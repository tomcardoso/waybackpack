import os
import re
import tempfile

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

# "?" isn't a glob character: in a pattern, as in a URL, it starts the query.
GLOB_CHARS = "*["

SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

DEFAULT_PORT_PATTERN = re.compile(r":(80|443)\Z")


def has_glob(s):
    return any(c in s for c in GLOB_CHARS)


def strip_www(host):
    # The CDX index treats example.com and www.example.com as the same host.
    if host.startswith("www.") and not has_glob(host):
        return host[4:]
    return host


def split_url(url):
    # Only the host is lowercased here; matching ignores case (see below).
    url = SCHEME_PATTERN.sub("", url)
    end = min([i for i in (url.find("/"), url.find("?")) if i != -1] or [len(url)])
    host, rest = url[:end], url[end:]
    # Default ports are dropped, as normalize_original does for snapshots.
    host = DEFAULT_PORT_PATTERN.sub("", host.lower())
    return strip_www(host), rest


def normalize_original(url):
    # Reduce to host/path?query, without the scheme or any default port.
    parsed = urlparse(url if SCHEME_PATTERN.match(url) else "http://" + url)
    host = strip_www((parsed.hostname or "").lower())
    default_port = {"http": 80, "https": 443}.get(parsed.scheme)
    if parsed.port and parsed.port != default_port:
        host += ":{0}".format(parsed.port)
    rest = parsed.path or "/"
    if parsed.query:
        rest += "?" + parsed.query
    return host + rest


def glob_to_regex(pattern):
    return re.compile(translate(pattern) + r"\Z", re.DOTALL | re.IGNORECASE)


def translate(pattern, query=False):
    # *    matches anything except "/" (in a query, anything at all)
    # **   matches anything, including "/"
    # **/  matches zero or more whole directories
    # [..] matches a character class; [!..] negates it
    # Matching is case-insensitive.
    i, n = 0, len(pattern)
    out = []
    while i < n:
        c = pattern[i]
        if pattern.startswith("**/", i) and not query:
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append(".*" if query else "[^/]*")
            i += 1
        elif c == "[" and pattern.find("]", i + 2) != -1:
            j = pattern.find("]", i + 2)
            start = i + 1
            body = pattern[start:j]
            negate = body[0] == "!"
            if negate:
                body = body[1:]
            # As in fnmatch, only "!" negates; escape everything else that
            # is special inside a regex class, except "-" for ranges.
            body = "".join("\\" + ch if ch in "\\[]^&~|" else ch for ch in body)
            out.append("[" + ("^" if negate else "") + body + "]")
            i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


class WildcardPattern(object):
    def __init__(self, pattern):
        self.pattern = pattern
        # Snapshot URLs are matched without a fragment, so drop the pattern's.
        url, sep, fragment = pattern.partition("#")
        self.fragment = fragment if sep else None
        host, rest = split_url(url)
        path, sep, query = rest.partition("?")
        path = path or "/"
        has_query = sep == "?"

        # The CDX API only understands prefix and domain matches, so
        # cdx_url is the coarser query; matches() applies the full pattern.
        if has_glob(host):
            if not (host.startswith("*.") and not has_glob(host[2:])):
                raise ValueError(
                    "In --wildcard mode, the host can only contain a wildcard as a leading '*.', e.g., '*.example.com/...'. Got: {0!r}".format(
                        host
                    )
                )
            self.cdx_url = host
        elif has_glob(path):
            first = min(path.index(c) for c in GLOB_CHARS if c in path)
            self.cdx_url = host + path[:first] + "*"
        elif has_query:
            # Query strings are narrowed locally, not in the CDX query.
            self.cdx_url = host + path + "*"
        else:
            self.cdx_url = None

        if host.startswith("*."):
            # Match the host itself (with or without www.) or any subdomain.
            host_regex = r"(?:[^/]*\.)?" + re.escape(host[2:])
        else:
            host_regex = translate(host)
        if not has_query:
            # No "?" in the pattern: any query string, or none.
            query_regex = r"(?:\?.*)?"
        elif query:
            query_regex = r"\?" + translate(query, query=True)
        else:
            # A trailing "?": no query string.
            query_regex = ""
        try:
            self.regex = re.compile(
                host_regex + translate(path) + query_regex + r"\Z",
                re.DOTALL | re.IGNORECASE,
            )
        except re.error as e:
            raise ValueError(
                "Invalid --wildcard pattern {0!r}: {1}".format(pattern, e.msg)
            )

    @property
    def is_wildcard(self):
        return self.cdx_url is not None

    def matches(self, original_url):
        return self.regex.match(normalize_original(original_url)) is not None


def is_case_insensitive(directory):
    # In a fresh, empty directory inside the target, create two files whose
    # names differ only by case. If only one survives, the filesystem is
    # case-insensitive (or at least collides the way we care about).
    os.makedirs(directory, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as probe:
        for name in ("WaybackPack", "wAYBACKpACK"):
            with open(os.path.join(probe, name), "wb"):
                pass
        return len(os.listdir(probe)) == 1
