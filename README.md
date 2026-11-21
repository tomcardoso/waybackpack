# waybackpack

[![Version](https://img.shields.io/pypi/v/waybackpack.svg)](https://pypi.python.org/pypi/waybackpack) [![Support Python versions](https://img.shields.io/pypi/pyversions/waybackpack.svg)](https://pypi.python.org/pypi/waybackpack)

Waybackpack is a command-line tool that lets you download the entire Wayback Machine archive for a given URL.

For instance, to download every copy of the Department of Labor's homepage through 1996 (which happens to be the first year the site was archived), you'd run:

```sh
waybackpack http://www.dol.gov/ -d ~/Downloads/dol-wayback --to-date 1996
```

Result:

```sh
~/Downloads/dol-wayback/
├── 19961102145216
│   └── www.dol.gov
│       └── index.html
├── 19961103063843
│   └── www.dol.gov
│       └── index.html
├── 19961222171647
│   └── www.dol.gov
│       └── index.html
└── 19961223193614
    └── www.dol.gov
        └── index.html
```

Or, just to print the URLs of all archived snapshots:

```sh
waybackpack http://www.dol.gov/ --list
```

To download archived `.html` pages from across a site, use `--wildcard` (and quote the URL, so your shell doesn't expand it):

```sh
waybackpack "http://example.com/**/*.html" -d ~/Downloads/example-wayback --wildcard --from-date 2005 --to-date 2008 --delay 1 --no-clobber
```

In a pattern, `*` matches within a single path segment, `**` matches across segments (and `**/` also matches no directories at all), `[abc]` matches any of the listed characters, and `[!abc]` matches any other character. Matching ignores case, so `*.html` also matches `PAGE.HTML`. It also ignores the scheme, default ports (`:80` and `:443`), and a leading `www.`. The host can't contain wildcards, except for a leading `*.`: `*.example.com/**` matches `example.com`, `www.example.com`, and any other subdomain of `example.com`.

As in a URL, `?` starts the query string (so, unlike in other globs, it isn't a one-character wildcard):

- With no `?`, the pattern matches the path, and any query string, or none, is allowed. `example.com/**/*.pdf` matches both `example.com/report.pdf` and `example.com/report.pdf?download=1`.
- With a `?`, the query string must match the part after it, where `*` matches anything, including `/`. `example.com/view.php?id=*` matches `view.php?id=5` and `view.php?id=5&page=2`, but not `view.php` or `view.php?page=2&id=5`: query strings are matched as written, so the order of parameters matters.
- A trailing `?` matches only URLs without a query string, e.g., `example.com/page.php?`.

A fragment (anything after `#`) is ignored, in patterns and in snapshot URLs alike, because the CDX API ignores it too: `example.com/view.php#top` searches for `example.com/view.php`.

How it works: waybackpack asks the CDX API for every snapshot under the pattern's fixed prefix (e.g., `example.com/*` for `example.com/**/*.html`), then applies the full pattern itself. So a narrow pattern with a short prefix can still mean downloading a long list of results. Query strings are narrowed only in this second step. If the URL contains no `*`, `[`, or `?`, `--wildcard` treats it as an ordinary URL.

Snapshots that the CDX API lists with a 3xx, 4xx, or 5xx status (redirects and errors) are skipped. Revisits are kept: the Wayback Machine can record an unchanged page as a "revisit" of an earlier capture, which the CDX API lists with a status of `-` and a MIME type of `warc/revisit`, and downloading one gets the earlier capture's content. But a revisit can also point back to a capture that was a redirect (e.g., from `http://` to `https://`) or an error page, and the CDX API doesn't say which. With `--wildcard`, waybackpack skips redirects when downloading, rather than saving them as empty files (unless you use `--follow-redirects`). An error page comes back with an HTTP error, so it is retried (see `--max-retries`) and then skipped.

To skip snapshots whose content hasn't changed, add `--uniques-only`. With `--wildcard`, waybackpack compares the snapshots itself: for each URL, it keeps only the first snapshot of each distinct content (going by the content fingerprint, or `digest`, that the CDX API lists for each snapshot). That skips revisits and identical recaptures, but a page that didn't change during your date range still appears once. If a page changes and later changes back, the return to the earlier version is skipped.

Each snapshot is saved under its own timestamp, host, and path, e.g., `20050101000000/example.com/some/page.html`. A query string is added to the filename, percent-encoded (e.g., `page.php%3Fid%3D1`), or replaced by a hash if the name would be too long. If two URLs in the same snapshot need a file and a directory at the same path (e.g., `/about` and `/about/team`), the second is skipped with a warning.

Caution: Paths on a web server are usually case-sensitive, but the default filesystems on MacOS and Windows are not, so `PATH/TO/file.txt` and `path/to/FILE.txt` can collide there. If `--wildcard` finds that the target directory is case-insensitive, it will log a warning and, within a single run, skip colliding files rather than overwrite them. A file saved by an earlier run can still be overwritten by a colliding file, unless you use `--no-clobber`.

To download only certain kinds of files, add `--filter`, which passes an archive.org [`filter`](https://github.com/internetarchive/wayback/blob/master/wayback-cdx-server/README.md#filtering) through. Snapshots must match the pattern *and* every filter. To negate a filter, start it with `!`, and quote it with single quotes so that your shell doesn't treat the `!` as a command (e.g., `--filter '!mimetype:text/html'`). The CDX API matches filters case-sensitively, but MIME types aren't case-sensitive, so waybackpack adds the `(?i)` (ignore case) flag to `mimetype` filters: `--filter mimetype:application/pdf` also matches `Application/PDF`. For instance, to download PDFs from one site during a given period:

```sh
waybackpack "example.com/**/*.pdf" -d ~/Downloads/example-pdfs --wildcard --filter mimetype:application/pdf --from-date 2005 --to-date 2008 --raw --delay 1 --no-clobber
```

That skips PDFs that the archive recorded under another MIME type (e.g., `application/octet-stream`), and revisits, which the CDX API lists with a MIME type of `warc/revisit`, so a PDF that didn't change during your date range could be missing if its last full capture came before the range. Drop `--filter` to rely on the pattern alone, or drop the `.pdf` from the pattern to rely on the MIME type alone.

Wildcard searches can match a very large number of snapshots. Use `--list` first to check how many there are (e.g., `| wc -l`), and narrow the search with a shorter date range, a longer fixed prefix in the pattern, or `--filter`. `--collapse` thins out the results, but it doesn't shorten the search: with `--wildcard`, results come back in several pages, and a live check showed that the CDX API drops a row at each page boundary when it collapses paged results. So with `--wildcard`, waybackpack fetches the uncollapsed results and applies `--collapse` itself, the same way (each row is dropped if its field, or the field's first N characters for `field:N`, matches the row before it).

## Installation

```
pip install waybackpack
```

## Usage

```
usage: waybackpack [-h] [--version] (-d DIR | --list) [--wildcard] [--raw]
                   [--root ROOT] [--from-date FROM_DATE] [--to-date TO_DATE]
                   [--user-agent USER_AGENT] [--follow-redirects]
                   [--uniques-only] [--collapse COLLAPSE] [--filter FILTER]
                   [--ignore-errors] [--max-retries MAX_RETRIES]
                   [--no-clobber] [--quiet] [--progress] [--delay DELAY]
                   [--delay-retry DELAY_RETRY]
                   url

positional arguments:
  url                   The URL of the resource you want to download.

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  -d DIR, --dir DIR     Directory to save the files. Will create this
                        directory if it doesn't already exist.
  --list                Instead of downloading the files, only print the list
                        of snapshots.
  --wildcard            Treat the URL as a wildcard pattern, and download the
                        archived snapshots whose URLs match it. '*' matches
                        within a path segment, '**' matches across segments,
                        '[abc]' matches any listed character, and '[!abc]' any
                        other. As in a URL, '?' starts the query string:
                        'example.com/**/*.pdf' matches PDFs with any query
                        string or none, 'example.com/view.php?id=*' matches
                        only URLs whose query string starts with 'id=', and a
                        trailing '?' matches only URLs without one. Matching
                        ignores case, the scheme, default ports, and a leading
                        'www.'. The host can't contain wildcards, except a
                        leading '*.', which matches the host itself and all
                        its subdomains. Snapshots that the CDX API lists with
                        a 3xx, 4xx, or 5xx status (redirects and errors) are
                        skipped; revisits of unchanged pages are kept. If the
                        URL contains no '*', '[', or '?', it is treated as an
                        ordinary URL, without that status filter. Quote the
                        URL so that your shell doesn't expand it. Caution: URL
                        paths are usually case-sensitive, but MacOS and
                        Windows filesystems usually aren't, so URLs that
                        differ only in capitalization can collide. If the
                        target directory is case-insensitive, waybackpack
                        warns you and, within a single run, skips colliding
                        files rather than overwriting them. See the README for
                        more caveats.
  --raw                 Fetch file in its original state, without any
                        processing by the Wayback Machine or waybackpack.
  --root ROOT           The root URL from which to serve snapshotted
                        resources. Default: 'https://web.archive.org'
  --from-date FROM_DATE
                        Timestamp-string indicating the earliest snapshot to
                        download. Should take the format YYYYMMDDhhss, though
                        you can omit as many of the trailing digits as you
                        like. E.g., '201501' is valid.
  --to-date TO_DATE     Timestamp-string indicating the latest snapshot to
                        download. Should take the format YYYYMMDDhhss, though
                        you can omit as many of the trailing digits as you
                        like. E.g., '201604' is valid.
  --user-agent USER_AGENT
                        The User-Agent header to send along with your requests
                        to the Wayback Machine. If possible, please include
                        the phrase 'waybackpack' and your email address. That
                        way, if you're battering their servers, they know who
                        to contact. Default: 'waybackpack'.
  --follow-redirects    Follow redirects.
  --uniques-only        Download only the first version of duplicate files.
  --collapse COLLAPSE   An archive.org `collapse` parameter. E.g., --collapse
                        timestamp:6 collapses results to at most one per
                        month. See here: https://github.com/internetarchive/wa
                        yback/blob/master/wayback-cdx-
                        server/README.md#collapsing
  --filter FILTER       An archive.org `filter` parameter. E.g., --filter
                        mimetype:application/pdf keeps only snapshots that the
                        archive recorded with that MIME type (ignoring case,
                        unlike other fields). Can be repeated; snapshots must
                        match every filter. With --wildcard,
                        !statuscode:[345].. is always added. See here: https:/
                        /github.com/internetarchive/wayback/blob/master/waybac
                        k-cdx-server/README.md#filtering
  --ignore-errors       Don't crash on non-HTTP errors e.g., the requests
                        library's ChunkedEncodingError. Instead, log error and
                        continue. See here:
                        https://github.com/jsvine/waybackpack/issues/19
  --max-retries MAX_RETRIES
                        How many times to try accessing content with 4XX or
                        5XX status code before skipping?
  --no-clobber          If a file is already present (and >0 filesize), don't
                        download it again.
  --quiet               Don't log progress to stderr.
  --progress            Print a progress bar. Mutes the default logging.
                        Requires `tqdm` to be installed.
  --delay DELAY         Sleep X seconds between each fetch, including between
                        pages of --wildcard search results.
  --delay-retry DELAY_RETRY
                        Sleep X seconds between each post-error retry.
```

## Support

Waypackback is written in pure Python, depends only on [`requests`](docs.python-requests.org), and should work wherever Python works. Requires Python 3.3+.

## Thanks

Many thanks to the following users for catching bugs, fixing typos, and proposing useful features:

- [@grawity](https://github.com/grawity)
- [@taggartk](https://github.com/taggartk)
- [@jtemplon](https://github.com/jtemplon)
- [@jwilk](https://github.com/jwilk)
- [@wumpus](https://github.com/wumpus)
- [@bevacqua](https://github.com/bevacqua)
- [@ErikBorra](https://github.com/ErikBorra)
- [@StevenACoffman](https://github.com/StevenACoffman)
- [@Hunter-Github](https://github.com/Hunter-Github)
- [@jeremybmerrill](https://github.com/jeremybmerrill)
- [@peci1](https://github.com/peci1)
- [@shijialee](https://github.com/shijialee)
- [@pmlandwehr](https://github.com/pmlandwehr)
