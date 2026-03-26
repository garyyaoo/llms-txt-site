import re
from urllib.parse import urlparse
from crawler import score_url
from scraper import content_score

_LOCALE_RE = re.compile(r"^([a-z]{2}|[a-z]{2}-[a-z]{2,4})$", re.IGNORECASE)

SUBDOMAIN_SECTION_MAP = {
    "docs":       "Documentation",
    "api":        "API Reference",
    "help":       "Support",
    "support":    "Support",
    "developers": "Documentation",
    "dev":        "Documentation",
}

# First N sections appear with the base threshold; beyond that, geometric decay applies
SECTION_THRESHOLD = 20
FREE_SECTIONS = 3               # number of sections that only need to clear SECTION_THRESHOLD
DECAY_RATE = 0.9                # each extra section requires score >= highest * DECAY_RATE^N
# Utility/legal sections that are never useful for LLMs
_BLOCKED_SECTIONS = {
    "legal", "privacy", "terms", "cookies", "cookie policy",
    "accessibility", "sitemap", "404", "search",
}


def _section_for(url: str) -> str:
    """Infer section name from subdomain or first non-locale path segment."""
    parsed = urlparse(url)
    subdomain = parsed.hostname.split(".")[0] if parsed.hostname else ""
    if subdomain in SUBDOMAIN_SECTION_MAP:
        return SUBDOMAIN_SECTION_MAP[subdomain]
    segments = [s for s in parsed.path.strip("/").split("/") if s]
    # Skip locale prefixes like "en", "en-us", "fr", etc.
    while segments and _LOCALE_RE.match(segments[0]):
        segments = segments[1:]
    segment = segments[0] if segments else ""
    if "." in segment:
        segment = segment.rsplit(".", 1)[0]
    return segment.replace("-", " ").title() if segment else "Overview"


def _section_url(bucket: list[str]) -> str:
    """Reconstruct the canonical depth-1 URL for a section from any URL in its bucket."""
    parsed = urlparse(bucket[0])
    segments = [s for s in parsed.path.strip("/").split("/") if s]
    while segments and _LOCALE_RE.match(segments[0]):
        segments = segments[1:]
    first_seg = segments[0] if segments else ""
    return f"{parsed.scheme}://{parsed.netloc}/{first_seg}"


def _combined_score(url: str, metadata: dict) -> int:
    return max(score_url(url), content_score(metadata.get(url, {})))


def bucket_urls(urls: list[str], metadata: dict[str, dict]) -> dict[str, list[str]]:
    """
    Group URLs into sections by first path segment, ordered by section score.
    No filtering applied — all URLs are included. Used by the LLM path.
    """
    buckets: dict[str, list[str]] = {}
    for url in urls:
        buckets.setdefault(_section_for(url), []).append(url)

    scored = []
    for section, bucket in buckets.items():
        best_content = max(bucket, key=lambda u: _combined_score(u, metadata))
        section_score = max(
            score_url(_section_url(bucket)),
            content_score(metadata.get(best_content, {})),
        )
        scored.append((section_score, section, bucket))
    scored.sort(reverse=True)

    return {section: bucket for _, section, bucket in scored}


def group_urls(
    urls: list[str],
    metadata: dict[str, dict],
    threshold: int = SECTION_THRESHOLD,
    free_sections: int = FREE_SECTIONS,
    decay_rate: float = DECAY_RATE,
) -> dict[str, list[str]]:
    """
    Group URLs into sections by first path segment.
    Each section keeps only its highest-scoring URL (url score + content score).

    The first `free_sections` sections only need to clear `threshold`.
    Each additional section N (1-indexed) must score >= highest_score * decay_rate^N,
    creating a geometric decay: if highest=100, section 4 needs >90, section 5 >81, etc.
    Sections that don't qualify are collected into Optional.
    """
    buckets: dict[str, list[str]] = {}
    for url in urls:
        buckets.setdefault(_section_for(url), []).append(url)

    scored: list[tuple[int, str, list[str]]] = []
    for section, bucket in buckets.items():
        best_content = max(bucket, key=lambda u: _combined_score(u, metadata))
        section_score = max(
            score_url(_section_url(bucket)),
            content_score(metadata.get(best_content, {})),
        )
        scored.append((section_score, section, bucket))
    scored.sort(reverse=True)

    free = scored[:free_sections]
    baseline_score = sum(s for s, _, _ in free) / len(free) if free else 0
    floor = baseline_score / 2

    primary: dict[str, list[str]] = {}
    optional_urls: list[str] = []

    for rank, (score, section, bucket) in enumerate(scored):
        if section.lower() in _BLOCKED_SECTIONS or score < floor:
            continue
        if rank < free_sections:
            required = threshold
        else:
            n = rank - free_sections + 1
            required = baseline_score * (decay_rate ** n)
        if score < required:
            best = max(bucket, key=lambda u: _combined_score(u, metadata))
            optional_urls.append(best)
            continue

        # Pre-compute scores to avoid redundant calls during sort and filter
        url_scores = [(u, _combined_score(u, metadata)) for u in bucket]
        url_scores.sort(key=lambda x: x[1], reverse=True)
        max_score = url_scores[0][1]
        qualifying = [
            u for n, (u, s) in enumerate(url_scores)
            if s >= max_score * (decay_rate ** n)
        ]
        if qualifying:
            cap = max(1, round(len(bucket) ** 0.5))
            primary[section] = qualifying[:cap]

    primary = dict(sorted(
        primary.items(),
        key=lambda kv: _combined_score(kv[1][0], metadata),
        reverse=True,
    ))

    groups: dict[str, list[str]] = dict(primary)

    if optional_urls:
        optional_urls.sort(key=lambda u: _combined_score(u, metadata), reverse=True)
        cap = max(1, round(len(scored) ** 0.5))
        groups["Optional"] = optional_urls[:cap]

    return groups
