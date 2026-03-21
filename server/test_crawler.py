import pytest
from unittest.mock import patch, MagicMock
from crawler import fetch_robots_txt, fetch_sitemap, discover_urls


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_response(text: str, status: int = 200):
    mock = MagicMock()
    mock.text = text
    mock.status_code = status
    mock.raise_for_status = MagicMock()
    if status >= 400:
        mock.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return mock


ROBOTS_BASIC = """\
User-agent: *
Disallow: /admin/
Disallow: /private/
Sitemap: https://example.com/sitemap.xml
"""

ROBOTS_NO_SITEMAP = """\
User-agent: *
Disallow: /secret/
"""

ROBOTS_EMPTY_DISALLOW = """\
User-agent: *
Disallow:
Sitemap: https://example.com/sitemap.xml
"""

SITEMAP_BASIC = """\
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://example.com/docs</loc></url>
</urlset>
"""

SITEMAP_INDEX = """\
<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-blog.xml</loc></sitemap>
</sitemapindex>
"""

SITEMAP_PAGES = """\
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page-1</loc></url>
  <url><loc>https://example.com/page-2</loc></url>
</urlset>
"""

SITEMAP_BLOG = """\
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/blog/post-1</loc></url>
</urlset>
"""


# ── fetch_robots_txt ──────────────────────────────────────────────────────────

class TestFetchRobotsTxt:
    @patch("crawler.requests.get")
    def test_parses_disallowed_and_sitemaps(self, mock_get):
        mock_get.return_value = make_response(ROBOTS_BASIC)
        result = fetch_robots_txt("https://example.com")

        assert result["disallowed"] == ["/admin/", "/private/"]
        assert result["sitemaps"] == ["https://example.com/sitemap.xml"]

    @patch("crawler.requests.get")
    def test_fetches_correct_url(self, mock_get):
        mock_get.return_value = make_response(ROBOTS_BASIC)
        fetch_robots_txt("https://example.com")

        mock_get.assert_called_once_with("https://example.com/robots.txt", timeout=10)

    @patch("crawler.requests.get")
    def test_trailing_slash_stripped_from_base(self, mock_get):
        mock_get.return_value = make_response(ROBOTS_BASIC)
        fetch_robots_txt("https://example.com/")

        mock_get.assert_called_once_with("https://example.com/robots.txt", timeout=10)

    @patch("crawler.requests.get")
    def test_no_sitemap_returns_empty_list(self, mock_get):
        mock_get.return_value = make_response(ROBOTS_NO_SITEMAP)
        result = fetch_robots_txt("https://example.com")

        assert result["sitemaps"] == []
        assert result["disallowed"] == ["/secret/"]

    @patch("crawler.requests.get")
    def test_empty_disallow_line_ignored(self, mock_get):
        mock_get.return_value = make_response(ROBOTS_EMPTY_DISALLOW)
        result = fetch_robots_txt("https://example.com")

        assert result["disallowed"] == []

    @patch("crawler.requests.get")
    def test_raw_text_returned(self, mock_get):
        mock_get.return_value = make_response(ROBOTS_BASIC)
        result = fetch_robots_txt("https://example.com")

        assert result["raw"] == ROBOTS_BASIC

    @patch("crawler.requests.get")
    def test_http_error_raises(self, mock_get):
        mock_get.return_value = make_response("Not Found", status=404)
        with pytest.raises(Exception):
            fetch_robots_txt("https://example.com")

    @patch("crawler.requests.get")
    def test_case_insensitive_directives(self, mock_get):
        robots = "DISALLOW: /upper/\nSITEMAP: https://example.com/sitemap.xml\n"
        mock_get.return_value = make_response(robots)
        result = fetch_robots_txt("https://example.com")

        assert "/upper/" in result["disallowed"]
        assert "https://example.com/sitemap.xml" in result["sitemaps"]


# ── fetch_sitemap ─────────────────────────────────────────────────────────────

class TestFetchSitemap:
    @patch("crawler.requests.get")
    def test_basic_sitemap_returns_urls(self, mock_get):
        mock_get.return_value = make_response(SITEMAP_BASIC)
        urls = fetch_sitemap("https://example.com/sitemap.xml")

        assert urls == [
            "https://example.com/",
            "https://example.com/about",
            "https://example.com/docs",
        ]

    @patch("crawler.requests.get")
    def test_sitemap_index_recursively_fetched(self, mock_get):
        def side_effect(url, **kwargs):
            if "sitemap-pages" in url:
                return make_response(SITEMAP_PAGES)
            if "sitemap-blog" in url:
                return make_response(SITEMAP_BLOG)
            return make_response(SITEMAP_INDEX)

        mock_get.side_effect = side_effect
        urls = fetch_sitemap("https://example.com/sitemap.xml")

        assert "https://example.com/page-1" in urls
        assert "https://example.com/page-2" in urls
        assert "https://example.com/blog/post-1" in urls
        assert len(urls) == 3

    @patch("crawler.requests.get")
    def test_empty_sitemap_returns_empty_list(self, mock_get):
        empty = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
        mock_get.return_value = make_response(empty)
        urls = fetch_sitemap("https://example.com/sitemap.xml")

        assert urls == []

    @patch("crawler.requests.get")
    def test_http_error_raises(self, mock_get):
        mock_get.return_value = make_response("", status=404)
        with pytest.raises(Exception):
            fetch_sitemap("https://example.com/sitemap.xml")

    @patch("crawler.requests.get")
    def test_urls_are_stripped(self, mock_get):
        sitemap = """\
<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>  https://example.com/padded  </loc></url>
</urlset>"""
        mock_get.return_value = make_response(sitemap)
        urls = fetch_sitemap("https://example.com/sitemap.xml")

        assert urls == ["https://example.com/padded"]


