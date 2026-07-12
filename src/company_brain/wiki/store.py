"""WikiStore: the Markdown source of truth for the company wiki.

Each wiki page is a Markdown file with a YAML frontmatter block. The store is
backend-agnostic: ``LocalWikiStore`` writes to a local directory today; on a
cloud VM that directory is a mounted shared volume (``/workspace/wiki``), and a
future ``CloudWikiStore`` can implement the same interface against the cloud
service without touching agent code.

Writes are atomic (temp file + rename) so the shared volume stays consistent
across VMs, and every write stamps a ``content_hash`` so NotionSync can cheaply
skip unchanged pages.
"""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from company_brain.config import resolve_wiki_dir

# Control files live at the wiki root and are never treated as content pages.
CONTROL_FILES = {"_index.md", "_backlinks.json", "_absorb_log.json"}


def compute_hash(body: str) -> str:
    """Stable content hash of a page body (drives change-detection for sync)."""
    return "sha256:" + hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


@dataclass
class MarkdownDoc:
    """A wiki page: YAML frontmatter + Markdown body."""

    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""

    @property
    def content_hash(self) -> str:
        return compute_hash(self.body)

    def serialize(self) -> str:
        fm = dict(self.frontmatter)
        fm["content_hash"] = self.content_hash
        yaml_block = yaml.safe_dump(fm, default_flow_style=False, sort_keys=False).strip()
        return f"---\n{yaml_block}\n---\n\n{self.body.strip()}\n"

    @classmethod
    def parse(cls, text: str) -> "MarkdownDoc":
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = yaml.safe_load(parts[1]) or {}
                body = parts[2].lstrip("\n")
                return cls(frontmatter=fm, body=body)
        return cls(frontmatter={}, body=text)


class WikiStore(ABC):
    """Abstract Markdown wiki store."""

    @abstractmethod
    def read(self, rel_path: str) -> MarkdownDoc: ...

    @abstractmethod
    def write(self, rel_path: str, doc: MarkdownDoc) -> None: ...

    @abstractmethod
    def exists(self, rel_path: str) -> bool: ...

    @abstractmethod
    def list(self, subdir: str | None = None) -> list[str]: ...

    @abstractmethod
    def abspath(self, rel_path: str) -> Path: ...

    @abstractmethod
    def delete(self, rel_path: str) -> None: ...

    def read_text(self, rel_path: str) -> str:
        """Read a raw file (e.g. a control file) as text, or '' if missing."""
        path = self.abspath(rel_path)
        return path.read_text() if path.exists() else ""

    def write_text(self, rel_path: str, text: str) -> None:
        """Write a raw control file atomically."""
        path = self.abspath(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, text)


class LocalWikiStore(WikiStore):
    """WikiStore backed by a local directory (or a mounted shared volume)."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else resolve_wiki_dir()

    def abspath(self, rel_path: str) -> Path:
        return self.root / rel_path

    def exists(self, rel_path: str) -> bool:
        return self.abspath(rel_path).exists()

    def read(self, rel_path: str) -> MarkdownDoc:
        path = self.abspath(rel_path)
        if not path.exists():
            raise FileNotFoundError(rel_path)
        return MarkdownDoc.parse(path.read_text())

    def write(self, rel_path: str, doc: MarkdownDoc) -> None:
        path = self.abspath(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, doc.serialize())

    def list(self, subdir: str | None = None) -> list[str]:
        base = self.root / subdir if subdir else self.root
        if not base.exists():
            return []
        out: list[str] = []
        for path in sorted(base.rglob("*.md")):
            if path.name in CONTROL_FILES:
                continue
            out.append(path.relative_to(self.root).as_posix())
        return out

    def delete(self, rel_path: str) -> None:
        path = self.abspath(rel_path)
        if path.exists():
            path.unlink()


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
