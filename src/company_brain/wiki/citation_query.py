"""Citation-only Query — grant-aware employee/company search for console + CLI.

Returns snippets + Notion citation URLs (MD path when unbound). Admin bypasses
``query_grants``. Supports live employee trees and git ``archive/employee/{member}``
branches after offboard. Never dumps full pages in the result list — use
``expand_result`` for one path at a time.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from company_brain.config import resolve_employee_wiki_dir, resolve_wiki_dir
from company_brain.members_config import MembersConfig, load_members_config
from company_brain.wiki.employee_store import LocalEmployeeWikiStore
from company_brain.wiki.retrieve import retrieve
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc, WikiStore

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 8
DENY_COMPANY_PREFIXES = ("admin/", "raw/")


@dataclass
class CitationHit:
    rel_path: str
    title: str
    snippet: str
    score: float
    volume: str  # company | employee | archive
    member: str = ""
    notion_page_id: str = ""
    citation: str = ""
    sync: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CitationQueryResult:
    hits: list[CitationHit] = field(default_factory=list)
    as_member: str = ""
    admin_bypass: bool = False
    people_hints: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": [h.to_dict() for h in self.hits],
            "as_member": self.as_member,
            "admin_bypass": self.admin_bypass,
            "people_hints": list(self.people_hints),
        }


def notion_citation(page_id: str, *, rel_path: str = "") -> str:
    pid = (page_id or "").strip()
    if pid:
        return f"https://www.notion.so/{pid.replace('-', '')}"
    return rel_path


def is_admin_member(member_key: str, *, members: MembersConfig | None = None) -> bool:
    cfg = members or load_members_config()
    spec = cfg.get(member_key)
    return bool(spec and spec.is_admin)


def granted_employee_prefixes(
    as_member: str,
    *,
    members: MembersConfig | None = None,
    admin_bypass: bool | None = None,
) -> list[tuple[str, str]]:
    """Return ``(member_key, path_prefix)`` pairs the querier may search.

    ``query_grants`` lives on the *owner* spec: keys are grantee member keys,
    values are prefixes under that owner's tree.
    """
    cfg = members or load_members_config()
    bypass = admin_bypass if admin_bypass is not None else is_admin_member(as_member, members=cfg)
    out: list[tuple[str, str]] = []
    if bypass:
        for key in cfg.members:
            out.append((key, f"{key}/"))
        return out
    # Own tree always
    if as_member in cfg.members:
        out.append((as_member, f"{as_member}/"))
    for owner_key, spec in cfg.members.items():
        if owner_key == as_member:
            continue
        grants = (spec.query_grants or {}).get(as_member) or []
        for prefix in grants:
            p = str(prefix).strip().strip("/")
            if not p:
                continue
            if not p.startswith(f"{owner_key}/"):
                p = f"{owner_key}/{p}"
            out.append((owner_key, p + "/"))
    # Dedupe
    seen: set[tuple[str, str]] = set()
    uniq: list[tuple[str, str]] = []
    for item in out:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq


def citation_query(
    question: str,
    *,
    as_member: str = "",
    admin_bypass: bool | None = None,
    limit: int = DEFAULT_LIMIT,
    include_company: bool = True,
    company_store: WikiStore | None = None,
    members: MembersConfig | None = None,
    with_people_hints: bool = True,
) -> CitationQueryResult:
    """Search granted scopes; return citation-shaped hits (no full-page dump)."""
    cfg = members or load_members_config()
    member = (as_member or "").strip()
    if admin_bypass is True:
        bypass = True
    elif admin_bypass is False:
        bypass = False
    else:
        bypass = not member or is_admin_member(member, members=cfg)
    if not member and bypass:
        member = _first_admin_key(cfg) or "admin"

    hits: list[CitationHit] = []
    cstore = company_store or LocalWikiStore(root=resolve_wiki_dir())

    if include_company:
        hits.extend(
            _search_company(
                question,
                store=cstore,
                admin_bypass=bypass,
                limit=limit,
            )
        )

    for owner, prefix in granted_employee_prefixes(member, members=cfg, admin_bypass=bypass):
        hits.extend(
            _search_employee_member(
                question,
                owner_key=owner,
                prefix=prefix,
                limit=max(3, limit // 2),
                members=cfg,
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    hits = hits[:limit]

    people_hints: list[dict[str, Any]] = []
    if with_people_hints:
        try:
            from company_brain.wiki.who_knows import suggest_people

            people_hints = suggest_people(question, limit=3)
        except Exception:
            logger.debug("who_knows hints unavailable", exc_info=True)

    return CitationQueryResult(
        hits=hits,
        as_member=member,
        admin_bypass=bypass,
        people_hints=people_hints,
    )


def expand_result(
    rel_path: str,
    *,
    as_member: str = "",
    admin_bypass: bool | None = None,
    volume: str = "",
    member: str = "",
    members: MembersConfig | None = None,
) -> dict[str, Any]:
    """Load one page body when the querier is allowed — expand-one-at-a-time."""
    cfg = members or load_members_config()
    querier = (as_member or "").strip()
    bypass = (
        True
        if admin_bypass is True
        else (
            False
            if admin_bypass is False
            else (not querier or is_admin_member(querier, members=cfg))
        )
    )
    vol = (volume or "").strip() or _guess_volume(rel_path)
    owner = (member or "").strip() or _owner_from_path(rel_path, vol)

    if vol == "company":
        try:
            store = LocalWikiStore(root=resolve_wiki_dir())
            doc = store.read(rel_path)
        except FileNotFoundError:
            return {"status": "missing"}
        sync = str((doc.frontmatter or {}).get("sync") or "")
        if not bypass and sync in {"admin_only", "not_synced"}:
            return {"status": "denied", "reason": "sync_denied"}
        return _expanded_payload(rel_path, doc, volume="company")

    # Employee / archive
    if not bypass and not _employee_path_allowed(querier, owner, rel_path, members=cfg):
        return {"status": "denied", "reason": "query_grants"}

    body_doc = _read_employee_or_archive(owner, rel_path)
    if body_doc is None:
        return {"status": "missing", "volume": vol or "employee", "member": owner}
    return _expanded_payload(
        rel_path,
        body_doc,
        volume="archive" if _member_archived(owner, cfg) else "employee",
        member=owner,
    )


def _search_company(
    question: str,
    *,
    store: WikiStore,
    admin_bypass: bool,
    limit: int,
) -> list[CitationHit]:
    def allow(rel: str, doc: MarkdownDoc) -> bool:
        sync = str((doc.frontmatter or {}).get("sync") or "")
        if not admin_bypass and sync in {"admin_only", "not_synced"}:
            return False
        return True

    deny = DENY_COMPANY_PREFIXES if not admin_bypass else ("raw/",)
    raw = retrieve(
        question,
        store=store,
        allow=allow,
        deny_prefixes=deny,
        limit=limit,
        snippet_chars=600,
    )
    out: list[CitationHit] = []
    for hit in raw:
        pid = str(hit.get("notion_page_id") or "")
        rel = str(hit["rel_path"])
        out.append(
            CitationHit(
                rel_path=rel,
                title=str(hit.get("title") or rel),
                snippet=str(hit.get("snippet") or "")[:600],
                score=float(hit.get("score") or 0),
                volume="company",
                notion_page_id=pid,
                citation=notion_citation(pid, rel_path=rel),
            )
        )
    return out


def _search_employee_member(
    question: str,
    *,
    owner_key: str,
    prefix: str,
    limit: int,
    members: MembersConfig,
) -> list[CitationHit]:
    store, volume = _employee_store(owner_key, members=members)
    if store is None:
        return []

    def allow(rel: str, doc: MarkdownDoc) -> bool:
        if not rel.startswith(prefix.rstrip("/") + "/") and rel != prefix.rstrip("/"):
            if not rel.startswith(owner_key + "/"):
                # store may be rooted at member dir — paths without member prefix
                pass
            elif not (rel.startswith(prefix) or rel == prefix.rstrip("/")):
                return False
        sync = str((doc.frontmatter or {}).get("sync") or "private")
        return sync in {"private", "company", "not_synced"} or sync.startswith("location:")

    # When store is member-rooted, prefixes are relative without member key
    member_root = resolve_employee_wiki_dir() / owner_key
    search_prefixes: list[str] | None = None
    if member_root.is_dir() and isinstance(store, LocalEmployeeWikiStore):
        # LocalEmployeeWikiStore is rooted at employee_wiki/ — paths include member/
        search_prefixes = [prefix]
    elif volume == "archive":
        search_prefixes = None  # whole temp tree

    raw = retrieve(
        question,
        store=store,
        prefixes=search_prefixes,
        allow=allow,
        limit=limit,
        snippet_chars=600,
    )
    out: list[CitationHit] = []
    for hit in raw:
        rel = str(hit["rel_path"])
        if not rel.startswith(owner_key + "/") and "/" not in rel.split("/", 1)[0]:
            rel = f"{owner_key}/{rel}"
        if not (rel.startswith(prefix) or rel.startswith(owner_key + "/")):
            continue
        pid = str(hit.get("notion_page_id") or "")
        out.append(
            CitationHit(
                rel_path=rel,
                title=str(hit.get("title") or rel),
                snippet=str(hit.get("snippet") or "")[:600],
                score=float(hit.get("score") or 0),
                volume=volume,
                member=owner_key,
                notion_page_id=pid,
                citation=notion_citation(pid, rel_path=rel),
                sync=str(hit.get("sync") or ""),
            )
        )
    return out


def _employee_store(owner_key: str, *, members: MembersConfig) -> tuple[WikiStore | None, str]:
    live = resolve_employee_wiki_dir() / owner_key
    if live.is_dir():
        return LocalEmployeeWikiStore(root=resolve_employee_wiki_dir()), "employee"
    if _member_archived(owner_key, members):
        cached = _materialize_archive(owner_key)
        if cached is not None:
            return LocalWikiStore(root=cached), "archive"
    return None, "employee"


def _read_employee_or_archive(owner_key: str, rel_path: str) -> MarkdownDoc | None:
    members = load_members_config()
    store, _vol = _employee_store(owner_key, members=members)
    if store is None:
        return None
    # Normalize path relative to store root
    candidates = [rel_path]
    if rel_path.startswith(f"{owner_key}/"):
        candidates.append(rel_path[len(owner_key) + 1 :])
    for cand in candidates:
        if store.exists(cand):
            try:
                return store.read(cand)
            except FileNotFoundError:
                continue
    return None


def _materialize_archive(member_key: str) -> Path | None:
    """Checkout ``archive/employee/{member}`` into a temp cache when possible."""
    from company_brain.agents.admin import wiki_commit_config as wiki_git

    work = wiki_git.wiki_commit_work_dir()
    if not work or not Path(work).is_dir():
        return None
    branch = f"archive/employee/{member_key}"
    cache = Path(tempfile.gettempdir()) / "company-brain-archive" / member_key
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        # Fresh sparse export via git archive
        if cache.exists():
            return cache if any(cache.iterdir()) else None
        cache.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["git", "-C", str(work), "archive", branch],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            logger.info("archive branch %s unavailable: %s", branch, proc.stderr[:200])
            return None
        import io
        import tarfile

        with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tar:
            tar.extractall(path=cache)
        return cache
    except Exception:
        logger.exception("Failed to materialize archive for %s", member_key)
        return None


def _member_archived(member_key: str, members: MembersConfig) -> bool:
    spec = members.get(member_key)
    return bool(spec and spec.wiki_archived)


def _employee_path_allowed(
    querier: str,
    owner: str,
    rel_path: str,
    *,
    members: MembersConfig,
) -> bool:
    if not querier:
        return False
    if querier == owner:
        return True
    if is_admin_member(querier, members=members):
        return True
    for ok, prefix in granted_employee_prefixes(querier, members=members, admin_bypass=False):
        if ok != owner:
            continue
        if rel_path.startswith(prefix) or rel_path.startswith(owner + "/"):
            return True
    return False


def _expanded_payload(
    rel_path: str,
    doc: MarkdownDoc,
    *,
    volume: str,
    member: str = "",
) -> dict[str, Any]:
    fm = dict(doc.frontmatter or {})
    pid = str(fm.get("notion_page_id") or "")
    return {
        "status": "ok",
        "rel_path": rel_path,
        "title": str(fm.get("title") or rel_path),
        "body": (doc.body or "")[:12000],
        "volume": volume,
        "member": member,
        "notion_page_id": pid,
        "citation": notion_citation(pid, rel_path=rel_path),
        "sync": str(fm.get("sync") or ""),
    }


def _first_admin_key(cfg: MembersConfig) -> str:
    for key, spec in cfg.members.items():
        if spec.is_admin:
            return key
    return ""


def _guess_volume(rel_path: str) -> str:
    if rel_path.startswith("archive/employee/"):
        return "archive"
    # Heuristic: top segment matches a member key
    members = load_members_config()
    top = rel_path.split("/", 1)[0]
    if top in members.members:
        return "archive" if _member_archived(top, members) else "employee"
    return "company"


def _owner_from_path(rel_path: str, volume: str) -> str:
    if volume in {"employee", "archive"}:
        return rel_path.split("/", 1)[0]
    return ""


def format_cli_results(result: CitationQueryResult) -> str:
    if not result.hits:
        lines = ["No matching pages in granted scope."]
    else:
        lines = [f"Found {len(result.hits)} hit(s) (as `{result.as_member}`):", ""]
        for i, hit in enumerate(result.hits, 1):
            lines.append(f"{i}. {hit.title}")
            lines.append(f"   path: {hit.rel_path} [{hit.volume}]")
            lines.append(f"   cite: {hit.citation}")
            snip = hit.snippet.replace("\n", " ")[:160]
            lines.append(f"   snippet: {snip}")
            lines.append("")
    if result.people_hints:
        lines.append("People who may know:")
        for p in result.people_hints:
            lines.append(f"  • {p.get('name') or p.get('member')} — {p.get('reason', '')}")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "CitationHit",
    "CitationQueryResult",
    "citation_query",
    "expand_result",
    "format_cli_results",
    "granted_employee_prefixes",
    "notion_citation",
]
