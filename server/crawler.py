import time
from collections import deque

import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
from scraper import extract_metadata, _slug_to_title

# Extensions that are never useful page content
_SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".css", ".js", ".json", ".xml", ".pdf", ".zip", ".gz",
    ".mp4", ".mp3", ".woff", ".woff2", ".ttf",
}


def _root_domain(netloc: str) -> str:
    """Return the root domain (last two labels) from a netloc, e.g. 'vancouver.craigslist.org' → 'craigslist.org'."""
    parts = netloc.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else netloc


def _is_same_domain(url: str, base_netloc: str) -> bool:
    parsed = urlparse(url)
    if not parsed.netloc:
        return True  # relative URL
    return _root_domain(parsed.netloc) == _root_domain(base_netloc)


def _is_crawlable(url: str, base_netloc: str) -> bool:
    """Return True if the URL is worth fetching as a page."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https", ""):
        return False
    if not _is_same_domain(url, base_netloc):
        return False
    if parsed.fragment and not parsed.path:
        return False  # pure anchor link
    ext = parsed.path.rsplit(".", 1)[-1].lower()
    if f".{ext}" in _SKIP_EXTENSIONS:
        return False
    return True


_PRIORITY_KEYWORDS = {
    "/about", "/docs", "/documentation", "/guide", "/guides", "/api", "/faq",
    "/help", "/getting-started", "/reference", "/features",
    "/products", "/services", "/overview", "/support", "/engineering",
}# Subdomains that indicate high-value content regardless of path
_HIGH_PRIORITY_SUBDOMAINS = {"docs", "api", "help", "support", "developers", "dev"}


def score_url(url: str) -> int:
    """Score a URL by relevance. Higher = more important for llms.txt."""
    parsed = urlparse(url)
    path = parsed.path.lower().rstrip("/")
    subdomain = parsed.hostname.split(".")[0] if parsed.hostname else ""
    depth = path.count("/") if path else 0
    score = 0

    # Subdomain boost — e.g. docs.example.com scores high even with path "/"
    if subdomain in _HIGH_PRIORITY_SUBDOMAINS:
        score += 50
    else:
        # Strip file extensions from segments before keyword matching
        # e.g. /intro.html → /intro, so it can match /introduction etc.
        def _strip_ext(s: str) -> str:
            return s.rsplit(".", 1)[0] if "." in s else s
        path_segments = {"/" + _strip_ext(s) for s in path.lstrip("/").split("/") if s}
        if any(k in path_segments for k in _PRIORITY_KEYWORDS):
            score += 40

    # URL length penalty — paths beyond 20 chars are penalised heavily
    # Every 2 chars beyond 20 costs 1 point (e.g. 60-char path = -20, 20-char = 0)
    score -= max(0, len(path) - 20) // 2

    # Depth penalty: depth 1=0, 2=5, 3=20, 4=40, 5=60, ...
    if depth >= 3:
        score -= 20 + (depth - 3) * 20
    elif depth == 2:
        score -= 5

    return score


def _extract_nav_links(html: str, page_url: str) -> list[str]:
    """Return absolute URLs found only inside <nav>, <header>, or <footer> elements."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for container in soup.find_all(["nav", "header", "footer"]):
        for a in container.find_all("a", href=True):
            href = a["href"].strip()
            if href:
                links.append(urljoin(page_url, href))
    return links


