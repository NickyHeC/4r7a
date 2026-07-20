"""Google Ads data client — READ ONLY.

Exposes GAQL search and snapshot helpers only. Never mutates campaigns, budgets,
bids, ads, or recommendations. Use a read-only Google Ads user role when possible.

Configuration (environment only — never hardcode company secrets):
  - ``GOOGLE_ADS_DEVELOPER_TOKEN``
  - ``GOOGLE_ADS_CLIENT_ID``
  - ``GOOGLE_ADS_CLIENT_SECRET``
  - ``GOOGLE_ADS_REFRESH_TOKEN``
  - ``GOOGLE_ADS_CUSTOMER_ID`` (digits only or with dashes)
  - ``GOOGLE_ADS_LOGIN_CUSTOMER_ID`` (optional MCC login customer)

SDK: official ``google-ads`` Python client (lazy import). Tests mock ``search``.
"""

from __future__ import annotations

import calendar
import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

_ENV_KEYS = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_CUSTOMER_ID",
)


class GoogleAdsClientError(RuntimeError):
    pass


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def customer_id() -> str:
    """Return customer id with dashes stripped (API form)."""
    raw = _env("GOOGLE_ADS_CUSTOMER_ID").replace("-", "")
    if not raw:
        raise GoogleAdsClientError("GOOGLE_ADS_CUSTOMER_ID not set — see project_install.md")
    return raw


def login_customer_id() -> str | None:
    raw = _env("GOOGLE_ADS_LOGIN_CUSTOMER_ID").replace("-", "")
    return raw or None


def google_ads_is_configured() -> bool:
    return all(_env(k) for k in _ENV_KEYS)


def micros_to_currency(micros: int | float | None) -> float:
    if micros is None:
        return 0.0
    return float(micros) / 1_000_000.0


def format_currency(amount: float) -> str:
    return f"${amount:,.2f}"


def channel_type_label(raw: str | None) -> str:
    """Human label for ``advertising_channel_type`` enum / string."""
    if not raw:
        return "Unknown"
    text = str(raw).strip()
    # Proto enums may be "AdvertisingChannelType.SEARCH" or "SEARCH"
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    mapping = {
        "SEARCH": "Search",
        "PERFORMANCE_MAX": "Performance Max",
        "DISPLAY": "Display",
        "SHOPPING": "Shopping",
        "VIDEO": "Video",
        "MULTI_CHANNEL": "Multi-channel",
        "LOCAL": "Local",
        "SMART": "Smart",
        "DEMAND_GEN": "Demand Gen",
    }
    return mapping.get(text.upper(), text.replace("_", " ").title())


def period_budget_for_month(
    *,
    amount_micros: int,
    budget_period: str,
    year: int,
    month: int,
) -> float:
    """Currency amount representing the campaign budget for the calendar month.

    Daily budgets are scaled by days-in-month (monthly cycle approximation).
    Non-daily periods use the configured amount as the period cap.
    """
    amount = micros_to_currency(amount_micros)
    period = (budget_period or "").upper()
    if "." in period:
        period = period.rsplit(".", 1)[-1]
    if period in {"", "DAILY", "UNKNOWN", "UNSPECIFIED"}:
        days = calendar.monthrange(year, month)[1]
        return amount * days
    return amount


def pacing_percent(spend: float, period_budget: float) -> float | None:
    if period_budget <= 0:
        return None
    return (spend / period_budget) * 100.0


@dataclass(frozen=True)
class CampaignRow:
    campaign_id: str
    name: str
    status: str
    channel_type: str
    start_date: str
    end_date: str
    budget_id: str
    budget_name: str
    budget_amount_micros: int
    budget_period: str


@dataclass(frozen=True)
class BudgetPacingRow:
    campaign_id: str
    name: str
    status: str
    channel_type: str
    budget_amount_micros: int
    budget_period: str
    spend_micros: int
    period_budget: float
    spend: float
    percent_used: float | None


@dataclass(frozen=True)
class AcquisitionCostRow:
    campaign_id: str
    name: str
    channel_type: str
    cost_micros: int
    conversions: float
    clicks: int
    impressions: int
    cpa: float | None


