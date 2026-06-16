"""Mercury data client — READ ONLY.

This client only ever *reads* from Mercury (accounts, transactions, statements,
treasury, categories). It deliberately exposes no money-movement operations
(no payments, transfers, recipients, or account changes): agent-driven writes
to a bank are high-risk and the tooling is immature, while read-only access
already unlocks the accounting/finance analysis value. Keep it that way — use a
read-only ``MERCURY_TOKEN`` and do not add write methods here.

Prefers the ``mercury`` CLI subprocess (faster, no extra auth dance) but falls
back to direct HTTP against the Mercury REST API if the CLI binary is missing
or errors. The CLI is invoked with ``--format jsonl`` so list endpoints stream
cleanly even across many pages.

Configuration (environment only — never hardcode company data):
  - ``MERCURY_TOKEN``   API token (read-only scope)
  - ``MERCURY_ENV``     ``production`` | ``sandbox`` (default ``production``)

CLI install: https://mercury.com/api
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import date
from typing import Iterable

MERCURY_BASE = "https://api.mercury.com/api/v1"


def _token() -> str:
    tok = os.getenv("MERCURY_TOKEN", "")
    if not tok:
        raise RuntimeError("MERCURY_TOKEN not set — see .env")
    return tok


def _env() -> str:
    return os.getenv("MERCURY_ENV", "production")


def _cli_available() -> bool:
    return shutil.which("mercury") is not None


# ---------------------------------------------------------------------------
# CLI invocation
# ---------------------------------------------------------------------------


def _run_cli(args: list[str]) -> list[dict]:
    """Run ``mercury <args> --format jsonl`` and parse JSON-lines output."""
    cmd = [
        "mercury",
        "--api-key", _token(),
        "--environment", _env(),
        "--format", "jsonl",
        *args,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"mercury CLI failed ({' '.join(args)}): {err[:300]}")

    records: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


# ---------------------------------------------------------------------------
# Direct HTTP fallback (used when CLI is missing or fails)
# ---------------------------------------------------------------------------


def _http_get(path: str, params: dict | None = None) -> dict:
    import requests

    headers = {"Authorization": f"Bearer {_token()}"}
    resp = requests.get(f"{MERCURY_BASE}{path}", headers=headers, params=params or {})
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_accounts() -> list[dict]:
    """Return all bank (depository) accounts."""
    if _cli_available():
        try:
            return _run_cli(["accounts", "list", "--max-items", "-1"])
        except RuntimeError as e:
            print(f"  [cli fallback] {e}")
    return _http_get("/accounts").get("accounts", [])


def list_credit_accounts() -> list[dict]:
    """Return Mercury IO Credit Card accounts."""
    if _cli_available():
        try:
            data = _run_cli(["credit", "list"])
            if data and "accounts" in data[0]:
                return data[0]["accounts"]
            return data
        except RuntimeError as e:
            print(f"  [cli fallback] {e}")
    return _http_get("/credit").get("accounts", [])


def list_treasury_accounts() -> list[dict]:
    """Return treasury (money market) accounts."""
    if _cli_available():
        try:
            data = _run_cli(["treasury", "list"])
            if data and "accounts" in data[0]:
                return data[0]["accounts"]
            return data
        except RuntimeError as e:
            print(f"  [cli fallback] {e}")
    try:
        return _http_get("/treasury").get("accounts", [])
    except Exception:
        return []


def list_categories() -> list[dict]:
    """Return Mercury expense categories."""
    if _cli_available():
        try:
            return _run_cli(["categories", "list", "--max-items", "-1"])
        except RuntimeError as e:
            print(f"  [cli fallback] {e}")
    return _http_get("/categories").get("categories", [])


def list_transactions(
    account_id: str,
    start: str | None = None,
    end: str | None = None,
    max_items: int = -1,
) -> list[dict]:
    """List transactions for a single account.

    *start* / *end* are ``YYYY-MM-DD`` strings (inclusive).
    """
    if _cli_available():
        args = [
            "transactions", "list",
            "--account-id", account_id,
            "--max-items", str(max_items),
        ]
        if start:
            args += ["--start", start]
        if end:
            args += ["--end", end]
        try:
            return _run_cli(args)
        except RuntimeError as e:
            print(f"  [cli fallback] {e}")

    out: list[dict] = []
    offset = 0
    while True:
        params: dict = {"limit": 500, "offset": offset}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        data = _http_get(f"/account/{account_id}/transactions", params)
        batch = data.get("transactions", [])
        out.extend(batch)
        if len(batch) < 500:
            break
        offset += 500
        if max_items > 0 and len(out) >= max_items:
            return out[:max_items]
    return out


def list_all_transactions(
    accounts: Iterable[dict],
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Fetch transactions across a set of accounts, tagging account metadata."""
    out: list[dict] = []
    for acct in accounts:
        aid = acct["id"]
        name = acct.get("nickname") or acct.get("name") or aid[:8]
        for t in list_transactions(aid, start=start, end=end):
            out.append({**t, "_account_id": aid, "_account_name": name})
    return out