# ── discover_urls ─────────────────────────────────────────────────────────────

class TestDiscoverUrls:
    @patch("crawler.fetch_sitemap")
    @patch("crawler.fetch_robots_txt")
    def test_basic_discovery(self, mock_robots, mock_sitemap):
        mock_robots.return_value = {
            "disallowed": [],
            "sitemaps": ["https://example.com/sitemap.xml"],
            "raw": "",
        }
        mock_sitemap.return_value = ["https://example.com/", "https://example.com/about"]

        result = discover_urls("https://example.com")

        assert "https://example.com/" in result["page_urls"]
        assert "https://example.com/about" in result["page_urls"]

    @patch("crawler.fetch_sitemap")
    @patch("crawler.fetch_robots_txt")
    def test_disallowed_paths_filtered(self, mock_robots, mock_sitemap):
        mock_robots.return_value = {
            "disallowed": ["/admin/"],
            "sitemaps": [],
            "raw": "",
        }
        mock_sitemap.return_value = [
            "https://example.com/docs",
            "https://example.com/admin/secret",
        ]

        result = discover_urls("https://example.com")

        assert "https://example.com/docs" in result["page_urls"]
        assert "https://example.com/admin/secret" not in result["page_urls"]

    @patch("crawler.fetch_sitemap")
    @patch("crawler.fetch_robots_txt")
    def test_deduplication(self, mock_robots, mock_sitemap):
        mock_robots.return_value = {
            "disallowed": [],
            "sitemaps": ["https://example.com/sitemap.xml"],
            "raw": "",
        }
        # sitemap.xml appears in both robots sitemaps and default fallback,
        # so fetch_sitemap may be called twice with same URL returning duplicates
        mock_sitemap.return_value = [
            "https://example.com/page",
            "https://example.com/page",
        ]

        result = discover_urls("https://example.com")

        assert result["page_urls"].count("https://example.com/page") == 1

    @patch("crawler.fetch_sitemap")
    @patch("crawler.fetch_robots_txt")
    def test_robots_failure_falls_back_to_default_sitemap(self, mock_robots, mock_sitemap):
        mock_robots.side_effect = Exception("connection error")
        mock_sitemap.return_value = ["https://example.com/page"]

        result = discover_urls("https://example.com")

        assert result["robots"] is None
        mock_sitemap.assert_called_with("https://example.com/sitemap.xml")
        assert "https://example.com/page" in result["page_urls"]

    @patch("crawler.fetch_sitemap")
    @patch("crawler.fetch_robots_txt")
    def test_sitemap_failure_skipped_gracefully(self, mock_robots, mock_sitemap):
        mock_robots.return_value = {
            "disallowed": [],
            "sitemaps": [],
            "raw": "",
        }
        mock_sitemap.side_effect = Exception("not found")

        result = discover_urls("https://example.com")

        assert result["page_urls"] == []

    @patch("crawler.fetch_sitemap")
    @patch("crawler.fetch_robots_txt")
    def test_default_sitemap_added_when_not_in_robots(self, mock_robots, mock_sitemap):
        mock_robots.return_value = {
            "disallowed": [],
            "sitemaps": [],
            "raw": "",
        }
        mock_sitemap.return_value = []

        discover_urls("https://example.com")

        called_urls = [call.args[0] for call in mock_sitemap.call_args_list]
        assert "https://example.com/sitemap.xml" in called_urls

    @patch("crawler.fetch_sitemap")
    @patch("crawler.fetch_robots_txt")
    def test_default_sitemap_not_duplicated_if_already_in_robots(self, mock_robots, mock_sitemap):
        mock_robots.return_value = {
            "disallowed": [],
            "sitemaps": ["https://example.com/sitemap.xml"],
            "raw": "",
        }
        mock_sitemap.return_value = []

        discover_urls("https://example.com")

        called_urls = [call.args[0] for call in mock_sitemap.call_args_list]
        assert called_urls.count("https://example.com/sitemap.xml") == 1

    @patch("crawler.fetch_sitemap")
    @patch("crawler.fetch_robots_txt")
    def test_trailing_slash_normalised(self, mock_robots, mock_sitemap):
        mock_robots.return_value = {"disallowed": [], "sitemaps": [], "raw": ""}
        mock_sitemap.return_value = []

        discover_urls("https://example.com/")

        mock_robots.assert_called_once_with("https://example.com")