def _credentials_dict() -> dict[str, Any]:
    missing = [k for k in _ENV_KEYS if not _env(k)]
    if missing:
        raise GoogleAdsClientError(
            f"Google Ads env incomplete (missing {', '.join(missing)}) — see project_install.md"
        )
    creds: dict[str, Any] = {
        "developer_token": _env("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": _env("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": _env("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": _env("GOOGLE_ADS_REFRESH_TOKEN"),
        "use_proto_plus": True,
    }
    login = login_customer_id()
    if login:
        creds["login_customer_id"] = login
    return creds


def _google_ads_client():
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError as exc:
        raise GoogleAdsClientError(
            "google-ads package not installed — pip install 'google-ads' "
            "(or pip install -e '.[google-ads]')"
        ) from exc
    return GoogleAdsClient.load_from_dict(_credentials_dict())


def _field_value(obj: Any, *path: str) -> Any:
    cur = obj
    for part in path:
        if cur is None:
            return None
        cur = getattr(cur, part, None)
    if cur is None:
        return None
    # Proto enums
    name = getattr(cur, "name", None)
    if isinstance(name, str) and name not in {"", "UNKNOWN", "UNSPECIFIED"}:
        return name
    return cur


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Best-effort flatten of a GoogleAdsRow for tests and light consumers."""
    campaign = getattr(row, "campaign", None)
    budget = getattr(row, "campaign_budget", None)
    metrics = getattr(row, "metrics", None)
    out: dict[str, Any] = {}
    if campaign is not None:
        out["campaign"] = {
            "id": str(_field_value(campaign, "id") or ""),
            "name": str(_field_value(campaign, "name") or ""),
            "status": str(_field_value(campaign, "status") or ""),
            "advertising_channel_type": str(
                _field_value(campaign, "advertising_channel_type") or ""
            ),
            "start_date": str(_field_value(campaign, "start_date") or ""),
            "end_date": str(_field_value(campaign, "end_date") or ""),
        }
    if budget is not None:
        amount = _field_value(budget, "amount_micros")
        out["campaign_budget"] = {
            "id": str(_field_value(budget, "id") or ""),
            "name": str(_field_value(budget, "name") or ""),
            "amount_micros": int(amount or 0),
            "period": str(_field_value(budget, "period") or ""),
        }
    if metrics is not None:
        out["metrics"] = {
            "cost_micros": int(_field_value(metrics, "cost_micros") or 0),
            "conversions": float(_field_value(metrics, "conversions") or 0.0),
            "clicks": int(_field_value(metrics, "clicks") or 0),
            "impressions": int(_field_value(metrics, "impressions") or 0),
            "cost_per_conversion": float(_field_value(metrics, "cost_per_conversion") or 0.0),
        }
    return out


def search(query: str, *, customer_id_override: str | None = None) -> list[dict[str, Any]]:
    """Run a GAQL query; return flattened row dicts. Read-only."""
    cid = (customer_id_override or customer_id()).replace("-", "")
    client = _google_ads_client()
    service = client.get_service("GoogleAdsService")
    try:
        response = service.search(customer_id=cid, query=query)
    except Exception as exc:
        raise GoogleAdsClientError(f"Google Ads search failed: {exc}") from exc
    return [_row_to_dict(row) for row in response]


def list_campaigns() -> list[CampaignRow]:
    """Active inventory snapshot (excludes REMOVED)."""
    query = """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.advertising_channel_type,
          campaign.start_date,
          campaign.end_date,
          campaign_budget.id,
          campaign_budget.name,
          campaign_budget.amount_micros,
          campaign_budget.period
        FROM campaign
        WHERE campaign.status != 'REMOVED'
        ORDER BY campaign.name
    """
    rows: list[CampaignRow] = []
    for raw in search(query):
        c = raw.get("campaign") or {}
        b = raw.get("campaign_budget") or {}
        rows.append(
            CampaignRow(
                campaign_id=str(c.get("id") or ""),
                name=str(c.get("name") or ""),
                status=str(c.get("status") or ""),
                channel_type=channel_type_label(str(c.get("advertising_channel_type") or "")),
                start_date=str(c.get("start_date") or ""),
                end_date=str(c.get("end_date") or ""),
                budget_id=str(b.get("id") or ""),
                budget_name=str(b.get("name") or ""),
                budget_amount_micros=int(b.get("amount_micros") or 0),
                budget_period=str(b.get("period") or ""),
            )
        )
    return rows


def list_budget_pacing(*, as_of: date | None = None) -> list[BudgetPacingRow]:
    """MTD spend vs period budget for non-removed campaigns."""
    as_of = as_of or date.today()
    query = """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.advertising_channel_type,
          campaign_budget.amount_micros,
          campaign_budget.period,
          metrics.cost_micros
        FROM campaign
        WHERE campaign.status != 'REMOVED'
          AND segments.date DURING THIS_MONTH
        ORDER BY campaign.name
    """
    # Aggregate cost if API returns multiple segment rows (shouldn't with DURING)
    by_id: dict[str, dict[str, Any]] = {}
    for raw in search(query):
        c = raw.get("campaign") or {}
        b = raw.get("campaign_budget") or {}
        m = raw.get("metrics") or {}
        cid = str(c.get("id") or "")
        if not cid:
            continue
        if cid not in by_id:
            by_id[cid] = {
                "campaign": c,
                "budget": b,
                "spend_micros": 0,
            }
        by_id[cid]["spend_micros"] += int(m.get("cost_micros") or 0)

    out: list[BudgetPacingRow] = []
    for cid, data in by_id.items():
        c = data["campaign"]
        b = data["budget"]
        amount_micros = int(b.get("amount_micros") or 0)
        period = str(b.get("period") or "")
        spend_micros = int(data["spend_micros"])
        period_budget = period_budget_for_month(
            amount_micros=amount_micros,
            budget_period=period,
            year=as_of.year,
            month=as_of.month,
        )
        spend = micros_to_currency(spend_micros)
        out.append(
            BudgetPacingRow(
                campaign_id=cid,
                name=str(c.get("name") or ""),
                status=str(c.get("status") or ""),
                channel_type=channel_type_label(str(c.get("advertising_channel_type") or "")),
                budget_amount_micros=amount_micros,
                budget_period=period,
                spend_micros=spend_micros,
                period_budget=period_budget,
                spend=spend,
                percent_used=pacing_percent(spend, period_budget),
            )
        )
    out.sort(key=lambda r: r.name.lower())
    return out


def list_acquisition_cost(*, during: str = "THIS_MONTH") -> list[AcquisitionCostRow]:
    """Cost / conversions snapshot for a GAQL date range keyword.

    ``during`` is e.g. ``THIS_MONTH`` or ``LAST_30_DAYS``.
    """
    during = during.strip().upper()
    if during not in {"THIS_MONTH", "LAST_30_DAYS", "LAST_7_DAYS"}:
        raise GoogleAdsClientError(f"Unsupported acquisition lookback: {during}")
    query = f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.advertising_channel_type,
          metrics.cost_micros,
          metrics.conversions,
          metrics.clicks,
          metrics.impressions
        FROM campaign
        WHERE campaign.status != 'REMOVED'
          AND segments.date DURING {during}
        ORDER BY campaign.name
    """
    by_id: dict[str, dict[str, Any]] = {}
    for raw in search(query):
        c = raw.get("campaign") or {}
        m = raw.get("metrics") or {}
        cid = str(c.get("id") or "")
        if not cid:
            continue
        if cid not in by_id:
            by_id[cid] = {
                "campaign": c,
                "cost_micros": 0,
                "conversions": 0.0,
                "clicks": 0,
                "impressions": 0,
            }
        by_id[cid]["cost_micros"] += int(m.get("cost_micros") or 0)
        by_id[cid]["conversions"] += float(m.get("conversions") or 0.0)
        by_id[cid]["clicks"] += int(m.get("clicks") or 0)
        by_id[cid]["impressions"] += int(m.get("impressions") or 0)

    out: list[AcquisitionCostRow] = []
    for cid, data in by_id.items():
        c = data["campaign"]
        cost_micros = int(data["cost_micros"])
        conversions = float(data["conversions"])
        cost = micros_to_currency(cost_micros)
        cpa = (cost / conversions) if conversions > 0 else None
        out.append(
            AcquisitionCostRow(
                campaign_id=cid,
                name=str(c.get("name") or ""),
                channel_type=channel_type_label(str(c.get("advertising_channel_type") or "")),
                cost_micros=cost_micros,
                conversions=conversions,
                clicks=int(data["clicks"]),
                impressions=int(data["impressions"]),
                cpa=cpa,
            )
        )
    out.sort(key=lambda r: r.name.lower())
    return out
