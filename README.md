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

To download every archived `.html` page on a site, use `--wildcard` (and quote the URL, so your shell doesn't expand it):

```sh
waybackpack "http://example.com/**/*.html" -d ~/Downloads/example-wayback --wildcard --from-date 2005 --to-date 2008 --delay 1 --no-clobber
```

In a pattern, `*` matches within a single path segment, `**` matches across segments, `?` matches one character, and `[abc]` matches any of the listed characters. Only snapshots the archive recorded with a `200` status are included. Each snapshot is saved under its own timestamp, host, and path, e.g., `20050101000000/example.com/some/page.html`.

Caution: Paths on a web server are usually case-sensitive, but the default filesystems on MacOS and Windows are not, so `PATH/TO/file.txt` and `path/to/FILE.txt` can collide there. If `--wildcard` finds that the target directory is case-insensitive, it will log a warning and skip (rather than overwrite) any colliding files.

## Installation

```
pip install waybackpack
```

## Usage

```
usage: waybackpack [-h] [--version] (-d DIR | --list) [--wildcard] [--raw]
                   [--root ROOT] [--from-date FROM_DATE] [--to-date TO_DATE]
                   [--user-agent USER_AGENT] [--follow-redirects]
                   [--uniques-only] [--collapse COLLAPSE] [--ignore-errors]
                   [--max-retries MAX_RETRIES] [--no-clobber] [--quiet]
                   [--progress] [--delay DELAY] [--delay-retry DELAY_RETRY]
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
  --wildcard            Treat the URL as a wildcard pattern, and download
                        every archived URL that matches it. '*' matches within
                        a path segment, '**' matches across segments, '?'
                        matches one character, and '[abc]' matches any listed
                        character. E.g., 'example.com/**/*.html' matches every
                        archived .html page on example.com, skipping any
                        snapshots whose status isn't 200. Quote the URL so
                        that your shell doesn't expand it. Caution: URL paths
                        are usually case-sensitive, but MacOS and Windows
                        filesystems usually aren't, so URLs that differ only
                        in capitalization can collide. If the target directory
                        is case-insensitive, waybackpack warns you and skips
                        (rather than overwrites) colliding files.
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
  --delay DELAY         Sleep X seconds between each fetch.
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
