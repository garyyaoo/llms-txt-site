import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


def _slug_to_title(url: str) -> str:
    """Infer a human-readable title from the last non-empty path segment."""
    path = urlparse(url).path.rstrip("/")
    segment = path.split("/")[-1] if path else ""
    if not segment:
        return urlparse(url).hostname or url
    # Strip common extensions
    if "." in segment:
        segment = segment.rsplit(".", 1)[0]
    return segment.replace("-", " ").replace("_", " ").title()


def extract_metadata(html: str, url: str) -> dict:
    """Extract title and description from an already-fetched HTML string."""
    soup = BeautifulSoup(html, "html.parser")

    og_title = soup.find("meta", property="og:title")
    title_tag = soup.find("title")
    raw_title = (
        (og_title.get("content", "").strip() if og_title else None)
        or (title_tag.get_text().strip() if title_tag else None)
    )
    if raw_title and (" | " in raw_title or " - " in raw_title):
        sep = " | " if " | " in raw_title else " - "
        raw_title = raw_title.split(sep)[0].strip()
    title = raw_title or _slug_to_title(url)

    meta_desc = soup.find("meta", attrs={"name": "description"})
    og_desc = soup.find("meta", property="og:description")
    description = (
        (meta_desc.get("content", "").strip() if meta_desc else None)
        or (og_desc.get("content", "").strip() if og_desc else None)
    )

    return {"url": url, "title": title, "description": description or None, "scraped": True}


def _fetch_metadata(url: str, max_retries: int = 2) -> dict:
    """Fetch a page and extract its metadata. Retries on ReadTimeout up to max_retries times."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            r = requests.get(
                url,
                timeout=5,
                headers={"User-Agent": "Mozilla/5.0 (compatible; llmstxt-bot/1.0)"},
                allow_redirects=True,
            )
            r.raise_for_status()
            return extract_metadata(r.text, url)
        except requests.exceptions.ReadTimeout as e:
            last_exc = e
            if attempt < max_retries:
                continue
        except Exception as e:
            log.info(f"[scraper] error {url}: {e}")
            return {"url": url, "title": _slug_to_title(url), "description": None, "scraped": False}
    log.info(f"[scraper] error {url}: {last_exc}")
    return {"url": url, "title": _slug_to_title(url), "description": None, "scraped": False}


_HOW_TO_PATTERNS = [
    "how to", "getting started", "introduction", "guide", "tutorial",
    "quickstart", "overview", "reference", "setup", "install", "learn",
    "step", "walkthrough", "explained", "what",
]


def content_score(meta: dict) -> int:
    """Score metadata by instructional relevance — how useful is this page for an LLM."""
    title = (meta.get("title") or "").lower()
    desc  = (meta.get("description") or "").lower()
    score = 0
    if any(p in title for p in _HOW_TO_PATTERNS):
        score += 20
    if any(p in desc for p in _HOW_TO_PATTERNS):
        score += 10
    # Boost pages that were actually scraped (real metadata > inferred slug)
    if meta.get("scraped"):
        score += 5
    return score


def scrape_metadata(
    urls: list[str],
    base_url: str | None = None,
    max_scrape: int = 100,
    max_workers: int = 10,
    total_timeout: float = 20.0,
) -> dict[str, dict]:
    """
    Scrape metadata for the top `max_scrape` URLs concurrently.
    Stops after `total_timeout` seconds — any unfinished URLs are inferred from slug.
    If base_url is provided, the homepage is always included in the scrape budget.

    Returns {url: {title, description, scraped}} for all URLs.
    """
    priority = []
    if base_url:
        homepage = base_url.rstrip("/") + "/"
        if homepage in urls:
            priority.append(homepage)
        homepage_no_slash = base_url.rstrip("/")
        if homepage_no_slash in urls and homepage_no_slash not in priority:
            priority.append(homepage_no_slash)

    remaining = [u for u in urls if u not in priority]
    to_scrape = (priority + remaining)[:max_scrape]
    to_infer  = [u for u in urls if u not in set(to_scrape)]

    results: dict[str, dict] = {}

    for url in to_infer:
        results[url] = {"url": url, "title": _slug_to_title(url), "description": None, "scraped": False}

    log.info(f"[scraper] fetching metadata for {len(to_scrape)} URLs ({len(to_infer)} inferred from slug), timeout={total_timeout}s")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_metadata, url): url for url in to_scrape}
        remaining_timeout = max(0.0, total_timeout - (time.time() - t0))
        done, not_done = wait(futures, timeout=remaining_timeout)

        for future in done:
            meta = future.result()
            results[meta["url"]] = meta
            status = "ok" if meta["scraped"] else "err"
            log.info(f"[scraper] {status}  {meta['title'][:50]:<50}  {meta['url']}")

        if not_done:
            log.info(f"[scraper] timed out after {total_timeout}s — {len(not_done)} URLs not fetched:")
            for future in not_done:
                url = futures[future]
                log.info(f"[scraper]   skip  {url}")
                results[url] = {"url": url, "title": _slug_to_title(url), "description": None, "scraped": False}
                future.cancel()

    elapsed = time.time() - t0
    log.info(f"[scraper] done in {elapsed:.1f}s — {len(done)} fetched, {len(not_done) if not_done else 0} timed out")
    return results
