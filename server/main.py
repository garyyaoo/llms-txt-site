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
import logging
from crawler import discover_urls, score_url
from grouper import group_urls, bucket_urls
from scraper import scrape_metadata, content_score
from generator import generate
from llm import generate_with_llm

log = logging.getLogger(__name__)


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
        top_score = max((e["score"] for e in entries), default=0)
        sections.append({"name": section, "score": top_score, "urls": entries})
    sections.sort(key=lambda s: s["score"], reverse=True)
    return {"type": "sections", "sections": sections}


def run(base_url: str, output_path: str | None = None, max_scrape: int = 100, force_crawl: bool = False, use_llm: bool = False, max_urls: int | None = None, on_progress=None, on_phase=None, discovery_timeout: float | None = None, max_depth: int = 3) -> dict:
    base_url = base_url.rstrip("/")

    # 1. Discover
    log.info("Discovering URLs for %s", base_url)
    result = discover_urls(base_url, force_crawl=force_crawl, max_pages=max_scrape, on_progress=on_progress, discovery_timeout=discovery_timeout, max_depth=max_depth)
    urls = result["page_urls"]
    log.info("Discovered %d URLs", len(urls))

    if on_phase:
        on_phase("generating")

    # 2. Metadata
    log.info("Scraping metadata")
    if result["metadata"] is not None:
        log.info("[scraper] using %d cached metadata entries from crawler", len(result["metadata"]))
        metadata = result["metadata"]
    else:
        metadata = scrape_metadata(urls, base_url=base_url, max_scrape=max_scrape)

    # 3. Group
    log.info("Grouping")
    group_input = urls[:max_urls] if max_urls else urls
    groups = group_urls(group_input, metadata)
    for section, section_urls in groups.items():
        log.info("  %s: %d URLs", section, len(section_urls))

    # 4. Generate
    log.info("Generating llms.txt")
    why = None
    if use_llm:
        llm_urls = urls[:max_urls] if max_urls else urls
        buckets = bucket_urls(llm_urls, metadata)
        llms_txt, why = generate_with_llm(base_url, buckets, metadata)
        if why:
            log.info("Why:\n%s", why)
        insights = {"type": "llm", "why": why or ""}
    else:
        llms_txt = generate(base_url, groups, metadata)
        all_buckets = bucket_urls(group_input, metadata)
        insights = _section_insights(all_buckets, metadata)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(llms_txt)
        log.info("Saved → %s", output_path)
    else:
        log.info(llms_txt)

    return {"llms_txt": llms_txt, "why": why, "insights": insights}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.tryprofound.com"
    out = sys.argv[2] if len(sys.argv) > 2 else None
    run(url, out)
