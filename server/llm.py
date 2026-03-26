"""
LLM-based llms.txt generator using Gemini.
Passes grouped URL sections to the model and returns generated llms.txt content.
"""
import logging
import os
import time
from urllib.parse import urlparse

from google import genai

log = logging.getLogger(__name__)


def _get_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set")
    return genai.Client(api_key=api_key)


def _strip_prefix(url: str, base_url: str) -> str:
    """Strip scheme + netloc prefix, return just the path (or full URL if different domain)."""
    base = urlparse(base_url)
    parsed = urlparse(url)
    if parsed.netloc == base.netloc or parsed.netloc == "":
        return parsed.path or "/"
    # Different subdomain — keep subdomain only, strip scheme
    return f"{parsed.netloc}{parsed.path}"


def _build_prompt(base_url: str, groups: dict, metadata: dict) -> str:
    base = base_url.rstrip("/")
    parsed = urlparse(base)
    site_domain = parsed.netloc

    # Homepage description
    homepage = metadata.get(base + "/") or metadata.get(base) or {}
    site_desc = homepage.get("description") or homepage.get("title") or site_domain

    lines = [
        f"Generate an llms.txt file for {site_domain}.",
        f"Site description: {site_desc}",
        "",
        "Below are all discovered URLs grouped by section. Select the most relevant sections and URLs.",
        "Rules:",
        "- Output: # Site Name, > one-line description, then ## Section Name sections",
        "- Each primary section: bullet links as - [Title](url): one-sentence description",
        "- Last section: ## Optional — links with NO descriptions: - [Title](url)",
        "  Always use the provided title for link text. Never use raw URLs as link text.",
        "- Be selective: prefer structural/product pages over blog posts, legal, and marketing pages.",
        "- Be concise: rewrite descriptions to one sentence focused on what an LLM would find useful.",
        "",
        "After the llms.txt output, add a separator line containing only '---' followed by a",
        "brief '## Why' section explaining concisely why each primary section was included",
        "and why others were demoted to Optional.",
        "",
        f"All URL paths below are relative to {site_domain}. Reconstruct full URLs in output.",
        "",
        "URLs by section:",
    ]

    for section, section_urls in groups.items():
        lines.append(f"\n## {section}")
        for url in section_urls:
            path = _strip_prefix(url, base)
            meta = metadata.get(url, {})
            title = meta.get("title") or path
            lines.append(f"- {path}: {title}")

    return "\n".join(lines)


def generate_with_llm(base_url: str, groups: dict, metadata: dict, model: str = "gemini-3.1-flash-lite-preview", max_retries: int = 3) -> tuple[str, str]:
    """
    Generate llms.txt via Gemini, using grouped sections as structured input.
    Returns (llms_txt, why) as a tuple.
    """
    client = _get_client()
    prompt = _build_prompt(base_url, groups, metadata)

    token_estimate = len(prompt) // 4
    log.info(f"[llm] prompt ~{token_estimate} tokens, {len(groups)} sections")
    log.info(f"\n--- PROMPT ---\n{prompt}\n--- END PROMPT ---\n")

    last_exc = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            text = response.text
            break
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt
            log.info(f"[llm] attempt {attempt + 1} failed: {e} — retrying in {wait}s")
            time.sleep(wait)
    else:
        raise RuntimeError(f"Gemini failed after {max_retries} attempts: {last_exc}")

    # Split on the separator line between llms.txt and Why section
    if "\n---\n" in text:
        llms_txt, why = text.split("\n---\n", 1)
    else:
        # Fallback: split on ## Why if no separator present
        if "## Why" in text:
            llms_txt, why = text.split("## Why", 1)
            why = "## Why" + why
        else:
            llms_txt, why = text, ""

    return llms_txt.strip(), why.strip()
