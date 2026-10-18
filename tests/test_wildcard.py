#!/usr/bin/env python
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import waybackpack
from waybackpack.wildcard import (WildcardPattern, glob_to_regex,
                                  is_case_insensitive, normalize_original)

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
        assert not self.match(pat, "http://nywork.craigslist.org/a/123.html?x=1")

    def test_single_star_stops_at_slash(self):
        assert self.match("example.com/a/*.html", "http://example.com/a/b.html")
        assert not self.match("example.com/a/*.html", "http://example.com/a/b/c.html")

    def test_question_and_class(self):
        assert self.match("example.com/p?.html", "http://example.com/p1.html")
        assert not self.match("example.com/p?.html", "http://example.com/p12.html")
        assert self.match("example.com/p[12].html", "http://example.com/p2.html")
        assert not self.match("example.com/p[!12].html", "http://example.com/p2.html")

    def test_scheme_port_host_case(self):
        assert self.match("example.com/**", "http://EXAMPLE.com:80/x/y")
        assert self.match("EXAMPLE.com/**", "http://example.com/x")
        assert normalize_original("http://a.com:80/x") == "a.com/x"
        assert normalize_original("http://a.com:8080/x") == "a.com:8080/x"

    def test_path_case_sensitive(self):
        assert not self.match("example.com/Foo/*", "http://example.com/foo/a")

    def test_subdomain(self):
        assert self.match("*.example.com/**", "http://a.b.example.com/x")
        assert not self.match("*.example.com/**", "http://example.com/x")

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
        assert [x["original"] for x in snaps] == [
            "http://example.com/a/one.html",
            "http://example.com/a/b/two.html",
            "http://example.com/Four.html",
        ]

    def test_no_wildcard_flag_is_untouched(self):
        s = self.session()
        snaps = waybackpack.search("example.com/**/*.html", session=s)
        assert s.get.call_args[1]["params"]["url"] == "example.com/**/*.html"
        assert len(snaps) == 4

    def test_flag_without_glob_chars(self):
        s = self.session()
        with self.assertLogs("waybackpack.cdx", level="WARNING"):
            snaps = waybackpack.search("example.com/a", session=s, wildcard=True)
        assert s.get.call_args[1]["params"]["url"] == "example.com/a"
        assert len(snaps) == 4

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
            if is_case_insensitive(d):
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
            assert isinstance(is_case_insensitive(os.path.join(d, "new")), bool)
            assert os.listdir(os.path.join(d, "new")) == []
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
