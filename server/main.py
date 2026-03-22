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


def run(base_url: str, output_path: str | None = None) -> str:
    base_url = base_url.rstrip("/")

    # 1. Discover
    print(f"\n=== Discovering URLs for {base_url} ===")
    result = discover_urls(base_url)
    urls = result["page_urls"]
    print(f"Discovered {len(urls)} URLs")

    # 2. Scrape metadata (URLs already sorted by score)
    print("\n=== Scraping metadata ===")
    metadata = scrape_metadata(urls, base_url=base_url)

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
