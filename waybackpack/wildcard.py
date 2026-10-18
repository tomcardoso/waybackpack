import os
import re
import tempfile

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

GLOB_CHARS = "*?["

SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def has_glob(s):
    return any(c in s for c in GLOB_CHARS)


def split_url(url):
    # Only the host is lowercased; paths are case-sensitive on the server.
    url = SCHEME_PATTERN.sub("", url)
    slash = url.find("/")
    if slash == -1:
        return url.lower(), ""
    return url[:slash].lower(), url[slash:]


def normalize_original(url):
    # Reduce to host/path?query, without the scheme or any default port.
    parsed = urlparse(url if SCHEME_PATTERN.match(url) else "http://" + url)
    host = (parsed.hostname or "").lower()
    default_port = {"http": 80, "https": 443}.get(parsed.scheme)
    if parsed.port and parsed.port != default_port:
        host += ":{0}".format(parsed.port)
    rest = parsed.path or "/"
    if parsed.query:
        rest += "?" + parsed.query
    return host + rest


def glob_to_regex(pattern):
    # *    matches anything except "/"
    # **   matches anything, including "/"
    # **/  matches zero or more whole directories
    # ?    matches one character, except "/"
    # [..] matches a character class; [!..] negates it
    i, n = 0, len(pattern)
    out = []
    while i < n:
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[" and pattern.find("]", i + 2) != -1:
            j = pattern.find("]", i + 2)
            start = i + 1
            body = pattern[start:j]
            if body[0] == "!":
                body = "^" + body[1:]
            out.append("[" + body.replace("\\", "\\\\") + "]")
            i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out) + r"\Z", re.DOTALL)


class WildcardPattern(object):
    def __init__(self, pattern):
        self.pattern = pattern
        host, rest = split_url(pattern)
        self.normalized = host + (rest or "/")

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
        elif has_glob(rest):
            first = min(rest.index(c) for c in GLOB_CHARS if c in rest)
            self.cdx_url = host + rest[:first] + "*"
        else:
            self.cdx_url = None

        self.regex = glob_to_regex(self.normalized)

    @property
    def is_wildcard(self):
        return self.cdx_url is not None

    def matches(self, original_url):
        return self.regex.match(normalize_original(original_url)) is not None


def is_case_insensitive(directory):
    # Write a mixed-case temporary file, then look for it under other casing.
    os.makedirs(directory, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="WaybackPack-Case-", dir=directory)
    os.close(fd)
    try:
        head, tail = os.path.split(path)
        return os.path.exists(os.path.join(head, tail.swapcase()))
    finally:
        os.remove(path)
