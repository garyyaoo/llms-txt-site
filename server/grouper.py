import math
from urllib.parse import urlparse
from crawler import score_url

SUBDOMAIN_SECTION_MAP = {
    "docs":       "Documentation",
    "api":        "API Reference",
    "help":       "Support",
    "support":    "Support",
    "developers": "Documentation",
    "dev":        "Documentation",
}

# UGC sections — articles, posts, changelogs. All URLs routed to Optional.
UGC_SECTIONS = {"Blog", "Resources", "Research", "Changelog", "News", "Customers"}


def _dynamic_cap(count: int) -> int:
    """Scale cap logarithmically with section size.
    Small sections show all entries; large sections are trimmed.
      1-3  → all
      5    → 3
      10   → 5
      50   → 9
    """
    if count <= 3:
        return count
    return max(3, round(math.sqrt(count) * 1.5))


def _depth(url: str) -> int:
    return urlparse(url).path.rstrip("/").count("/")


def _section_for(url: str) -> str:
    """Infer section name from subdomain or first path segment."""
    parsed = urlparse(url)
    subdomain = parsed.hostname.split(".")[0] if parsed.hostname else ""
    if subdomain in SUBDOMAIN_SECTION_MAP:
        return SUBDOMAIN_SECTION_MAP[subdomain]
    path = parsed.path.strip("/")
    first_segment = path.split("/")[0] if path else ""
    return first_segment.replace("-", " ").title() if first_segment else "Overview"


def group_urls(
    urls: list[str],
    max_total: int | None = None,
) -> dict[str, list[str]]:
    """
    Group a scored (pre-sorted) URL list into named sections inferred from
    the URL structure.

    Section caps are determined dynamically from section size.
    Within each section, entries are sorted by depth (shallowest first)
    then by score (highest first) before the cap is applied.
    When trimming to max_total, the lowest-scored URL across all sections
    is dropped first.
    """
    # Bucket all URLs into sections without applying caps yet.
    # Track UGC separately — their depth-2+ entries are stripped before merging into Optional.
    raw: dict[str, list[str]] = {}
    ugc_urls: list[str] = []  # URLs from UGC sections (blog posts, articles, etc.)

    for url in urls:
        section = _section_for(url)
        if section in UGC_SECTIONS:
            ugc_urls.append(url)
        else:
            raw.setdefault(section, []).append(url)

    # Apply dynamic cap per section, prioritising lowest depth then highest score.
    # Depth-2+ entries must score >= 30 to be included (length penalty filters long URLs).
    _DEEP_SCORE_FLOOR = 30
    groups: dict[str, list[str]] = {}
    for section, bucket in raw.items():
        eligible = [u for u in bucket if _depth(u) <= 1 or score_url(u) >= _DEEP_SCORE_FLOOR]
        cap = _dynamic_cap(len(eligible))
        sorted_bucket = sorted(eligible, key=lambda u: (_depth(u), -score_url(u)))
        groups[section] = sorted_bucket[:cap]

    # Build Optional bucket:
    # - UGC: depth-1 only (section landing pages like /blog, /resources)
    # - Non-UGC that scored too low for primary: depth-1 freely, depth-2+ only if highly scored
    optional_bucket: list[str] = []
    for url in ugc_urls:
        if _depth(url) <= 1:
            optional_bucket.append(url)
    # Non-primary non-UGC sections will be handled by generator after scoring,
    # so we only merge UGC depth-1 here into a synthetic Optional group.
    if optional_bucket:
        cap = _dynamic_cap(len(optional_bucket))
        sorted_optional = sorted(optional_bucket, key=lambda u: (_depth(u), -score_url(u)))
        groups["Optional"] = sorted_optional[:cap]

    if max_total is not None:
        total = sum(len(v) for v in groups.values())
        while total > max_total:
            worst_section = min(
                groups,
                key=lambda s: score_url(groups[s][-1]),
            )
            groups[worst_section].pop()
            if not groups[worst_section]:
                del groups[worst_section]
            total -= 1

    return {k: v for k, v in groups.items() if v}
