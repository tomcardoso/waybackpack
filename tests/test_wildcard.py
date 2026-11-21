#!/usr/bin/env python
import io
import os
import shutil
import tempfile
import unittest
import warnings
from unittest.mock import MagicMock, PropertyMock, patch

import requests

import waybackpack
import waybackpack.cli
from waybackpack import wildcard
from waybackpack.wildcard import WildcardPattern, glob_to_regex

CDX_FIELDS = ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest"]


def cdx_response(*rows):
    res = MagicMock()
    res.status_code = 200
    res.json.return_value = [CDX_FIELDS] + [
        ["k", ts, url, "text/html", "200", "d"] for ts, url in rows
    ]
    return res


class Test(unittest.TestCase):
    def match(self, pattern, url):
        return WildcardPattern(pattern).matches(url)

    def test_cdx_url(self):
        p = WildcardPattern("http://nywork.craigslist.org/**/*.html")
        assert p.cdx_url == "nywork.craigslist.org/*"
        p = WildcardPattern("example.com/img/photo*.jpg")
        assert p.cdx_url == "example.com/img/photo*"
        p = WildcardPattern("*.example.com/a")
        assert p.cdx_url == "*.example.com"
        assert not WildcardPattern("example.com/a").is_wildcard

    def test_bad_host(self):
        with self.assertRaises(ValueError):
            WildcardPattern("www.*.com/a")

    def test_double_star(self):
        pat = "nywork.craigslist.org/**/*.html"
        assert self.match(pat, "http://nywork.craigslist.org/abc/123.html")
        assert self.match(pat, "http://nywork.craigslist.org/a/b/c/123.html")
        assert self.match(pat, "http://nywork.craigslist.org/123.html")
        assert not self.match(pat, "http://nywork.craigslist.org/a/123.htm")
        assert self.match(pat, "http://nywork.craigslist.org/a/123.html?x=1")

    def test_single_star_stops_at_slash(self):
        assert self.match("example.com/a/*.html", "http://example.com/a/b.html")
        assert not self.match("example.com/a/*.html", "http://example.com/a/b/c.html")

    def test_class(self):
        assert self.match("example.com/p[0-9].html", "http://example.com/p1.html")
        assert not self.match("example.com/p[0-9].html", "http://example.com/p12.html")
        assert self.match("example.com/p[12].html", "http://example.com/p2.html")
        assert not self.match("example.com/p[!12].html", "http://example.com/p2.html")

    def test_no_query_in_pattern_allows_any_query(self):
        pat = "example.com/**/*.pdf"
        assert self.match(pat, "http://example.com/a/report.pdf")
        assert self.match(pat, "http://example.com/a/report.pdf?download=1")
        assert self.match(pat, "http://example.com/report.pdf?u=a/b.pdf")
        assert not self.match(pat, "http://example.com/report.pdfx?download=1")

    def test_query_in_pattern(self):
        pat = "example.com/view.php?id=*"
        p = WildcardPattern(pat)
        assert p.is_wildcard
        assert p.cdx_url == "example.com/view.php*"
        assert self.match(pat, "http://example.com/view.php?id=5")
        assert self.match(pat, "http://example.com/view.php?id=5&page=2")
        assert self.match(pat, "http://example.com/view.php?id=a/b")
        assert self.match(pat, "http://example.com/VIEW.php?ID=5")
        assert not self.match(pat, "http://example.com/view.php")
        assert not self.match(pat, "http://example.com/view.php?page=2&id=5")
        assert not self.match(pat, "http://example.com/view.phpXid=5")
        assert not self.match(pat, "http://example.com/a/view.php?id=5")

    def test_exact_query(self):
        # A pasted URL with a query string is a pattern for exactly that URL.
        pat = "example.com/view.php?id=5"
        assert WildcardPattern(pat).cdx_url == "example.com/view.php*"
        assert self.match(pat, "http://example.com/view.php?id=5")
        assert not self.match(pat, "http://example.com/view.php?id=50")
        assert self.match("example.com/s?q=a?b", "http://example.com/s?q=a?b")

    def test_trailing_question_mark_means_no_query(self):
        pat = "example.com/page.php?"
        assert self.match(pat, "http://example.com/page.php")
        assert not self.match(pat, "http://example.com/page.php?id=1")

    def test_query_without_path(self):
        p = WildcardPattern("example.com?x=*")
        assert p.cdx_url == "example.com/*"
        assert self.match("example.com?x=*", "http://example.com/?x=1")
        assert not self.match("example.com?x=*", "http://example.com/a?x=1")
        assert self.match("*.example.com?x=*", "http://news.example.com/?x=1")
        with self.assertRaises(ValueError):
            WildcardPattern("exa*mple.com?x=1")

    def test_fragment_ignored(self):
        # Snapshot URLs are matched without their fragment, so patterns are too.
        p = WildcardPattern("example.com/view.php?id=*#top")
        assert p.fragment == "top"
        assert p.cdx_url == "example.com/view.php*"
        assert self.match(
            "example.com/view.php?id=*#top", "http://example.com/view.php?id=5#x"
        )
        assert self.match("example.com/*.php#1", "http://example.com/view.php")
        assert WildcardPattern("example.com/*.php").fragment is None

    def test_fragment_logged(self):
        s = self.session()
        with self.assertLogs("waybackpack.cdx", level="INFO") as cm:
            waybackpack.search("example.com/**/*.html#top", session=s, wildcard=True)
        assert s.get.call_args[1]["params"]["url"] == "example.com/*"
        assert any("Ignoring '#top'" in m for m in cm.output)

    def test_scheme_port_host_case(self):
        assert self.match("example.com/**", "http://EXAMPLE.com:80/x/y")
        assert self.match("EXAMPLE.com/**", "http://example.com/x")
        assert wildcard.normalize_original("http://a.com:80/x") == "a.com/x"
        assert wildcard.normalize_original("http://a.com:8080/x") == "a.com:8080/x"

    def test_case_insensitive(self):
        assert self.match("example.com/Foo/*", "http://example.com/foo/a")
        assert self.match("example.com/**/*.html", "http://example.com/A/B.HTML")
        assert self.match("example.com/p[a-c].html", "http://example.com/PB.html")

    def test_subdomain(self):
        assert self.match("*.example.com/**", "http://a.b.example.com/x")
        assert self.match("*.example.com/**", "http://example.com/x")
        assert self.match("*.example.com/**", "http://www.example.com:80/x")
        assert not self.match("*.example.com/**", "http://badexample.com/x")
        assert not self.match("*.example.com/**", "http://example.com.evil.org/x")

    def test_default_port_in_pattern(self):
        p = WildcardPattern("example.com:80/*")
        assert p.cdx_url == "example.com/*"
        assert self.match("example.com:80/*", "http://example.com:80/a")
        assert self.match("example.com:80/*", "http://example.com/a")
        assert self.match("example.com:443/*", "https://example.com:443/a")
        assert self.match("example.com:8080/*", "http://example.com:8080/a")
        assert not self.match("example.com:8080/*", "http://example.com/a")

    def test_class_literals(self):
        # As in fnmatch, only [!...] negates; ^ and [ are literal in a class.
        pat = "example.com/files/[^a]*"
        assert self.match(pat, "http://example.com/files/^x")
        assert self.match(pat, "http://example.com/files/ax")
        assert not self.match(pat, "http://example.com/files/bx")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert self.match("example.com/[[]x", "http://example.com/[x")
            assert self.match("example.com/[a&&b]", "http://example.com/&")

    def test_bad_class(self):
        with self.assertRaises(ValueError) as cm:
            WildcardPattern("example.com/[z-a]")
        assert "[z-a]" in str(cm.exception)
        with self.assertRaises(waybackpack.cdx.WaybackpackException):
            waybackpack.search("example.com/[z-a]", session=MagicMock(), wildcard=True)

    def test_cli_bad_pattern_is_usage_error(self):
        argv = ["waybackpack", "example.com/[z-a]", "--wildcard", "--list"]
        with patch("sys.argv", argv), patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as cm:
                waybackpack.cli.parse_args()
        assert cm.exception.code == 2

    def test_regex_escapes(self):
        assert glob_to_regex("a.b+c").match("a.b+c")
        assert not glob_to_regex("a.b").match("axb")

    ROWS = [
        ("20050101000000", "http://example.com/a/one.html"),
        ("20050102000000", "http://example.com/a/b/two.html"),
        ("20050103000000", "http://example.com/a/three.txt"),
        ("20050104000000", "http://example.com/Four.html"),
    ]

    def session(self):
        s = MagicMock()
        s.get.return_value = cdx_response(*self.ROWS)
        return s

    def test_search_filters_and_queries_prefix(self):
        s = self.session()
        snaps = waybackpack.search("example.com/**/*.html", session=s, wildcard=True)
        assert s.get.call_args[1]["params"]["url"] == "example.com/*"
        assert s.get.call_args[1]["params"]["filter"] == ["!statuscode:[345].."]
        assert [x["original"] for x in snaps] == [
            "http://example.com/a/one.html",
            "http://example.com/a/b/two.html",
            "http://example.com/Four.html",
        ]

    def test_no_wildcard_flag_is_untouched(self):
        s = self.session()
        snaps = waybackpack.search("example.com/**/*.html", session=s)
        assert s.get.call_args[1]["params"]["url"] == "example.com/**/*.html"
        assert s.get.call_args[1]["params"]["filter"] is None
        assert len(snaps) == 4

    def test_flag_without_glob_chars(self):
        s = self.session()
        with self.assertLogs("waybackpack.cdx", level="WARNING"):
            snaps = waybackpack.search("example.com/a", session=s, wildcard=True)
        assert s.get.call_args[1]["params"]["url"] == "example.com/a"
        assert len(snaps) == 4

    def test_paging(self):
        page1 = cdx_response(self.ROWS[0], self.ROWS[3])
        page1.json.return_value += [[], ["KEY1"]]
        page2 = cdx_response(self.ROWS[1])
        s = MagicMock()
        s.get.side_effect = [page1, page2]
        snaps = waybackpack.search("example.com/**/*.html", session=s, wildcard=True)
        assert s.get.call_count == 2
        assert "resumeKey" not in s.get.call_args_list[0][1]["params"]
        assert s.get.call_args_list[1][1]["params"]["resumeKey"] == "KEY1"
        assert s.get.call_args_list[0][1]["params"]["showResumeKey"] == "true"
        assert [x["timestamp"] for x in snaps] == [
            "20050101000000",
            "20050104000000",
            "20050102000000",
        ]

    def test_filters(self):
        s = self.session()
        waybackpack.search(
            "example.com/**/*.pdf",
            session=s,
            wildcard=True,
            filters=["mimetype:application/pdf"],
        )
        assert s.get.call_args[1]["params"]["filter"] == [
            "!statuscode:[345]..",
            "mimetype:(?i)application/pdf",
        ]
        s = self.session()
        waybackpack.search("example.com", session=s, filters=["mimetype:text/html"])
        assert s.get.call_args[1]["params"]["filter"] == ["mimetype:(?i)text/html"]

    def test_delay_between_pages(self):
        page1 = cdx_response(self.ROWS[0])
        page1.json.return_value += [[], ["KEY1"]]
        s = MagicMock()
        s.get.side_effect = [page1, cdx_response(self.ROWS[1])]
        with patch("waybackpack.cdx.time.sleep") as sleep:
            waybackpack.search(
                "example.com/**/*.html", session=s, wildcard=True, delay=3
            )
        sleep.assert_called_once_with(3)

    def test_repeated_resume_key_stops(self):
        page = cdx_response(self.ROWS[0])
        page.json.return_value += [[], ["SAME"]]
        s = MagicMock()
        s.get.return_value = page
        waybackpack.search("example.com/**/*.html", session=s, wildcard=True)
        assert s.get.call_count == 2

    def paged_session(self, *pages):
        s = MagicMock()
        s.max_retries = 2
        s.delay_retry = 0
        s.get.side_effect = list(pages)
        return s

    def read_error(self):
        res = MagicMock()
        res.status_code = 200
        type(res).content = PropertyMock(
            side_effect=requests.exceptions.ChunkedEncodingError("dropped")
        )
        return res

    def test_body_read_error_retries_page(self):
        page1 = cdx_response(self.ROWS[0])
        page1.json.return_value += [[], ["KEY1"]]
        page2 = cdx_response(self.ROWS[1])
        s = self.paged_session(page1, self.read_error(), page2)
        with patch("waybackpack.cdx.time.sleep"):
            snaps = waybackpack.search("example.com/**", session=s, wildcard=True)
        assert s.get.call_count == 3
        assert s.get.call_args_list[1] == s.get.call_args_list[2]
        assert [x["timestamp"] for x in snaps] == ["20050101000000", "20050102000000"]

    def test_body_read_error_gives_up_with_resume_key(self):
        page1 = cdx_response(self.ROWS[0], self.ROWS[1])
        page1.json.return_value += [[], ["KEY1"]]
        s = self.paged_session(page1, *[self.read_error() for _ in range(3)])
        with patch("waybackpack.cdx.time.sleep"):
            with self.assertRaises(waybackpack.cdx.WaybackpackException) as cm:
                waybackpack.search("example.com/**", session=s, wildcard=True)
        assert s.get.call_count == 4
        assert "2 rows" in str(cm.exception)
        assert "'KEY1'" in str(cm.exception)

    def test_later_page_without_header(self):
        # Unverified whether later pages repeat the header row, so drop the
        # first row of a later page only if it equals the first page's header.
        page1 = cdx_response(self.ROWS[0])
        page1.json.return_value += [[], ["KEY1"]]
        page2 = cdx_response(self.ROWS[1], self.ROWS[3])
        page2.json.return_value = page2.json.return_value[1:]
        s = self.paged_session(page1, page2)
        snaps = waybackpack.search("example.com/**", session=s, wildcard=True)
        assert [x["timestamp"] for x in snaps] == [
            "20050101000000",
            "20050102000000",
            "20050104000000",
        ]

    def test_empty_page_with_resume_key(self):
        page1 = cdx_response()
        page1.json.return_value += [[], ["KEY1"]]
        s = self.paged_session(page1, cdx_response(self.ROWS[0]))
        with patch("waybackpack.cdx.time.sleep") as sleep:
            snaps = waybackpack.search(
                "example.com/**", session=s, wildcard=True, delay=2
            )
        assert s.get.call_count == 2
        sleep.assert_called_once_with(2)
        assert [x["timestamp"] for x in snaps] == ["20050101000000"]

    def test_duplicate_rows_across_pages_dropped(self):
        page1 = cdx_response(self.ROWS[0], self.ROWS[1])
        page1.json.return_value += [[], ["KEY1"]]
        page2 = cdx_response(self.ROWS[1], self.ROWS[3])
        s = self.paged_session(page1, page2)
        snaps = waybackpack.search("example.com/**", session=s, wildcard=True)
        assert [x["timestamp"] for x in snaps] == [
            "20050101000000",
            "20050102000000",
            "20050104000000",
        ]

    def test_collapse_applied_locally_across_pages(self):
        # A live check showed that the CDX API drops a row at each page
        # boundary when collapse and resumeKey paging are combined.
        page1 = cdx_response(
            ("20050101000000", "http://example.com/a.html"),
            ("20050102000000", "http://example.com/a.html"),
        )
        page1.json.return_value += [[], ["KEY1"]]
        page2 = cdx_response(
            ("20050103000000", "http://example.com/a.html"),
            ("20050104000000", "http://example.com/b.html"),
        )
        for page in (page1, page2):
            for row in page.json.return_value[1:]:
                if len(row) > 2:
                    row[0] = row[2]  # urlkey
        s = self.paged_session(page1, page2)
        snaps = waybackpack.search(
            "example.com/*.html", session=s, wildcard=True, collapse=["urlkey"]
        )
        assert all(c[1]["params"]["collapse"] is None for c in s.get.call_args_list)
        assert [x["timestamp"] for x in snaps] == ["20050101000000", "20050104000000"]

    def test_collapse_prefix_and_repeated(self):
        rows = [
            ("20050101000000", "http://example.com/a.html"),
            ("20050101120000", "http://example.com/a.html"),
            ("20050102000000", "http://example.com/a.html"),
            ("20050102000000", "http://example.com/b.html"),
        ]
        res = cdx_response(*rows)
        for i, row in enumerate(res.json.return_value[1:]):
            row[0] = row[2]
            row[5] = "d" if i < 3 else "e"
        s = MagicMock()
        s.get.return_value = res
        snaps = waybackpack.search(
            "example.com/*.html", session=s, wildcard=True, collapse="timestamp:8"
        )
        assert [x["timestamp"] for x in snaps] == ["20050101000000", "20050102000000"]
        snaps = waybackpack.search(
            "example.com/*.html",
            session=s,
            wildcard=True,
            collapse=["timestamp:8", "digest"],
        )
        assert [x["timestamp"] for x in snaps] == ["20050101000000"]

    def test_collapse_bad_field(self):
        s = self.session()
        with self.assertRaises(waybackpack.cdx.WaybackpackException):
            waybackpack.search(
                "example.com/*.html", session=s, wildcard=True, collapse=["nope"]
            )

    def test_collapse_sent_without_wildcard(self):
        s = self.session()
        waybackpack.search("example.com", session=s, collapse=["urlkey"])
        assert s.get.call_args[1]["params"]["collapse"] == ["urlkey"]

    def test_uniques_only_with_wildcard(self):
        res = MagicMock()
        res.status_code = 200
        res.json.return_value = [
            CDX_FIELDS + ["dupecount"],
            ["k", "20050101000000", "http://example.com/a.html", "t", "200", "d", "0"],
            ["k", "20050102000000", "http://example.com/a.html", "t", "200", "d", "1"],
            ["k", "20050103000000", "http://example.com/b.txt", "t", "200", "e", "0"],
        ]
        s = MagicMock()
        s.get.return_value = res
        snaps = waybackpack.search(
            "example.com/*.html", session=s, wildcard=True, uniques_only=True
        )
        assert [x["timestamp"] for x in snaps] == ["20050101000000"]

    def test_uniques_only_wildcard_compares_locally(self):
        # Per URL, keep the first snapshot of each digest (A, B, A -> A, B),
        # whatever dupecount the CDX API reports.
        fields = CDX_FIELDS + ["dupecount"]

        def row(ts, url, digest, dupecount):
            return [url, ts, "http://" + url, "text/html", "200", digest, dupecount]

        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = [
            fields,
            row("20050101000000", "example.com/a.html", "A", "3"),
            row("20050102000000", "example.com/a.html", "B", "0"),
            [],
            ["KEY1"],
        ]
        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = [
            fields,
            row("20050103000000", "example.com/a.html", "A", "0"),
            row("20050104000000", "example.com/a.html", "C", "0"),
            row("20050101000000", "example.com/b.html", "A", "1"),
            row("20050102000000", "example.com/b.html", "A", "0"),
        ]
        s = self.paged_session(page1, page2)
        snaps = waybackpack.search(
            "example.com/*.html", session=s, wildcard=True, uniques_only=True
        )
        assert [(x["original"][-6:], x["timestamp"][6:8]) for x in snaps] == [
            ("a.html", "01"),
            ("a.html", "02"),
            ("a.html", "04"),
            ("b.html", "01"),
        ]

    def test_non_wildcard_params_unchanged(self):
        s = self.session()
        waybackpack.search("example.com", session=s, from_date="2005", to_date="2006")
        args, kwargs = s.get.call_args
        assert s.get.call_count == 1
        assert args == (waybackpack.cdx.SEARCH_URL,)
        assert kwargs == {
            "params": {
                "url": "example.com",
                "from": "2005",
                "to": "2006",
                "showDupeCount": "true",
                "output": "json",
                "collapse": None,
                "filter": None,
            }
        }

    def test_not_json(self):
        res = MagicMock()
        res.status_code = 200
        res.content = b"<html>Temporarily Offline</html>"
        res.json.side_effect = ValueError("nope")
        s = MagicMock()
        s.get.return_value = res
        with self.assertRaises(waybackpack.cdx.WaybackpackException):
            waybackpack.search("example.com/**", session=s, wildcard=True)

    def test_www(self):
        assert self.match("dol.gov/**", "http://www.dol.gov:80/a/b.html")
        assert self.match("www.dol.gov/**", "http://dol.gov/a")
        assert not self.match("dol.gov/**", "http://www.other.gov/a")

    def test_download_layout_and_list(self):
        s = self.session()
        snaps = waybackpack.search("example.com/**/*.html", session=s, wildcard=True)
        pack = waybackpack.Pack(
            "example.com/**/*.html", snapshots=snaps, session=s, wildcard=True
        )
        assert pack.timestamps == [x["timestamp"] for x in snaps]
        assert (
            pack.assets[1]
            .get_archive_url()
            .endswith("/web/20050102000000/http://example.com/a/b/two.html")
        )
        for a in pack.assets:
            a.fetch = MagicMock(return_value=b"x")
        d = tempfile.mkdtemp()
        try:
            pack.download_to(d)
            found = sorted(
                os.path.relpath(os.path.join(r, f), d)
                for r, _, fs in os.walk(d)
                for f in fs
            )
        finally:
            shutil.rmtree(d)
        assert found == [
            "20050101000000/example.com/a/one.html",
            "20050102000000/example.com/a/b/two.html",
            "20050104000000/example.com/Four.html",
        ]

    def download(self, rows, **kwargs):
        snaps = [{"timestamp": ts, "original": url} for ts, url in rows]
        pack = waybackpack.Pack(
            "x", snapshots=snaps, session=MagicMock(), wildcard=True
        )
        for i, a in enumerate(pack.assets):
            a.fetch = MagicMock(return_value=str(i).encode())
        d = tempfile.mkdtemp()
        try:
            with self.assertLogs("waybackpack.pack", level="INFO") as cm:
                pack.download_to(d, **kwargs)
            found = {
                os.path.relpath(os.path.join(r, f), d): open(os.path.join(r, f)).read()
                for r, _, fs in os.walk(d)
                for f in fs
            }
        finally:
            shutil.rmtree(d)
        return found, cm.output

    def test_redirects_skipped(self):
        # A revisit can point back to a redirect; don't save it as a file.
        snaps = [
            {"timestamp": "20050101000000", "original": "http://example.com/a.pdf"},
            {"timestamp": "20050102000000", "original": "http://example.com/b.pdf"},
        ]
        redirect = MagicMock(status_code=302, content=b"")
        ok = MagicMock(status_code=200, content=b"%PDF")
        s = MagicMock(follow_redirects=False)
        s.get.side_effect = [redirect, ok]
        pack = waybackpack.Pack("x", snapshots=snaps, session=s, wildcard=True)
        d = tempfile.mkdtemp()
        try:
            with self.assertLogs("waybackpack", level="INFO") as cm:
                pack.download_to(d, raw=True)
            found = [os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs]
        finally:
            shutil.rmtree(d)
        assert [os.path.basename(f) for f in found] == ["b.pdf"]
        assert any("redirect" in m for m in cm.output)

    def test_wayback_redirect_notice_skipped(self):
        notice = (
            b'<p class="code shift target">Got an HTTP 301 response at crawl time</p>'
            b"<title>Internet Archive Wayback Machine</title>"
            b'<a href="/web/20050101000001/http://example.com/a.html">Impatient?</a>'
        )
        snaps = [
            {"timestamp": "20050101000000", "original": "http://example.com/a.html"}
        ]
        s = MagicMock(follow_redirects=False)
        s.get.return_value = MagicMock(status_code=200, content=notice)
        pack = waybackpack.Pack("x", snapshots=snaps, session=s, wildcard=True)
        d = tempfile.mkdtemp()
        try:
            pack.download_to(d)
            found = [f for _, _, fs in os.walk(d) for f in fs]
        finally:
            shutil.rmtree(d)
        assert found == []

    def test_non_wildcard_still_writes_redirects(self):
        s = MagicMock(follow_redirects=False)
        s.get.return_value = MagicMock(status_code=302, content=b"")
        pack = waybackpack.Pack(
            "example.com/a", timestamps=["20050101000000"], session=s
        )
        d = tempfile.mkdtemp()
        try:
            pack.download_to(d, raw=True)
            found = [f for _, _, fs in os.walk(d) for f in fs]
        finally:
            shutil.rmtree(d)
        assert found == ["a"]

    def test_file_dir_clash_skipped(self):
        ts = "20050101000000"
        for urls in [
            ["http://example.com/about", "http://example.com/about/team"],
            ["http://example.com/about/team", "http://example.com/about"],
        ]:
            found, logs = self.download([(ts, u) for u in urls])
            assert len(found) == 1
            assert any("WARNING" in m and "Skipping" in m for m in logs)

    def test_query_strings_in_filenames(self):
        ts = "20050101000000"
        found, _ = self.download(
            [
                (ts, "http://example.com/p.php?id=1"),
                (ts, "http://example.com/p.php?id=2"),
                (ts, "http://example.com/p.php"),
                (ts, "http://example.com/?a=b/c:d*e"),
            ]
        )
        base = os.path.join(ts, "example.com")
        assert found == {
            os.path.join(base, "p.php%3Fid%3D1"): "0",
            os.path.join(base, "p.php%3Fid%3D2"): "1",
            os.path.join(base, "p.php"): "2",
            os.path.join(base, "index.html%3Fa%3Db%2Fc%3Ad%2Ae"): "3",
        }

    def test_long_query_string_hashed(self):
        ts = "20050101000000"
        found, _ = self.download(
            [
                (ts, "http://example.com/p.php?q=" + "a" * 300),
                (ts, "http://example.com/p.php?q=" + "a" * 299 + "b"),
            ]
        )
        names = [os.path.basename(p) for p in found]
        assert len(names) == 2
        assert all(n.startswith("p.php%3F%23") and len(n) <= 255 for n in names)

    def test_non_wildcard_ignores_query_in_filename(self):
        pack = waybackpack.Pack(
            "example.com/p.php?id=1", timestamps=["20050101000000"], session=MagicMock()
        )
        pack.assets[0].fetch = MagicMock(return_value=b"x")
        d = tempfile.mkdtemp()
        try:
            pack.download_to(d)
            assert os.listdir(os.path.join(d, "20050101000000", "example.com")) == [
                "p.php"
            ]
        finally:
            shutil.rmtree(d)

    def test_case_insensitive_collision_skipped_with_warning(self):
        rows = [
            ("20050101000000", "http://example.com/Foo.html"),
            ("20050101000000", "http://example.com/foo.html"),
        ]
        s = MagicMock()
        s.get.return_value = cdx_response(*rows)
        snaps = waybackpack.search("example.com/*.html", session=s, wildcard=True)
        pack = waybackpack.Pack("x", snapshots=snaps, session=s, wildcard=True)
        for i, a in enumerate(pack.assets):
            a.fetch = MagicMock(return_value=str(i).encode())
        d = tempfile.mkdtemp()
        try:
            with patch("waybackpack.pack.is_case_insensitive", return_value=True):
                with self.assertLogs("waybackpack.pack", level="WARNING") as cm:
                    pack.download_to(d)
            files = os.listdir(os.path.join(d, "20050101000000", "example.com"))
        finally:
            shutil.rmtree(d)
        assert files == ["Foo.html"]
        assert any("case-insensitive" in m for m in cm.output)
        assert any("Skipping" in m for m in cm.output)

    def test_case_sensitive_fs_keeps_both(self):
        d = tempfile.mkdtemp()
        try:
            if wildcard.is_case_insensitive(d):
                self.skipTest("filesystem is case-insensitive")
            rows = [
                ("20050101000000", "http://example.com/Foo.html"),
                ("20050101000000", "http://example.com/foo.html"),
            ]
            s = MagicMock()
            s.get.return_value = cdx_response(*rows)
            snaps = waybackpack.search("example.com/*.html", session=s, wildcard=True)
            pack = waybackpack.Pack("x", snapshots=snaps, session=s, wildcard=True)
            for a in pack.assets:
                a.fetch = MagicMock(return_value=b"x")
            pack.download_to(d)
            assert sorted(
                os.listdir(os.path.join(d, "20050101000000", "example.com"))
            ) == [
                "Foo.html",
                "foo.html",
            ]
            assert os.listdir(d) == ["20050101000000"]  # probe file cleaned up
        finally:
            shutil.rmtree(d)

    def test_probe_runs_and_cleans_up(self):
        d = tempfile.mkdtemp()
        try:
            assert isinstance(
                wildcard.is_case_insensitive(os.path.join(d, "new")), bool
            )
            assert os.listdir(os.path.join(d, "new")) == []
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
