"""Path allow-list for Weave implement+prove diffs."""

from __future__ import annotations

from company_brain.agents.admin.weave_builder_config import weave_builder_config


def normalize_rel(path: str) -> str:
    rel = (path or "").replace("\\", "/").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")


def path_allowed(path: str, *, cfg: dict | None = None) -> bool:
    """Return True if ``path`` is within the Weave builder allow-list."""
    cfg = cfg or weave_builder_config()
    rel = normalize_rel(path)
    if not rel or rel.endswith("/"):
        return False
    extras = list(cfg.get("extra_allow_prefixes") or [])
    prefixes = list(cfg.get("allow_prefixes") or [])
    suffixes = list(cfg.get("allow_suffixes") or [])
    if any(rel.startswith(p) for p in extras):
        return True
    if not any(rel.startswith(p) for p in prefixes):
        return False
    if not suffixes:
        return True
    return any(rel.endswith(s) for s in suffixes)


def check_changed_paths(
    paths: list[str],
    *,
    cfg: dict | None = None,
) -> tuple[bool, list[str]]:
    """Return ``(ok, disallowed_paths)`` for a list of changed relative paths."""
    cfg = cfg or weave_builder_config()
    bad = [normalize_rel(p) for p in paths if not path_allowed(p, cfg=cfg)]
    # preserve order, drop empties
    bad = [p for p in bad if p]
    return (len(bad) == 0, bad)
