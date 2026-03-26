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
from crawler import discover_urls, score_url
from grouper import group_urls
from scraper import scrape_metadata, content_score
from generator import generate


def _section_insights(groups: dict, metadata: dict) -> dict:
    """Build per-section scoring breakdown for the non-LLM path."""
    sections = []
    for section, urls in groups.items():
        entries = []
        for url in urls:
            meta = metadata.get(url, {})
            u_score = score_url(url)
            c_score = content_score(meta)
            entries.append({
                "url": url,
                "title": (meta.get("title") or url)[:80],
                "url_score": u_score,
                "content_score": c_score,
                "score": max(u_score, c_score),
            })
        sections.append({"name": section, "urls": entries})
    return {"type": "sections", "sections": sections}


def run(base_url: str, output_path: str | None = None, max_scrape: int = 100, force_crawl: bool = False, use_llm: bool = False, max_urls: int | None = None, on_progress=None, on_phase=None, discovery_timeout: float | None = None, max_depth: int = 3) -> dict:
    base_url = base_url.rstrip("/")

    # 1. Discover
    print(f"\n=== Discovering URLs for {base_url} ===")
    result = discover_urls(base_url, force_crawl=force_crawl, max_pages=max_scrape, on_progress=on_progress, discovery_timeout=discovery_timeout, max_depth=max_depth)
    urls = result["page_urls"]
    print(f"Discovered {len(urls)} URLs")

    if on_phase:
        on_phase("generating")

    # 2. Metadata
    print("\n=== Scraping metadata ===")
    if result["metadata"] is not None:
        print(f"[scraper] using {len(result['metadata'])} cached metadata entries from crawler")
        metadata = result["metadata"]
    else:
        metadata = scrape_metadata(urls, base_url=base_url, max_scrape=max_scrape)

    # 3. Group
    print("\n=== Grouping ===")
    group_input = urls[:max_urls] if max_urls else urls
    groups = group_urls(group_input, metadata)
    for section, section_urls in groups.items():
        print(f"  {section}: {len(section_urls)} URLs")

    # 4. Generate
    print("\n=== Generating llms.txt ===")
    why = None
    if use_llm:
        from llm import generate_with_llm
        from grouper import bucket_urls
        llm_urls = urls[:max_urls] if max_urls else urls
        buckets = bucket_urls(llm_urls, metadata)
        llms_txt, why = generate_with_llm(base_url, buckets, metadata)
        if why:
            print(f"\n=== Why ===\n{why}\n")
        insights = {"type": "llm", "why": why or ""}
    else:
        llms_txt = generate(base_url, groups, metadata)
        insights = _section_insights(groups, metadata)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(llms_txt)
        print(f"Saved → {output_path}")
    else:
        print("\n" + "=" * 60)
        print(llms_txt)

    return {"llms_txt": llms_txt, "why": why, "insights": insights}


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.tryprofound.com"
    out = sys.argv[2] if len(sys.argv) > 2 else None
    run(url, out)
