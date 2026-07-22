"""CLI wrapper for ``lsearch`` / ``local-search`` (Kevin-Liu-01/local-search)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from company_brain.web_search.config import lsearch_settings

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    title: str = ""
    url: str = ""
    snippet: str = ""
    content: str = ""


@dataclass
class SearchResponse:
    ok: bool
    backend: str = "lsearch"
    hits: list[SearchHit] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class ReadResponse:
    ok: bool
    backend: str = "lsearch"
    url: str = ""
    text: str = ""
    error: str = ""


def resolve_binary(settings: dict[str, Any] | None = None) -> str | None:
    settings = settings or lsearch_settings()
    preferred = str(settings.get("binary") or "lsearch").strip() or "lsearch"
    for name in (preferred, "lsearch", "local-search"):
        path = shutil.which(name)
        if path:
            return path
    return None


def available() -> bool:
    return resolve_binary() is not None


def search(
    query: str,
    *,
    limit: int | None = None,
    with_content: bool | None = None,
    engine: str | None = None,
) -> SearchResponse:
    settings = lsearch_settings()
    binary = resolve_binary(settings)
    if not binary:
        return SearchResponse(ok=False, error="lsearch_not_found")

    lim = int(limit if limit is not None else settings.get("limit") or 5)
    eng = str(engine or settings.get("engine") or "google").strip() or "google"
    use_content = bool(settings.get("with_content")) if with_content is None else bool(with_content)
    timeout = float(settings.get("timeout_seconds") or 90)
    content_chars = int(settings.get("content_chars") or 1200)

    cmd = [
        binary,
        "search",
        query,
        "--limit",
        str(max(1, lim)),
        "--engine",
        eng,
    ]
    if use_content:
        cmd.extend(["--with-content", "--content-chars", str(max(100, content_chars))])

    proc = _run(cmd, timeout=timeout)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "lsearch_failed").strip()
        return SearchResponse(ok=False, error=err[:500])

    payload = _parse_json(proc.stdout)
    if not payload.get("ok", True) and "error" in payload:
        err = payload.get("error")
        msg = err.get("message") if isinstance(err, dict) else str(err)
        return SearchResponse(ok=False, error=str(msg), raw=payload)

    hits = _hits_from_payload(payload)
    return SearchResponse(ok=True, hits=hits, raw=payload)


def read_url(url: str, *, fmt: str = "markdown") -> ReadResponse:
    settings = lsearch_settings()
    binary = resolve_binary(settings)
    if not binary:
        return ReadResponse(ok=False, url=url, error="lsearch_not_found")

    timeout = float(settings.get("timeout_seconds") or 90)
    cmd = [binary, "read", url, "--format", fmt]
    proc = _run(cmd, timeout=timeout)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "lsearch_read_failed").strip()
        return ReadResponse(ok=False, url=url, error=err[:500])

    text = (proc.stdout or "").strip()
    # JSON format wraps content; markdown/text is raw stdout.
    if fmt == "json":
        payload = _parse_json(text)
        if isinstance(payload, dict):
            text = str(
                payload.get("markdown") or payload.get("text") or payload.get("content") or text
            )
    return ReadResponse(ok=bool(text), url=url, text=text)


def cleanup(*, kill: bool = True) -> None:
    settings = lsearch_settings()
    if not settings.get("cleanup_after", True):
        return
    binary = resolve_binary(settings)
    if not binary:
        return
    cmd = [binary, "cleanup"]
    if kill:
        cmd.append("--kill")
    try:
        _run(cmd, timeout=30)
    except Exception:
        logger.debug("lsearch cleanup failed", exc_info=True)


def _run(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    logger.debug("lsearch: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Some versions may emit non-JSON preamble — try last JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _hits_from_payload(payload: dict[str, Any]) -> list[SearchHit]:
    raw_hits = payload.get("results") or payload.get("hits") or payload.get("items") or []
    if not isinstance(raw_hits, list):
        return []
    out: list[SearchHit] = []
    for item in raw_hits:
        if not isinstance(item, dict):
            continue
        out.append(
            SearchHit(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or item.get("link") or ""),
                snippet=str(item.get("snippet") or item.get("description") or ""),
                content=str(item.get("content") or item.get("text") or ""),
            )
        )
    return out
