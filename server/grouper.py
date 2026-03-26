from urllib.parse import urlparse
from crawler import score_url
from scraper import content_score

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



def _combined_score(url: str, metadata: dict) -> int:
    return max(score_url(url), content_score(metadata.get(url, {})))


def bucket_urls(urls: list[str], metadata: dict[str, dict]) -> dict[str, list[str]]:
    """
    Group URLs into sections by first path segment, ordered by section score.
    No filtering applied — all URLs are included. Used by the LLM path.
    """
    buckets: dict[str, list[str]] = {}
    for url in urls:
        section = _section_for(url)
        buckets.setdefault(section, []).append(url)

    def _section_url(bucket: list[str]) -> str:
        parsed = urlparse(bucket[0])
        first_seg = parsed.path.strip("/").split("/")[0]
        return f"{parsed.scheme}://{parsed.netloc}/{first_seg}"

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
        section = _section_for(url)
        buckets.setdefault(section, []).append(url)

    def _section_url(bucket: list[str]) -> str:
        """Reconstruct the canonical depth-1 URL for a section from any URL in its bucket."""
        parsed = urlparse(bucket[0])
        first_seg = parsed.path.strip("/").split("/")[0]
        return f"{parsed.scheme}://{parsed.netloc}/{first_seg}"

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

    primary: dict[str, list[str]] = {}
    optional_urls: list[str] = []

    for rank, (score, section, bucket) in enumerate(scored):
        if rank < free_sections:
            required = threshold
        else:
            n = rank - free_sections + 1
            required = baseline_score * (decay_rate ** n)
        if score < required:
            best = max(bucket, key=lambda u: _combined_score(u, metadata))
            optional_urls.append(best)
            continue
        # Geometric decay within section — URL at rank N must score >= max * decay_rate^N
        sorted_bucket = sorted(bucket, key=lambda u: _combined_score(u, metadata), reverse=True)
        max_in_section = _combined_score(sorted_bucket[0], metadata)
        qualifying = [
            u for n, u in enumerate(sorted_bucket)
            if _combined_score(u, metadata) >= max_in_section * (decay_rate ** n)
        ]
        if qualifying:
            sorted_qualifying = sorted(qualifying, key=lambda u: _combined_score(u, metadata), reverse=True)
            cap = max(1, round(len(bucket) ** 0.5))
            primary[section] = sorted_qualifying[:cap]

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
