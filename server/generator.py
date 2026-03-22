from urllib.parse import urlparse


def _site_name(base_url: str, metadata: dict[str, dict]) -> str:
    """Derive site name from homepage title or domain."""
    homepage = metadata.get(base_url.rstrip("/") + "/") or metadata.get(base_url.rstrip("/"))
    if homepage and homepage.get("title"):
        return homepage["title"]
    host = urlparse(base_url).hostname or base_url
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


def generate(
    base_url: str,
    groups: dict[str, list[str]],
    metadata: dict[str, dict],
) -> str:
    base = base_url.rstrip("/")
    site_name = _site_name(base_url, metadata)
    site_desc = _site_description(base_url, metadata)

    lines: list[str] = []

    lines.append(f"# {site_name}")
    lines.append("")
    if site_desc:
        lines.append(f"> {site_desc}")
        lines.append("")

    # Primary sections (everything except Optional, already sorted by grouper)
    for section, urls in groups.items():
        if section == "Optional":
            continue
        section_lines = []
        for url in urls:
            if url.rstrip("/") == base:
                continue
            meta = metadata.get(url, {})
            section_lines.append(_format_entry(url, meta))
        if section_lines:
            lines.append(f"## {section}")
            lines.extend(section_lines)
            lines.append("")

    # Optional — no descriptions
    optional_urls = [u for u in groups.get("Optional", []) if u.rstrip("/") != base]
    if optional_urls:
        lines.append("## Optional")
        for url in optional_urls:
            meta = metadata.get(url, {})
            lines.append(_format_entry(url, {**meta, "description": None}))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
