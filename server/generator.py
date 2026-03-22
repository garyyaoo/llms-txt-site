from urllib.parse import urlparse
from crawler import score_url
from scraper import content_score


def _combined_score(url: str, meta: dict) -> int:
    return score_url(url) + content_score(meta)


def _site_name(base_url: str, metadata: dict[str, dict]) -> str:
    """Derive site name from homepage title or domain."""
    homepage = metadata.get(base_url.rstrip("/") + "/") or metadata.get(base_url.rstrip("/"))
    if homepage and homepage.get("title"):
        return homepage["title"]
    host = urlparse(base_url).hostname or base_url
    # Strip www. and return title-cased domain without TLD
    parts = host.lstrip("www.").split(".")
    return parts[0].title()


def _site_description(base_url: str, metadata: dict[str, dict]) -> str | None:
    """Get site description from homepage metadata."""
    homepage = metadata.get(base_url.rstrip("/") + "/") or metadata.get(base_url.rstrip("/"))
    if homepage:
        return homepage.get("description")
    return None


def _format_entry(url: str, meta: dict) -> str:
    title = meta.get("title") or url
    desc  = meta.get("description")
    if desc:
        return f"- [{title}]({url}): {desc}"
    return f"- [{title}]({url})"


def _is_optional(section: str, urls: list[str]) -> bool:
    """A section is optional if its highest-scored URL has no priority keyword/subdomain boost.
    Threshold of 15 ensures slug-richness alone (max +10 for 4-word slugs) doesn't qualify as primary."""
    return score_url(urls[0]) < 15


def generate(
    base_url: str,
    groups: dict[str, list[str]],
    metadata: dict[str, dict],
) -> str:
    base = base_url.rstrip("/")
    site_name = _site_name(base_url, metadata)
    site_desc = _site_description(base_url, metadata)

    # Partition sections into primary and optional.
    # Sections named "Optional" are always optional regardless of score.
    primary  = {s: u for s, u in groups.items() if s != "Optional" and not _is_optional(s, u)}
    optional = {s: u for s, u in groups.items() if s == "Optional" or _is_optional(s, u)}

    # Sort primary sections by best combined score desc, then size desc
    primary = dict(sorted(
        primary.items(),
        key=lambda kv: (_combined_score(kv[1][0], metadata.get(kv[1][0], {})), len(kv[1])),
        reverse=True,
    ))

    lines: list[str] = []

    # Header
    lines.append(f"# {site_name}")
    lines.append("")
    if site_desc:
        lines.append(f"> {site_desc}")
        lines.append("")

    # Primary sections
    for section, urls in primary.items():
        lines.append(f"## {section}")
        for url in urls:
            # Skip homepage — already represented by the H1/blockquote
            if url.rstrip("/") == base:
                continue
            meta = metadata.get(url, {})
            lines.append(_format_entry(url, meta))
        lines.append("")

    # Optional section — flatten all low-priority sections.
    # Prefer depth-1 links; depth-2+ only if score >= 40 (has keyword/subdomain boost after penalty).
    from urllib.parse import urlparse as _urlparse
    def _opt_depth(url): return _urlparse(url).path.rstrip("/").count("/")
    optional_urls = [
        u for urls in optional.values() for u in urls
        if _opt_depth(u) <= 1 or score_url(u) >= 40
    ]
    # Remove homepage from optional too
    optional_urls = [u for u in optional_urls if u.rstrip("/") != base]

    if optional_urls:
        lines.append("## Optional")
        for url in optional_urls:
            meta = metadata.get(url, {})
            lines.append(_format_entry(url, {**meta, "description": None}))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
