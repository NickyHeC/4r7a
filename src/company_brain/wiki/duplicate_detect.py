"""Duplicate detection for employee wiki imports (tiers 1–4)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable

import yaml

from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore, task_detail_path
from company_brain.wiki.store import MarkdownDoc, WikiStore

FUZZY_THRESHOLD = 0.85

ARTIFACT_INLINE = re.compile(
    r"\b(?:linear:|ENG-|GRANOLA-|granola:|slack:)[A-Za-z0-9_-]+\b",
    re.I,
)
PATH_PREFIX_RE = re.compile(r"^(?:daily|para|notes|inbox|archive)/", re.I)


@dataclass
class FileDuplicateVerdict:
    path: str
    verdict: str  # link | import | review
    match_tier: str | int = "none"
    canonical: str | None = None
    artifact_ref: str | None = None
    candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], "none")}


@dataclass
class DuplicateReport:
    import_id: str
    files: list[FileDuplicateVerdict] = field(default_factory=list)
    member: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "import_id": self.import_id,
            "files": [f.to_dict() for f in self.files],
        }
        if self.member:
            out["member"] = self.member
        if self.source:
            out["source"] = self.source
        return out

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def detect_duplicates(
    import_files: dict[str, str],
    *,
    member_key: str,
    import_id: str,
    company_store: WikiStore,
    employee_store: WikiStore,
    bindings: TaskBindingStore | None = None,
) -> DuplicateReport:
    """Run duplicate detection tiers 1–4 over quarantine-relative paths."""
    bindings = bindings or TaskBindingStore()
    company_index = _build_index(company_store.list(), company_store, scope="company")
    member_prefix = f"{member_key}/"
    member_index = _build_index(
        [p for p in employee_store.list() if p.startswith(member_prefix)],
        employee_store,
        scope="member",
    )
    other_index = _build_index(
        [p for p in employee_store.list() if not p.startswith(member_prefix)],
        employee_store,
        scope="other",
    )

    report = DuplicateReport(member=member_key, import_id=import_id)
    for rel_path, raw in import_files.items():
        report.files.append(
            _classify_file(
                rel_path,
                raw,
                company_index=company_index,
                member_index=member_index,
                other_index=other_index,
                bindings=bindings,
            )
        )
    return report


def detect_external_duplicates(
    import_files: dict[str, str],
    *,
    source_key: str,
    import_id: str,
    company_store: WikiStore,
    bindings: TaskBindingStore | None = None,
) -> DuplicateReport:
    """Duplicate detection for external wiki mounts (company store only)."""
    bindings = bindings or TaskBindingStore()
    paths = [
        p
        for p in company_store.list()
        if "/_quarantine/" not in p and not p.startswith("external/_quarantine/")
    ]
    company_index = _build_index(paths, company_store, scope="company")
    source_prefix = f"external/{source_key}/"
    same_source_index = _build_index(
        [p for p in paths if p.startswith(source_prefix)],
        company_store,
        scope="member",
    )
    other_external_index = _build_index(
        [
            p
            for p in paths
            if p.startswith("external/") and not p.startswith(source_prefix)
        ],
        company_store,
        scope="other",
    )

    report = DuplicateReport(import_id=import_id, source=source_key)
    for rel_path, raw in import_files.items():
        report.files.append(
            _classify_file(
                rel_path,
                raw,
                company_index=company_index,
                member_index=same_source_index,
                other_index=other_external_index,
                bindings=bindings,
            )
        )
    return report


def _classify_file(
    rel_path: str,
    raw: str,
    *,
    company_index: dict[str, _PageIndexEntry],
    member_index: dict[str, _PageIndexEntry],
    other_index: dict[str, _PageIndexEntry],
    bindings: TaskBindingStore,
) -> FileDuplicateVerdict:
    doc = MarkdownDoc.parse(raw)
    body_hash = _body_hash(doc.body)

    for index, tier in ((company_index, 1), (member_index, 1)):
        for entry in index.values():
            if entry.body_hash == body_hash:
                return FileDuplicateVerdict(
                    path=rel_path,
                    verdict="link",
                    match_tier=tier,
                    canonical=entry.rel_path,
                )

    refs = _artifact_refs(doc, raw)
    for ref in refs:
        binding = _binding_for_ref(ref, bindings)
        if binding:
            canonical = task_detail_path(binding)
            return FileDuplicateVerdict(
                path=rel_path,
                verdict="link",
                match_tier=2,
                canonical=canonical,
                artifact_ref=ref,
            )

    title = _normalize_title(doc.frontmatter.get("title") or _title_from_path(rel_path))
    if title:
        for index, tier, allow_link in (
            (company_index, 3, True),
            (member_index, 3, True),
            (other_index, 3, False),
        ):
            matches = [e.rel_path for e in index.values() if e.normalized_title == title]
            if matches:
                if allow_link and len(matches) == 1:
                    return FileDuplicateVerdict(
                        path=rel_path,
                        verdict="link",
                        match_tier=tier,
                        canonical=matches[0],
                    )
                return FileDuplicateVerdict(
                    path=rel_path,
                    verdict="review",
                    match_tier=tier,
                    candidates=matches[:5],
                )

    headings = _headings(doc.body)
    if headings:
        candidates: list[tuple[str, float]] = []
        for index in (company_index, member_index):
            for entry in index.values():
                score = _jaccard(headings, entry.headings)
                if score >= FUZZY_THRESHOLD:
                    candidates.append((entry.rel_path, score))
        candidates.sort(key=lambda x: x[1], reverse=True)
        if candidates:
            return FileDuplicateVerdict(
                path=rel_path,
                verdict="review",
                match_tier=4,
                candidates=[c[0] for c in candidates[:5]],
            )

    return FileDuplicateVerdict(path=rel_path, verdict="import", match_tier="none")


@dataclass
class _PageIndexEntry:
    rel_path: str
    normalized_title: str
    body_hash: str
    headings: set[str]
    artifact_refs: set[str]


def _build_index(paths: Iterable[str], store: WikiStore, *, scope: str) -> dict[str, _PageIndexEntry]:
    del scope  # reserved for future scope-specific rules
    index: dict[str, _PageIndexEntry] = {}
    for rel in paths:
        if rel.endswith("/_index.md") or "/imports/" in rel or "/_quarantine/" in rel:
            continue
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        title = _normalize_title(doc.frontmatter.get("title") or _title_from_path(rel))
        refs = set(doc.frontmatter.get("artifact_refs") or [])
        refs.update(_artifact_refs(doc, doc.body))
        index[rel] = _PageIndexEntry(
            rel_path=rel,
            normalized_title=title,
            body_hash=_body_hash(doc.body),
            headings=_headings(doc.body),
            artifact_refs=refs,
        )
    return index


def _body_hash(body: str) -> str:
    normalized = re.sub(r"\s+", " ", body.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _title_from_path(rel_path: str) -> str:
    stem = PurePosixPath(PATH_PREFIX_RE.sub("", rel_path)).stem
    return stem.replace("-", " ").replace("_", " ")


def _headings(body: str) -> set[str]:
    out: set[str] = set()
    for line in body.splitlines():
        m = re.match(r"^#{1,6}\s+(.+)$", line.strip())
        if m:
            out.add(_normalize_title(m.group(1)))
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _artifact_refs(doc: MarkdownDoc, raw: str) -> list[str]:
    refs: list[str] = []
    for item in doc.frontmatter.get("artifact_refs") or []:
        refs.append(str(item))
    for match in ARTIFACT_INLINE.finditer(raw):
        refs.append(match.group(0))
    eng = re.search(r"\b(ENG-\d+)\b", raw, re.I)
    if eng:
        refs.append(eng.group(1).upper())
    return list(dict.fromkeys(refs))


def _binding_for_ref(ref: str, bindings: TaskBindingStore):
    ref = ref.strip()
    ident = ref.upper().replace("LINEAR:", "")
    if ident.startswith("ENG-"):
        return bindings.find_by_linear(ident)
    if ref.lower().startswith("granola:"):
        return bindings.find_by_granola_note(ref.split(":", 1)[1])
    return None


def parse_duplicate_report(text: str) -> DuplicateReport:
    data = json.loads(text)
    files = [
        FileDuplicateVerdict(
            path=f["path"],
            verdict=f["verdict"],
            match_tier=f.get("match_tier", "none"),
            canonical=f.get("canonical"),
            artifact_ref=f.get("artifact_ref"),
            candidates=list(f.get("candidates") or []),
        )
        for f in data.get("files") or []
    ]
    return DuplicateReport(
        import_id=str(data.get("import_id") or ""),
        files=files,
        member=str(data.get("member") or ""),
        source=str(data.get("source") or ""),
    )


def load_frontmatter(raw: str) -> dict[str, Any]:
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            return yaml.safe_load(parts[1]) or {}
    return {}