def list_account_statements(account_id: str) -> list[dict]:
    """List monthly statements for an account."""
    if _cli_available():
        try:
            args = ["statements", "accounts", "list",
                    "--account-id", account_id, "--max-items", "-1"]
            return _run_cli(args)
        except RuntimeError as e:
            print(f"  [cli fallback] {e}")
    try:
        return _http_get(f"/account/{account_id}/statements").get("statements", [])
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Transaction interpretation helpers
# ---------------------------------------------------------------------------


def is_internal_transfer(txn: dict) -> bool:
    """Return True for transfers between Mercury accounts (excluded from P&L).

    Covers internal account-to-account transfers, treasury transfers, and
    credit-card autopay.
    """
    kind = txn.get("kind", "")
    if kind in ("internalTransfer", "treasuryTransfer"):
        return True
    desc = (txn.get("bankDescription") or "").upper()
    if "IO AUTOPAY" in desc:
        return True
    cp = (txn.get("counterpartyName") or "").upper()
    if cp.startswith("MERCURY ") and "MERCURY TECHNOLOGIES" not in cp:
        return True
    return False


def is_credit_card_txn(txn: dict) -> bool:
    return txn.get("kind") == "creditCardTransaction"


def txn_category(txn: dict) -> str:
    """Best-effort expense category from Mercury's own classification."""
    gl = txn.get("generalLedgerCodeName")
    if gl:
        return gl
    cat = txn.get("categoryData") or {}
    if isinstance(cat, dict) and cat.get("name"):
        return cat["name"]
    merc = txn.get("mercuryCategory")
    if merc:
        return merc
    return "Uncategorized"


def txn_counterparty(txn: dict) -> str:
    return (txn.get("counterpartyName") or txn.get("bankDescription") or "Unknown").strip()


def txn_date(txn: dict) -> str:
    return (txn.get("postedAt") or txn.get("createdAt") or "")[:10]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def parse_month(month_str: str) -> tuple[str, str]:
    """``2026-04`` -> ``(2026-04-01, 2026-04-30)``."""
    import calendar

    year, month = int(month_str[:4]), int(month_str[5:7])
    last = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last:02d}"


def quarter_end(quarter_str: str) -> date:
    import calendar

    year = int(quarter_str[:4])
    q = int(quarter_str[-1])
    month = q * 3
    return date(year, month, calendar.monthrange(year, month)[1])


def month_end(month_str: str) -> date:
    import calendar

    year, month = int(month_str[:4]), int(month_str[5:7])
    return date(year, month, calendar.monthrange(year, month)[1])


def current_quarter() -> str:
    today = date.today()
    return f"{today.year}-Q{(today.month - 1) // 3 + 1}"


def fmt_money(val: float) -> str:
    if val < 0:
        return f"(${abs(val):,.2f})"
    return f"${val:,.2f}"
