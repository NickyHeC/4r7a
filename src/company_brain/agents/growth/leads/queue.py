"""Lead research job queue (wiki JSON files under ``growth/leads/queue/``)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.config import resolve_wiki_dir

QUEUE_DIR = "growth/leads/queue"


def _queue_root(wiki_root: Path | None = None) -> Path:
    root = Path(wiki_root or resolve_wiki_dir())
    path = root / QUEUE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def enqueue_lead_job(
    *,
    source: str,
    label: str,
    payload: dict[str, Any],
    wiki_root: Path | None = None,
) -> dict[str, Any]:
    job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    job = {
        "id": job_id,
        "source": source,
        "label": label,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    path = _queue_root(wiki_root) / f"{job_id}.json"
    path.write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return job


def list_pending_jobs(*, wiki_root: Path | None = None) -> list[dict[str, Any]]:
    root = _queue_root(wiki_root)
    jobs: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "pending":
            jobs.append(data)
    return jobs


def mark_job(
    job_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    wiki_root: Path | None = None,
) -> None:
    path = _queue_root(wiki_root) / f"{job_id}.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = status
    data["finished_at"] = datetime.now(timezone.utc).isoformat()
    if result is not None:
        data["result"] = result
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
