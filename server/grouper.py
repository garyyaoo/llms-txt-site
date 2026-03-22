from urllib.parse import urlparse
from crawler import score_url
from scraper import content_score

# UGC sections — only the depth-1 landing page is included, not individual posts/articles
UGC_SECTIONS = {"Blog", "Resources", "Research", "Changelog", "News", "Customers"}

SUBDOMAIN_SECTION_MAP = {
    "docs":       "Documentation",
    "api":        "API Reference",
    "help":       "Support",
    "support":    "Support",
    "developers": "Documentation",
    "dev":        "Documentation",
}

# First N sections appear with the base threshold; beyond that, strong relevance required
SECTION_THRESHOLD = 20
SECTION_STRONG_THRESHOLD = 40  # requires a keyword/subdomain boost
FREE_SECTIONS = 3               # number of sections that only need to clear SECTION_THRESHOLD


def _section_for(url: str) -> str:
    """Infer section name from subdomain or first path segment."""
    parsed = urlparse(url)
    subdomain = parsed.hostname.split(".")[0] if parsed.hostname else ""
    if subdomain in SUBDOMAIN_SECTION_MAP:
        return SUBDOMAIN_SECTION_MAP[subdomain]
    path = parsed.path.strip("/")
    first_segment = path.split("/")[0] if path else ""
    # Strip file extensions (e.g. intro.html → intro)
    if "." in first_segment:
        first_segment = first_segment.rsplit(".", 1)[0]
    return first_segment.replace("-", " ").title() if first_segment else "Overview"


def _depth(url: str) -> int:
    return urlparse(url).path.rstrip("/").count("/")


def _combined_score(url: str, metadata: dict) -> int:
    return score_url(url) + content_score(metadata.get(url, {}))


def group_urls(
    urls: list[str],
    metadata: dict[str, dict],
    threshold: int = SECTION_THRESHOLD,
    strong_threshold: int = SECTION_STRONG_THRESHOLD,
    free_sections: int = FREE_SECTIONS,
) -> dict[str, list[str]]:
    """
    Group URLs into sections by first path segment.
    Each section keeps only its highest-scoring URL (url score + content score).

    The first `free_sections` sections (by score) only need to clear `threshold`.
    Additional sections must clear `strong_threshold` (requires keyword/subdomain boost).
    Sections that don't qualify are collected into Optional.
    """
    buckets: dict[str, list[str]] = {}
    for url in urls:
        section = _section_for(url)
        buckets.setdefault(section, []).append(url)

    # Score each section by its best URL, then sort descending
    scored: list[tuple[int, str, list[str]]] = []
    for section, bucket in buckets.items():
        best = max(bucket, key=lambda u: _combined_score(u, metadata))
        scored.append((_combined_score(best, metadata), section, bucket))
    scored.sort(reverse=True)

    primary: dict[str, list[str]] = {}
    optional_urls: list[str] = []

    for rank, (score, section, bucket) in enumerate(scored):
        required = threshold if rank < free_sections else strong_threshold
        if score < required:
            # Use best depth-1 URL as Optional representative
            best = max(bucket, key=lambda u: _combined_score(u, metadata))
            optional_urls.append(best)
            continue
        # UGC sections: only the depth-1 landing page (no individual posts/articles)
        if section in UGC_SECTIONS:
            depth1 = [u for u in bucket if _depth(u) <= 1]
            qualifying = [max(depth1, key=lambda u: _combined_score(u, metadata))] if depth1 else []
        else:
            # Structural sections: include all URLs that individually pass the threshold
            qualifying = [u for u in bucket if _combined_score(u, metadata) >= threshold]
        if qualifying:
            primary[section] = sorted(qualifying, key=lambda u: _combined_score(u, metadata), reverse=True)

    primary = dict(sorted(
        primary.items(),
        key=lambda kv: _combined_score(kv[1][0], metadata),
        reverse=True,
    ))

    groups: dict[str, list[str]] = dict(primary)

    if optional_urls:
        optional_urls.sort(key=lambda u: _combined_score(u, metadata), reverse=True)
        groups["Optional"] = optional_urls

    return groups
