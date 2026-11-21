import hashlib
import logging
import os
import platform
import time

from .asset import Asset
from .cdx import search
from .session import Session
from .settings import DEFAULT_ROOT
from .wildcard import is_case_insensitive

logger = logging.getLogger(__name__)

try:
    from urllib.parse import quote, urlparse
except ImportError:
    from urllib import quote

    from urlparse import urlparse

try:
    from tqdm.auto import tqdm

    has_tqdm = True
except ImportError:
    has_tqdm = False

psl = platform.system().lower()
if "windows" in psl or "cygwin" in psl:
    invalid_chars = '<>:"\\|?*'
elif "darwin" in psl:
    invalid_chars = ":"
else:
    invalid_chars = ""


def replace_invalid_chars(path, fallback_char="_"):
    path = "".join([fallback_char if c in invalid_chars else c for c in path])
    return os.path.join(
        *(
            fallback_char * len(part) if part in {os.curdir, os.pardir} else part
            for part in path.split("/")
        )
    )


MAX_FILENAME_BYTES = 255


def add_query(filename, query):
    # Percent-encoding leaves only characters that are safe in filenames. An
    # encoded query never contains "%23" (a query can't contain "#", and "%"
    # becomes "%25"), so "%3F%23" marks a hashed query unambiguously.
    name = filename + "%3F" + quote(query, safe="")
    if len(name.encode("utf-8")) > MAX_FILENAME_BYTES:
        digest = hashlib.sha1(query.encode("utf-8")).hexdigest()
        name = filename + "%3F%23" + digest
    return name


class Pack(object):
    def __init__(
        self,
        url,
        timestamps=None,
        uniques_only=False,
        session=None,
        snapshots=None,
        wildcard=False,
    ):

        self.url = url
        self.wildcard = wildcard
        prefix = "http://" if urlparse(url).scheme == "" else ""
        self.full_url = prefix + url
        self.parsed_url = urlparse(self.full_url)

        self.session = session or Session()

        if snapshots is None and timestamps is None:
            snapshots = search(
                url,
                uniques_only=uniques_only,
                session=self.session,
                wildcard=wildcard,
            )

        if snapshots is not None:
            self.timestamps = [snap["timestamp"] for snap in snapshots]
        else:
            self.timestamps = timestamps

        if wildcard:
            # Each snapshot may come from a different URL, so each asset
            # needs to remember its own.
            if snapshots is None:
                raise ValueError(
                    "wildcard=True requires `snapshots`, not `timestamps`."
                )
            self.assets = [Asset(s["original"], s["timestamp"]) for s in snapshots]
        else:
            self.assets = [Asset(self.url, ts) for ts in self.timestamps]

    def download_to(
        self,
        directory,
        raw=False,
        root=DEFAULT_ROOT,
        ignore_errors=False,
        no_clobber=False,
        progress=False,
        delay=0,
        fallback_char="_",
    ):

        if progress and not has_tqdm:
            raise Exception(
                "To print progress bars, you must have `tqdm` installed. To install: pip install tqdm."
            )

        case_insensitive = False
        if self.wildcard:
            case_insensitive = is_case_insensitive(directory)
            if case_insensitive:
                logger.warning(
                    "The filesystem at {0!r} is case-insensitive, but web "
                    "servers' paths often are not. If a wildcard match "
                    "includes URLs that differ only in capitalization "
                    "(e.g., /Foo.html and /foo.html) from the same snapshot "
                    "timestamp, only the first will be saved; the rest will "
                    "be skipped with a warning. To avoid this, download to a "
                    "case-sensitive filesystem.".format(directory)
                )
        written = set()

        for i, asset in enumerate(tqdm(self.assets) if progress else self.assets):
            parsed_url = urlparse(
                asset.original_url if self.wildcard else self.full_url
            )
            path_head, path_tail = os.path.split(parsed_url.path)
            if path_tail == "":
                path_tail = "index.html"

            filedir = os.path.join(
                directory,
                asset.timestamp,
                replace_invalid_chars(parsed_url.netloc, fallback_char),
                replace_invalid_chars(path_head.lstrip("/"), fallback_char),
            )

            filename = replace_invalid_chars(path_tail, fallback_char)
            if self.wildcard and parsed_url.query:
                # Different query strings are different URLs, so keep them
                # apart on disk.
                filename = add_query(filename, parsed_url.query)
            filepath = os.path.join(filedir, filename)

            if case_insensitive:
                key = filepath.lower()
                if key in written:
                    logger.warning(
                        "Skipping {0} @ {1}: would overwrite a file differing "
                        "only in capitalization ({2})".format(
                            asset.original_url, asset.timestamp, filepath
                        )
                    )
                    continue

            if no_clobber and (
                os.path.exists(filepath) and os.path.getsize(filepath) > 0
            ):
                continue

            if i > 0 and delay:
                logger.info("Sleeping {0} seconds".format(delay))
                time.sleep(delay)

            logger.info(
                "Fetching {0} @ {1}".format(asset.original_url, asset.timestamp)
            )

            try:
                content = asset.fetch(
                    session=self.session,
                    raw=raw,
                    root=root,
                    skip_redirects=self.wildcard,
                )

                if content is None:
                    continue

            except Exception as e:
                if ignore_errors is True:
                    ex_name = ".".join([e.__module__, e.__class__.__name__])
                    logger.warn(
                        "ERROR -- {0} @ {1} -- {2}: {3}".format(
                            asset.original_url, asset.timestamp, ex_name, e
                        )
                    )
                    continue
                else:
                    raise

            try:
                os.makedirs(filedir)
            except OSError:
                pass

            try:
                f = open(filepath, "wb")
            except OSError:
                # E.g., /about and /about/team in the same snapshot: one path
                # needs a file where the other needs a directory.
                if os.path.isdir(filepath) or not os.path.isdir(filedir):
                    logger.warning(
                        "Skipping {0} @ {1}: {2} clashes with a file or "
                        "directory already saved there".format(
                            asset.original_url, asset.timestamp, filepath
                        )
                    )
                    continue
                raise

            with f:
                logger.info("Writing to {0}\n".format(filepath))
                f.write(content)

            if case_insensitive:
                written.add(filepath.lower())