def crawl_site(
    base_url: str,
    disallowed: list[str] | None = None,
    max_pages: int = 100,
    max_depth: int = 3,
    delay: float = 0.5,
) -> dict:
    """
    BFS crawler that discovers pages by following links found exclusively
    in <nav>, <header>, and <footer> elements.
    Metadata is extracted from each page during crawl — no second pass needed.

    Args:
        base_url:   The starting URL (homepage).
        disallowed: Path prefixes to skip (from robots.txt).
        max_pages:  Stop after collecting this many URLs.
        max_depth:  Do not follow links beyond this hop count from the start.
        delay:      Seconds to wait between requests.

    Returns:
        {"urls": [...sorted by score...], "metadata": {url: {...}}}
    """
    if disallowed is None:
        disallowed = []

    base_url = base_url.rstrip("/")
    base_netloc = urlparse(base_url).netloc

    visited: set[str] = set()
    queued: set[str] = set()
    found: list[str] = []
    metadata: dict[str, dict] = {}

    start = base_url.rstrip("/")
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    queued.add(start)

    while queue and len(found) < max_pages:
        url, depth = queue.popleft()

        url = urlparse(url)._replace(fragment="", query="").geturl().rstrip("/") or url

        if url in visited:
            continue
        visited.add(url)

        path = urlparse(url).path
        if any(path.startswith(d) for d in disallowed):
            print(f"[crawl] skip (disallowed) {url}")
            continue

        t0 = time.time()
        try:
            r = requests.get(
                url,
                timeout=3,
                headers={"User-Agent": "Mozilla/5.0 (compatible; llmstxt-bot/1.0)"},
                allow_redirects=True,
            )
            r.raise_for_status()
            if "text/html" not in r.headers.get("Content-Type", ""):
                continue
        except Exception as e:
            elapsed = time.time() - t0
            print(f"[crawl] error ({elapsed:.1f}s) {url}: {e}")
            metadata[url] = {"url": url, "title": _slug_to_title(url), "description": None, "scraped": False}
            continue

        elapsed = time.time() - t0
        found.append(url)
        meta = extract_metadata(r.text, url)
        metadata[url] = meta
        print(f"[crawl] {len(found):>3}/{max_pages}  depth={depth}  {elapsed:.1f}s  {meta['title'][:50]}")

        if depth < max_depth:
            for link in _extract_nav_links(r.text, url):
                norm = urlparse(link)._replace(fragment="", query="").geturl().rstrip("/")
                if not norm or not _is_crawlable(norm, base_netloc):
                    continue
                if norm not in visited and norm not in queued:
                    queued.add(norm)
                    queue.append((norm, depth + 1))

        if delay and len(found) < max_pages:
            time.sleep(delay)

    print(f"[crawl] done — {len(found)} pages crawled")
    urls = sorted(found, key=score_url, reverse=True)
    return {"urls": urls, "metadata": metadata}


def fetch_robots_txt(base_url: str, user_agent: str = "*") -> dict:
    """Fetch and parse robots.txt — returns disallowed paths and sitemap URLs.
    Only applies Disallow rules for the matching user-agent (default: '*').
    """
    url = urljoin(base_url, "/robots.txt")
    r = requests.get(url, timeout=10)
    r.raise_for_status()

    disallowed = []
    sitemaps = []
    current_agents: list[str] = []
    in_matching_block = False

    for line in r.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            # blank line ends the current user-agent block
            current_agents = []
            in_matching_block = False
            continue
        if line.lower().startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            current_agents.append(agent.lower())
            in_matching_block = user_agent.lower() in current_agents or "*" in current_agents
        elif line.lower().startswith("disallow:"):
            if in_matching_block:
                path = line.split(":", 1)[1].strip()
                if path:
                    disallowed.append(path)
        elif line.lower().startswith("sitemap:"):
            sitemap_url = line.split(":", 1)[1].strip()
            sitemaps.append(sitemap_url)

    return {
        "raw": r.text,
        "disallowed": disallowed,
        "sitemaps": sitemaps,
    }


