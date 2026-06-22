"""Absorb: the LLM "writer" loop that compiles raw entries into wiki articles.

Adapted from the wiki-gen skill for a company knowledge brain. This is NOT a
mechanical filer: it reads each raw entry, understands what it means, matches it
against the existing index, integrates a new dimension into the right
article(s) (re-reading before editing), and spins out concept/pattern articles.

SDK: Anthropic Claude Agent SDK. The agent works directly on the wiki directory
(cwd) using Read/Write/Edit/Glob/Grep, which suits a single competent writer with
a large context window. After each checkpoint batch the control files are
rebuilt, entries are marked absorbed, and changed pages are mirrored to Notion.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from company_brain.config import AppConfig, load_config, resolve_wiki_dir
from company_brain.ingestion.entry import RawEntry
from company_brain.ingestion.pipeline import IngestionPipeline
from company_brain.notion.sync import NotionSync
from company_brain.wiki.index import WikiIndex
from company_brain.wiki.store import LocalWikiStore, WikiStore

logger = logging.getLogger(__name__)

CHECKPOINT_EVERY = 15

SYSTEM_PROMPT = """You are a writer compiling a company knowledge wiki from raw \
entries. You are not a filing clerk. Read entries, understand what they mean, and \
write articles that capture understanding. The wiki is a map of the company: its \
projects, people, decisions, systems, customers, patterns, and principles.

Rules:
- The working directory is the wiki root. Articles live at <section>/<slug>.md.
- Each article has YAML frontmatter: title, type, section, related (a list of \
[[wikilinks]]), sources (raw entry ids), created, last_updated. Body organized by \
THEME, not chronology.
- Match each entry against existing articles first (read _index.md). Re-read an \
article fully before editing it. Integrate the new dimension; never just append.
- Create concept/pattern articles when a theme recurs. Anti-cram (don't pile a \
third sub-topic into a big article - split it) and anti-thin (every page you touch \
must get richer; no 3-sentence stubs when more material exists).
- Cite sources by raw entry id in frontmatter. Use [[wikilinks]] between articles.
- Tone: Wikipedia. Flat, factual. No em dashes, no peacock words, no editorial \
voice. Let direct quotes (max 2 per article) carry any emotional weight.
- Do NOT edit _index.md, _backlinks.json, or _absorb_log.json; those are rebuilt \
automatically.
"""


class AbsorbWriter:
    """Runs the LLM absorption loop over unabsorbed raw entries."""

    def __init__(
        self,
        config: AppConfig | None = None,
        store: WikiStore | None = None,
        pipeline: IngestionPipeline | None = None,
        model: str | None = None,
    ):
        self.config = config or load_config()
        self.store = store or LocalWikiStore()
        self.pipeline = pipeline or IngestionPipeline()
        self.model = model
        self.wiki_dir: Path = resolve_wiki_dir()

    def run(self, *, since=None) -> dict[str, Any]:
        entries = (
            self.pipeline.load_entries_since(since) if since
            else self.pipeline.load_unabsorbed()
        )
        entries.sort(key=lambda e: e.timestamp)
        if not entries:
            logger.info("No unabsorbed entries to process")
            return {"absorbed": 0, "batches": 0}

        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        batches = [
            entries[i:i + CHECKPOINT_EVERY]
            for i in range(0, len(entries), CHECKPOINT_EVERY)
        ]
        for n, batch in enumerate(batches, 1):
            logger.info("Absorb batch %d/%d (%d entries)", n, len(batches), len(batch))
            try:
                asyncio.run(self._absorb_batch(batch))
            except ImportError as e:
                raise RuntimeError(
                    "claude-agent-sdk not installed. Add it to dependencies: "
                    "pip install claude-agent-sdk"
                ) from e
            self._checkpoint(batch)

        synced = NotionSync(store=self.store, config=self.config).sync_all()
        logger.info("Absorb complete: %d entries, %d pages synced", len(entries), len(synced))
        return {"absorbed": len(entries), "batches": len(batches), "synced": len(synced)}

    async def _absorb_batch(self, batch: list[RawEntry]) -> None:
        from claude_agent_sdk import ClaudeAgentOptions, query

        from company_brain.llm import claude as llm_claude

        prompt = self._build_prompt(batch)
        options = ClaudeAgentOptions(
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
            permission_mode="acceptEdits",
            cwd=str(self.wiki_dir),
            system_prompt=SYSTEM_PROMPT,
            env=llm_claude.options_env(),
            **llm_claude.model_kwargs(self.model),
        )
        async for _ in query(prompt=prompt, options=options):
            pass

    def _build_prompt(self, batch: list[RawEntry]) -> str:
        blocks = []
        for e in batch:
            blocks.append(
                f"### entry id: {e.id}\n"
                f"date: {e.timestamp.date()}  source: {e.source_type}  title: {e.title}\n\n"
                f"{e.content}\n"
            )
        entries_text = "\n---\n".join(blocks)
        return (
            "Read _index.md, then absorb the following raw entries into the wiki, "
            "updating and creating articles as needed. Cite each entry id in the "
            "sources frontmatter of every article it informs.\n\n"
            f"{entries_text}"
        )

    def _checkpoint(self, batch: list[RawEntry]) -> None:
        index = WikiIndex(self.store)
        index.load()
        index.rebuild_control_files()
        self.pipeline.mark_absorbed([e.id for e in batch], [])
