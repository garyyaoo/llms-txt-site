import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse


def fetch_robots_txt(base_url: str) -> dict:
    """Fetch and parse robots.txt — returns disallowed paths and sitemap URLs found within it."""
    url = urljoin(base_url, "/robots.txt")
    r = requests.get(url, timeout=10)
    r.raise_for_status()

    disallowed = []
    sitemaps = []

    for line in r.text.splitlines():
        line = line.strip()
        if line.lower().startswith("disallow:"):
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


def discover_urls(base_url: str) -> dict:
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

    # Step 3: fetch all sitemaps and collect page URLs
    all_urls = []
    for sitemap_url in sitemap_urls:
        try:
            urls = fetch_sitemap(sitemap_url)
            print(f"[sitemap] {sitemap_url} → {len(urls)} URLs")
            all_urls.extend(urls)
        except Exception as e:
            print(f"[sitemap] Could not fetch {sitemap_url}: {e}")

    # Deduplicate and filter out disallowed paths
    seen = set()
    filtered = []
    for url in all_urls:
        if url in seen:
            continue
        seen.add(url)
        path = urlparse(url).path
        if any(path.startswith(d) for d in result["disallowed"]):
            continue
        filtered.append(url)

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