def fetch_sitemap(sitemap_url: str) -> list[str]:
    """Fetch a sitemap XML and return all page URLs. Handles sitemap index files recursively."""
    r = requests.get(sitemap_url, timeout=10)
    r.raise_for_status()

    root = ET.fromstring(r.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    # Sitemap index — contains references to other sitemaps
    if root.tag.endswith("sitemapindex"):
        urls = []
        for sitemap in root.findall("sm:sitemap", ns):
            loc = sitemap.findtext("sm:loc", namespaces=ns)
            if loc:
                urls.extend(fetch_sitemap(loc.strip()))
        return urls

    # Regular sitemap — contains page URLs
    urls = []
    for url in root.findall("sm:url", ns):
        loc = url.findtext("sm:loc", namespaces=ns)
        if loc:
            urls.append(loc.strip())
    return urls


def discover_urls(base_url: str, force_crawl: bool = False, max_pages: int = 100) -> dict:
    """
    Given a base URL:
    1. Fetch robots.txt — extract disallowed paths and any sitemap references
    2. Fetch sitemap.xml (and any sitemaps found in robots.txt)
    3. Return all discovered URLs, filtered against disallowed paths
    """
    base_url = base_url.rstrip("/")
    result = {
        "robots": None,
        "sitemap_urls": [],
        "page_urls": [],
        "disallowed": [],
        "metadata": None,  # populated only when crawler fallback is used
    }

    # Step 1: robots.txt
    try:
        robots = fetch_robots_txt(base_url)
        result["robots"] = robots
        result["disallowed"] = robots["disallowed"]
        sitemap_urls = robots["sitemaps"]
        print(f"[robots.txt] Found {len(robots['disallowed'])} disallowed paths, {len(sitemap_urls)} sitemap(s)")
    except Exception as e:
        print(f"[robots.txt] Could not fetch: {e}")
        sitemap_urls = []

    # Step 2: always try /sitemap.xml as a fallback
    default_sitemap = urljoin(base_url, "/sitemap.xml")
    if default_sitemap not in sitemap_urls:
        sitemap_urls.insert(0, default_sitemap)

    result["sitemap_urls"] = sitemap_urls

    # Step 3: fetch sitemaps (skipped if force_crawl)
    all_urls = []
    if not force_crawl:
        for sitemap_url in sitemap_urls:
            try:
                urls = fetch_sitemap(sitemap_url)
                print(f"[sitemap] {sitemap_url} → {len(urls)} URLs")
                all_urls.extend(urls)
            except Exception as e:
                print(f"[sitemap] Could not fetch {sitemap_url}: {e}")

    # Step 4: if sitemap yielded nothing (or crawl forced), use nav crawler (metadata extracted during crawl)
    if force_crawl or not all_urls:
        reason = "force_crawl" if force_crawl else "no sitemap URLs found"
        print(f"[discover] {reason} — using nav crawler")
        crawl_result = crawl_site(base_url, disallowed=result["disallowed"], delay=0.0, max_pages=max_pages)
        all_urls = crawl_result["urls"]
        result["metadata"] = crawl_result["metadata"]

    # Known i18n locale prefixes — strip these paths when a canonical version exists
    _LOCALE_RE = __import__("re").compile(
        r"^/([a-z]{2}|[a-z]{2}-[a-z]{2,4})(/|$)", __import__("re").IGNORECASE
    )

    def _canonical_path(path: str) -> str | None:
        """Return the canonical (non-locale) path, or None if not a locale URL."""
        m = _LOCALE_RE.match(path)
        if not m:
            return None
        return path[m.end() - 1:] or "/"  # strip locale prefix, keep leading slash

    # First pass: collect canonical paths that exist
    canonical_paths: set[str] = set()
    for url in all_urls:
        path = urlparse(url).path
        if not _LOCALE_RE.match(path):
            canonical_paths.add(path.rstrip("/") or "/")

    # Deduplicate and filter out disallowed paths and i18n duplicates
    seen = set()
    filtered = []
    skipped_i18n = 0
    for url in all_urls:
        if url in seen:
            continue
        seen.add(url)
        path = urlparse(url).path
        if any(path.startswith(d) for d in result["disallowed"]):
            continue
        # Filter meta/utility files — not useful page content
        if path.rstrip("/").endswith("llms.txt") or path.rstrip("/").endswith("llms-full.txt"):
            continue
        # Skip i18n duplicates when a canonical URL exists
        canonical = _canonical_path(path)
        if canonical is not None and (canonical.rstrip("/") or "/") in canonical_paths:
            skipped_i18n += 1
            continue
        filtered.append(url)

    if skipped_i18n:
        print(f"[discover] filtered {skipped_i18n} i18n duplicate URLs")
    filtered.sort(key=score_url, reverse=True)

    result["page_urls"] = filtered
    print(f"[discover] {len(filtered)} unique allowed URLs found")
    return result


def main():
    import sys
    import json
    import os
    from datetime import datetime

    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output"
    os.makedirs(output_dir, exist_ok=True)

    result = discover_urls(url)

    # Save full URL list as newline-delimited text
    urls_path = os.path.join(output_dir, "urls.txt")
    with open(urls_path, "w") as f:
        f.write("\n".join(result["page_urls"]))
    print(f"\nSaved {len(result['page_urls'])} URLs → {urls_path}")

    # Save full result as JSON
    json_path = os.path.join(output_dir, "crawl_result.json")

    with open(json_path, "w") as f:
        json.dump({
            "crawled_at": datetime.utcnow().isoformat() + "Z",
            "base_url": url,
            "sitemaps": result["sitemap_urls"],
            "disallowed": result["disallowed"],
            "page_count": len(result["page_urls"]),
            "page_urls": result["page_urls"],
        }, f, indent=2)
    print(f"Saved full result    → {json_path}")


if __name__ == "__main__":
    main()
