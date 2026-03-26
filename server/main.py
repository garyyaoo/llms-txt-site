#!/usr/bin/env python3
"""
llms.txt generator — full pipeline:
  1. Discover URLs via sitemap (+ nav crawler fallback)
  2. Score and group into named sections
  3. Scrape metadata for top URLs
  4. Generate llms.txt
"""
import sys
import os
from crawler import discover_urls
from grouper import group_urls
from scraper import scrape_metadata
from generator import generate


def run(base_url: str, output_path: str | None = None, max_scrape: int = 100, force_crawl: bool = False) -> str:
    base_url = base_url.rstrip("/")

    # 1. Discover — for crawl path, max_scrape also caps pages visited
    print(f"\n=== Discovering URLs for {base_url} ===")
    result = discover_urls(base_url, force_crawl=force_crawl, max_pages=max_scrape)
    urls = result["page_urls"]
    print(f"Discovered {len(urls)} URLs")

    # 2. Metadata — either from crawler (already fetched during BFS) or scrape top N
    print("\n=== Scraping metadata ===")
    if result["metadata"] is not None:
        print(f"[scraper] using {len(result['metadata'])} cached metadata entries from crawler")
        metadata = result["metadata"]
    else:
        metadata = scrape_metadata(urls, base_url=base_url, max_scrape=max_scrape)

    # 3. Group using combined url + content scores
    print("\n=== Grouping ===")
    groups = group_urls(urls, metadata)
    for section, section_urls in groups.items():
        print(f"  {section}: {len(section_urls)} URLs")

    # 4. Generate
    print("\n=== Generating llms.txt ===")
    output = generate(base_url, groups, metadata)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(output)
        print(f"Saved → {output_path}")
    else:
        print("\n" + "=" * 60)
        print(output)

    return output


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.tryprofound.com"
    out = sys.argv[2] if len(sys.argv) > 2 else None
    run(url, out)
