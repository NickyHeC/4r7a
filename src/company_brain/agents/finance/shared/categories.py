"""Spending category taxonomy and budget classification maps for finance agents.

This module holds GENERIC accounting taxonomy only. It must never contain
company-specific data (vendor names, account IDs, customers, real figures).
Company-specific keyword lists are intentionally left empty here and should be
populated at runtime from ``config/finance.yaml`` (see ``load_company_keywords``).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Spending category taxonomy (department -> subcategories).
# Generic, shareable; safe to open-source.
# ---------------------------------------------------------------------------

SPENDING_CATEGORIES: dict[str, list[str]] = {
    "Engineering": [
        "Cloud Infrastructure (Compute, Storage, Hosting)",
        "Model & API Usage (OpenAI, Anthropic, etc.)",
        "Dev Tools & SaaS (GitHub, Cursor, IDEs)",
        "DevOps & CI/CD",
        "Observability & Monitoring",
        "Security & Compliance Tools",
        "Data & Datasets",
    ],
    "Research": [
        "Research & Experimentation",
        "Research Compute (GPU / Fine-tuning)",
        "Academic & Conference Expenses",
        "Research Collaborations",
        "Publications & Submissions",
    ],
    "Product": [
        "Product Experimentation",
        "Product Analytics",
        "User Research & Testing",
        "Design Tools & Assets",
    ],
    "Growth": [
        "Paid Marketing (Ads, Campaigns)",
        "Content Production",
        "Developer Community (Hackathons, Workshops)",
        "Event Costs (Venue, Food, Swag)",
        "Sponsorships & Partnerships",
        "PR & Media",
        "Merchandise",
    ],
    "Operations": [
        "Office Rent / Workspace",
        "Subscriptions (Non-Engineering SaaS)",
        "Travel (Airfare)",
        "Travel (Ground Transportation)",
        "Travel (Lodging)",
        "Office Supplies",
        "Insurance (GL, E&O, D&O)",
        "Legal (Corporate, Contracts, Immigration)",
        "Accounting & Tax",
        "Banking & Processing Fees",
        "Compliance & Registrations",
    ],
    "Human Resources": [
        "Salaries",
        "Contractor Payments",
        "Bonuses & Incentives",
        "Payroll & HR Platforms",
        "Benefits (Health, Dental, Vision)",
        "Recruiting & Hiring",
        "Training & Education",
        "Team Events & Wellness",
    ],
}


# ---------------------------------------------------------------------------
# Budget classification maps.
#
# Keys are budget subcategories; values are UPPER-CASED keyword substrings.
# These are intentionally EMPTY of company-specific vendors. Populate the
# company-specific lists (e.g. payroll provider, landlord) from
# config/finance.yaml at runtime so no private data lands in source.
# ---------------------------------------------------------------------------

# Mercury counterparty name -> budget subcategory.
MERCURY_BUDGET_MAP: dict[str, list[str]] = {
    "Payroll": [],
    "Benefits & Insurance": [],
    "Rent": [],
    "Utilities": [],
    "Legal": [],
    "Insurance": [],
    "Bank charges": [],
}

# Ramp vendor name -> budget subcategory (for vendors not captured by QB/sk maps).
RAMP_VENDOR_BUDGET_MAP: dict[str, list[str]] = {
    "Rent": [],
    "Legal": [],
    "Insurance": [],
}

# Ramp QuickBooks accounting category -> budget subcategory. Generic QB names.
QB_BUDGET_MAP: dict[str, list[str]] = {
    "Payroll": ["Payroll"],
    "Benefits & Insurance": ["Employee Benefits"],
    "Contractors & Consultants": ["Contractor", "Consultant"],
    "Rent": ["Rent"],
    "Supplies & materials": ["Supplies & Materials"],
    "Equipment": ["Furniture & Fixture"],
    "Utilities": ["Telephone & Internet", "Utilities"],
    "Meals & entertainment": ["Meals and Entertainment"],
    "Airfare": ["Airfare"],
    "Ground transport": ["Ground Transportation"],
    "Lodging": ["Lodging"],
    "Software & web services": [
        "Model & API Usage", "Dev Tools & SaaS", "Non-Engineering SaaS",
        "Observability & Monitoring", "DevOps & CI/CD", "Design Tools & Assets",
        "Software",
    ],
    "Cloud infrastructure": ["Cloud Infrastructure"],
    "Advertising": ["Advertising"],
    "Promotions": ["PR & Media", "Developer Community"],
}

# Ramp sk_category fallback -> budget subcategory. Generic merchant categories.
SK_BUDGET_MAP: dict[str, list[str]] = {
    "Advertising": ["Advertising"],
    "Airfare": ["Airlines"],
    "Ground transport": ["Taxi and Rideshare", "Parking", "Car Rental"],
    "Lodging": ["Lodging", "Hotels"],
    "Meals & entertainment": ["Restaurants", "Alcohol and Bars", "Entertainment"],
    "Software & web services": ["SaaS / Software", "Software"],
    "Supplies & materials": [
        "General Merchandise", "Supermarkets and Grocery Stores", "Office Supplies",
    ],
    "Equipment": ["Electronics"],
    "Training": ["Education"],
    "Benefits & Insurance": ["Medical"],
}

# Generic keyword sets for special-casing inflows / adjustments.
TAX_KEYWORDS = ["FRANCHISE TAX", "IRS", "INTERNAL REVENUE", "STATE TAX"]
INTEREST_KEYWORDS = ["INTEREST CHARGE", "INTEREST PAYMENT", "FINANCE CHARGE"]
OTHER_INCOME_KEYWORDS = ["CASHBACK", "DIVIDEND", "INTEREST EARNED", "REWARD"]

UNCATEGORIZED = "Uncategorized"


def _merge_keyword_config(base: dict[str, list[str]], extra: dict[str, list[str]]) -> dict[str, list[str]]:
    merged = {k: list(v) for k, v in base.items()}
    for subcat, keywords in (extra or {}).items():
        merged.setdefault(subcat, [])
        merged[subcat].extend(kw.upper() for kw in keywords)
    return merged


def load_company_keywords(finance_config: dict[str, Any] | None) -> dict[str, dict[str, list[str]]]:
    """Merge company-specific keyword lists from config into the generic maps.

    ``finance_config`` is the parsed ``config/finance.yaml``. Expected shape::

        budget_keywords:
          mercury:   {Payroll: ["ACME PAYROLL"], ...}
          ramp_vendor: {Rent: ["ACME PROPERTIES"], ...}

    Returns merged copies; the module-level maps are left untouched.
    """
    cfg = (finance_config or {}).get("budget_keywords", {}) or {}
    # learned_categories maps an UPPER-CASED counterparty substring -> subcategory,
    # populated by request_manual_accounting after manual accounting is completed.
    learned_raw = (finance_config or {}).get("learned_categories", {}) or {}
    learned = {str(k).upper(): v for k, v in learned_raw.items()}
    return {
        "mercury": _merge_keyword_config(MERCURY_BUDGET_MAP, cfg.get("mercury", {})),
        "ramp_vendor": _merge_keyword_config(RAMP_VENDOR_BUDGET_MAP, cfg.get("ramp_vendor", {})),
        "qb": QB_BUDGET_MAP,
        "sk": SK_BUDGET_MAP,
        "learned": learned,
    }


def classify_budget(txn: dict[str, Any], keyword_maps: dict[str, dict[str, list[str]]]) -> str:
    """Assign a single expense transaction to a budget subcategory.

    ``txn`` uses the common record shape from ``transactions.py``
    (``name``/``source``/``qb_categories``/``sk_category``).
    """
    name_upper = (txn.get("name") or "").upper()
    source = txn.get("source", "")

    # Learned mappings (from completed manual accounting) take precedence.
    for substring, subcat in (keyword_maps.get("learned") or {}).items():
        if substring and substring in name_upper:
            return subcat

    if "Mercury" in source:
        for subcat, keywords in keyword_maps["mercury"].items():
            if any(kw in name_upper for kw in keywords):
                return subcat

    if "Ramp" in source:
        for subcat, keywords in keyword_maps["ramp_vendor"].items():
            if any(kw in name_upper for kw in keywords):
                return subcat
        for qb_name in txn.get("qb_categories", []) or []:
            qb_lower = qb_name.lower()
            for subcat, qb_keys in keyword_maps["qb"].items():
                if any(k.lower() in qb_lower for k in qb_keys):
                    return subcat
        sk = (txn.get("sk_category") or "").lower()
        if sk:
            for subcat, sk_keys in keyword_maps["sk"].items():
                if any(k.lower() == sk for k in sk_keys):
                    return subcat

    if any(kw in name_upper for kw in TAX_KEYWORDS):
        return "Taxes"

    return UNCATEGORIZED


def is_other_income(txn: dict[str, Any]) -> bool:
    name_upper = (txn.get("name") or "").upper()
    return any(kw in name_upper for kw in OTHER_INCOME_KEYWORDS)


def is_tax(name: str) -> bool:
    return any(kw in (name or "").upper() for kw in TAX_KEYWORDS)


def is_interest(name: str) -> bool:
    return any(kw in (name or "").upper() for kw in INTEREST_KEYWORDS)
