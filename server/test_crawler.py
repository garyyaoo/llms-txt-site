import pytest
from unittest.mock import patch, MagicMock
from crawler import fetch_robots_txt, fetch_sitemap, discover_urls, score_url, _is_crawlable


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
        robots = "User-agent: *\nDISALLOW: /upper/\n\nSITEMAP: https://example.com/sitemap.xml\n"
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

    @patch("crawler.fetch_sitemap")
    @patch("crawler.fetch_robots_txt")
    def test_llms_txt_filtered_out(self, mock_robots, mock_sitemap):
        mock_robots.return_value = {"disallowed": [], "sitemaps": [], "raw": ""}
        mock_sitemap.return_value = [
            "https://example.com/about",
            "https://example.com/llms.txt",
            "https://example.com/llms-full.txt",
        ]

        result = discover_urls("https://example.com")

        assert "https://example.com/about" in result["page_urls"]
        assert "https://example.com/llms.txt" not in result["page_urls"]
        assert "https://example.com/llms-full.txt" not in result["page_urls"]


# ── score_url ─────────────────────────────────────────────────────────────────

class TestScoreUrl:
    # Subdomain boosts
    def test_docs_subdomain_scores_highest(self):
        assert score_url("https://docs.example.com/") == 50

    def test_api_subdomain_scores_highest(self):
        assert score_url("https://api.example.com/") == 50

    def test_help_subdomain_scores_highest(self):
        assert score_url("https://help.example.com/") == 50

    def test_unknown_subdomain_no_boost(self):
        assert score_url("https://app.example.com/") == 0

    # Keyword boosts
    def test_blog_path_scores_0(self):
        # /blog removed from PRIORITY_KEYWORDS (UGC section)
        assert score_url("https://example.com/blog") == 0

    def test_docs_path_scores_40(self):
        assert score_url("https://example.com/docs") == 40

    def test_features_path_scores_40(self):
        assert score_url("https://example.com/features") == 40

    def test_pricing_path_scores_zero(self):
        assert score_url("https://example.com/pricing") == 0

    def test_no_keyword_no_boost(self):
        assert score_url("https://example.com/") == 0

    def test_unknown_path_no_boost(self):
        assert score_url("https://example.com/zeroclick") == 0

    # Depth penalty
    def test_depth_1_no_penalty(self):
        assert score_url("https://example.com/about") == 40   # keyword + no penalty

    def test_depth_2_penalised(self):
        # no keyword, depth 2 → penalty = 5
        assert score_url("https://example.com/blog/post") == -5

    def test_depth_3_penalised(self):
        # no keyword, depth 3, path len 23 → depth -20, length -1 → -21
        assert score_url("https://example.com/resources/articles/foo") == -21

    def test_depth_4_penalised_more(self):
        # no keyword, depth 4 → penalty = 40
        assert score_url("https://example.com/a/b/c/d") == -40

    def test_depth_2_no_keyword_penalised(self):
        # depth 2, no keyword → penalty = 5
        assert score_url("https://example.com/a/b") == -5

    # Subdomain + depth interaction
    def test_docs_subdomain_deep_path_still_penalised(self):
        # subdomain boost +50, depth 4 → penalty = 40 → 10
        assert score_url("https://docs.example.com/a/b/c/d") == 10

    # Keyword segment matching — keywords must match a full path segment
    def test_keyword_in_nested_segment_does_not_boost(self):
        # /legal/support-policy contains "support" as a substring but not as a segment
        assert score_url("https://example.com/legal/support-policy") < 40

    def test_support_segment_scores_40(self):
        assert score_url("https://example.com/support") == 40

    def test_keyword_as_first_segment_scores_40(self):
        # /docs (+40), depth 2 penalty (-5), path len 21 → length penalty max(0,21-20)//2=0 → 35
        assert score_url("https://example.com/docs/getting-started") == 35

    def test_non_keyword_segment_path_no_boost(self):
        # /solutions has no keyword; subdomain is www which is not in HIGH_PRIORITY_SUBDOMAINS
        assert score_url("https://example.com/solutions") == 0

    # Homepage
    def test_homepage_scores_zero(self):
        assert score_url("https://example.com/") == 0


# ── _is_crawlable ─────────────────────────────────────────────────────────────

