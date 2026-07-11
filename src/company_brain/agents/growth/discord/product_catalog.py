"""Product catalog loader for feature-request dedup and product inference."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from company_brain.config import CONFIG_DIR, resolve_wiki_dir

WIKI_CATALOG_PATH = "product/catalog.yaml"
REPO_CATALOG_PATH = CONFIG_DIR / "product_catalog.yaml"
GENERAL_SLUG = "general"


@dataclass
class ProductSpec:
    slug: str
    name: str
    status: str = "planned"
    features: list[str] | None = None
    in_build: list[str] | None = None

    def __post_init__(self) -> None:
        self.features = list(self.features or [])
        self.in_build = list(self.in_build or [])


@dataclass
class CatalogMatch:
    product_slug: str
    product_name: str
    matched_text: str
    match_kind: str  # shipped | in_build


@dataclass
class ProductCatalog:
    products: list[ProductSpec]

    def by_slug(self, slug: str) -> ProductSpec | None:
        ref = (slug or "").strip().lower()
        for product in self.products:
            if product.slug.lower() == ref:
                return product
        return None

    def display_name(self, slug: str) -> str:
        product = self.by_slug(slug)
        if product:
            return product.name
        if slug.lower() == GENERAL_SLUG:
            return "General"
        return slug.replace("-", " ").title()


def load_product_catalog(wiki_dir: Path | None = None) -> ProductCatalog:
    """Load catalog from wiki MD volume, then repo config fallback."""
    wiki_path = (wiki_dir or resolve_wiki_dir()) / WIKI_CATALOG_PATH
    if wiki_path.is_file():
        data = yaml.safe_load(wiki_path.read_text()) or {}
    elif REPO_CATALOG_PATH.is_file():
        data = yaml.safe_load(REPO_CATALOG_PATH.read_text()) or {}
    else:
        data = {}
    products: list[ProductSpec] = []
    for entry in data.get("products") or []:
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        products.append(
            ProductSpec(
                slug=slug,
                name=str(entry.get("name") or slug),
                status=str(entry.get("status") or "planned"),
                features=[str(f) for f in (entry.get("features") or [])],
                in_build=[str(f) for f in (entry.get("in_build") or [])],
            )
        )
    return ProductCatalog(products=products)


def infer_product_slug(title: str, body: str, catalog: ProductCatalog | None = None) -> str:
    """$0 heuristic product inference; defaults to ``general``."""
    catalog = catalog or load_product_catalog()
    text = f"{title}\n{body}".lower()
    best: tuple[int, str] | None = None
    for product in catalog.products:
        slug_hit = product.slug.replace("-", " ") in text or product.slug in text
        name_hit = product.name.lower() in text
        score = 0
        if slug_hit:
            score += 2
        if name_hit:
            score += 3
        if score and (best is None or score > best[0]):
            best = (score, product.slug)
    if best:
        return best[1]

    try:
        slug = _infer_product_llm(title, body, catalog)
        if slug:
            return slug
    except Exception:
        pass
    return GENERAL_SLUG


def find_catalog_match(text: str, catalog: ProductCatalog | None = None) -> CatalogMatch | None:
    """Return a catalog hit when the request overlaps shipped or in-build work."""
    catalog = catalog or load_product_catalog()
    lowered = text.lower()
    best: CatalogMatch | None = None
    best_score = 0
    for product in catalog.products:
        for item in product.features:
            score = _overlap_score(item, lowered)
            if score > best_score:
                best_score = score
                best = CatalogMatch(
                    product_slug=product.slug,
                    product_name=product.name,
                    matched_text=item,
                    match_kind="shipped",
                )
        for item in product.in_build:
            score = _overlap_score(item, lowered)
            if score > best_score:
                best_score = score
                best = CatalogMatch(
                    product_slug=product.slug,
                    product_name=product.name,
                    matched_text=item,
                    match_kind="in_build",
                )
    return best if best_score >= 2 else None


def _overlap_score(needle: str, haystack: str) -> int:
    ref = (needle or "").strip().lower()
    if not ref or len(ref) < 4:
        return 0
    if ref in haystack:
        return len(ref)
    words = [w for w in ref.split() if len(w) >= 4]
    if not words:
        return 0
    hits = sum(1 for w in words if w in haystack)
    return hits * 5 if hits >= 2 else 0


def _infer_product_llm(title: str, body: str, catalog: ProductCatalog) -> str | None:
    if not catalog.products:
        return None
    from agents import Agent

    from company_brain.llm import openai_agents as oa
    from company_brain.llm.tracking import run_openai_sync

    options = "\n".join(f"- {p.slug}: {p.name}" for p in catalog.products)
    prompt = f"""Pick the single best product slug for this community feature request.
Reply with ONLY the slug, or "{GENERAL_SLUG}" if unclear.

Products:
{options}

Request title: {title}
Request body:
{body[:1500]}
"""
    agent = Agent(
        name="discord_product_infer",
        instructions="You classify product ownership for feature requests. Reply with slug only.",
        model=oa.make_model(agent_name="discord_product_infer"),
    )
    result = run_openai_sync(
        "discord_product_infer",
        agent,
        prompt,
        run_config=oa.make_run_config(agent_name="discord_product_infer"),
    )
    slug = str(result.final_output or "").strip().lower().split()[0]
    if slug == GENERAL_SLUG:
        return GENERAL_SLUG
    if catalog.by_slug(slug):
        return slug
    return None


def draft_technical_reply(
    *,
    title: str,
    body: str,
    match: CatalogMatch,
    permalink: str = "",
) -> str:
    """Draft a suggested Discord reply for duplicate/in-progress features."""
    try:
        from agents import Agent

        from company_brain.llm import openai_agents as oa
        from company_brain.llm.tracking import run_openai_sync

        status = "already available" if match.match_kind == "shipped" else "currently in progress"
        prompt = f"""Draft a short, friendly technical reply for a Discord community member.
The requested capability ({match.matched_text}) is {status} in {match.product_name}.
Do not promise dates. Suggest docs or workarounds when appropriate.
Keep under 120 words. No markdown headers.

Community message:
Title: {title}
Body: {body[:1500]}
"""
        agent = Agent(
            name="discord_draft_reply",
            instructions=(
                "You draft human-review Discord replies for open-source community support."
            ),
            model=oa.make_model(agent_name="discord_draft_reply"),
        )
        result = run_openai_sync(
            "discord_draft_reply",
            agent,
            prompt,
            run_config=oa.make_run_config(agent_name="discord_draft_reply"),
        )
        text = str(result.final_output or "").strip()
        if text:
            return text
    except Exception:
        pass

    if match.match_kind == "shipped":
        return (
            f"Thanks for the suggestion! `{match.matched_text}` is already part of "
            f"{match.product_name}. If something still isn't working, share steps to reproduce."
        )
    return (
        f"Thanks! `{match.matched_text}` is on the roadmap for {match.product_name} "
        f"(in progress). We'll post updates when it ships."
    )