class TestIsCrawlable:
    BASE = "example.com"

    # Scheme filtering
    def test_http_allowed(self):
        assert _is_crawlable("http://example.com/page", self.BASE) is True

    def test_https_allowed(self):
        assert _is_crawlable("https://example.com/page", self.BASE) is True

    def test_mailto_rejected(self):
        assert _is_crawlable("mailto:info@example.com", self.BASE) is False

    def test_javascript_rejected(self):
        assert _is_crawlable("javascript:void(0)", self.BASE) is False

    def test_ftp_rejected(self):
        assert _is_crawlable("ftp://example.com/file", self.BASE) is False

    # Domain filtering
    def test_same_domain_allowed(self):
        assert _is_crawlable("https://example.com/about", self.BASE) is True

    def test_subdomain_same_root_allowed(self):
        assert _is_crawlable("https://docs.example.com/guide", self.BASE) is True

    def test_different_domain_rejected(self):
        assert _is_crawlable("https://other.com/page", self.BASE) is False

    def test_relative_url_allowed(self):
        assert _is_crawlable("/about", self.BASE) is True

    # Extension filtering
    def test_image_jpg_rejected(self):
        assert _is_crawlable("https://example.com/image.jpg", self.BASE) is False

    def test_image_png_rejected(self):
        assert _is_crawlable("https://example.com/logo.png", self.BASE) is False

    def test_css_rejected(self):
        assert _is_crawlable("https://example.com/style.css", self.BASE) is False

    def test_js_rejected(self):
        assert _is_crawlable("https://example.com/app.js", self.BASE) is False

    def test_pdf_rejected(self):
        assert _is_crawlable("https://example.com/doc.pdf", self.BASE) is False

    def test_html_page_allowed(self):
        assert _is_crawlable("https://example.com/page.html", self.BASE) is True

    def test_no_extension_allowed(self):
        assert _is_crawlable("https://example.com/about", self.BASE) is True

    # Anchor links
    def test_pure_anchor_rejected(self):
        assert _is_crawlable("#section", self.BASE) is False

    def test_page_with_fragment_allowed(self):
        # has a path — fragment stripped by caller, so is crawlable
        assert _is_crawlable("https://example.com/page#section", self.BASE) is True


# ── i18n deduplication ────────────────────────────────────────────────────────

class TestI18nFiltering:
    ROBOTS = {"disallowed": [], "sitemaps": [], "raw": ""}

    def _discover(self, urls):
        with patch("crawler.fetch_robots_txt", return_value=self.ROBOTS), \
             patch("crawler.fetch_sitemap", return_value=urls):
            return discover_urls("https://example.com")["page_urls"]

    def test_locale_duplicate_removed_when_canonical_exists(self):
        urls = ["https://example.com/about", "https://example.com/fr/about"]
        result = self._discover(urls)
        assert "https://example.com/about" in result
        assert "https://example.com/fr/about" not in result

    def test_region_locale_removed(self):
        urls = ["https://example.com/help", "https://example.com/en-gb/help"]
        result = self._discover(urls)
        assert "https://example.com/help" in result
        assert "https://example.com/en-gb/help" not in result

    def test_locale_kept_when_no_canonical(self):
        # /fr/about exists but /about does not — keep it
        urls = ["https://example.com/fr/about"]
        result = self._discover(urls)
        assert "https://example.com/fr/about" in result

    def test_multiple_locales_all_removed(self):
        urls = [
            "https://example.com/about",
            "https://example.com/fr/about",
            "https://example.com/ja/about",
            "https://example.com/zh-tw/about",
        ]
        result = self._discover(urls)
        assert "https://example.com/about" in result
        assert "https://example.com/fr/about" not in result
        assert "https://example.com/ja/about" not in result
        assert "https://example.com/zh-tw/about" not in result

    def test_non_locale_path_not_filtered(self):
        # /products and /pricing are not locale paths
        urls = ["https://example.com/products", "https://example.com/pricing"]
        result = self._discover(urls)
        assert "https://example.com/products" in result
        assert "https://example.com/pricing" in result

    def test_deep_locale_path_removed(self):
        urls = ["https://example.com/help/getting-started", "https://example.com/ko/help/getting-started"]
        result = self._discover(urls)
        assert "https://example.com/help/getting-started" in result
        assert "https://example.com/ko/help/getting-started" not in result
