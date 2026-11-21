import logging
import re
import time

import requests

from .session import Session
from .wildcard import WildcardPattern

logger = logging.getLogger(__name__)

SEARCH_URL = "https://web.archive.org/cdx/search/cdx"
CDX_PAGE_SIZE = 5000
CDX_TIMEOUT = 60
SKIP_STATUSES = "!statuscode:[345].."


class WaybackpackException(Exception):
    pass


# Errors raised while reading a response body, after the headers arrived.
READ_ERRORS = (
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def get_page(session, params, kwargs):
    # Session.get retries failed connections; this also retries a page whose
    # body is cut off, with the same --max-retries and --delay-retry.
    retries = 0
    while True:
        res = session.get(SEARCH_URL, params=params, **kwargs)
        if res is None or res.status_code != 200:
            return res, None
        try:
            return res, (res.json() if res.content.strip() else [])
        except READ_ERRORS:
            retries += 1
            if retries > session.max_retries:
                raise
            logger.info(
                "Error reading CDX response. Waiting {0} second(s) before retrying.".format(
                    session.delay_retry
                )
            )
            time.sleep(session.delay_retry)


MIMETYPE_FILTER = re.compile(r"^(!?mimetype:)(?!\(\?i\))")


def ignore_mimetype_case(filters):
    # The CDX API matches filters case-sensitively, but MIME types are
    # case-insensitive, so add the (?i) flag to mimetype filters.
    if filters is None:
        return None
    return [MIMETYPE_FILTER.sub(r"\1(?i)", f) for f in filters]


def collapse_rows(snapshots, collapse):
    # Like the CDX API's collapse: drop each row whose field (or its first N
    # characters, for "field:N") matches the row before it.
    for spec in collapse:
        field, sep, n = spec.partition(":")
        if snapshots and field not in snapshots[0]:
            raise WaybackpackException(
                "Can't collapse on {0!r}: CDX results have no such field.".format(field)
            )
        try:
            n = int(n) if sep else None
        except ValueError:
            raise WaybackpackException("Invalid --collapse value: {0!r}".format(spec))
        kept = []
        prev = object()
        for snap in snapshots:
            value = snap[field][:n]
            if value != prev:
                kept.append(snap)
            prev = value
        snapshots = kept
    return snapshots


def fail(msg, rows, resume_key):
    if rows:
        msg += (
            " Fetched {0} rows before failing; the last resume key was {1!r}.".format(
                len(rows), resume_key
            )
        )
    raise WaybackpackException(msg)


def search(
    url,
    from_date=None,
    to_date=None,
    uniques_only=False,
    collapse=None,
    session=None,
    wildcard=False,
    delay=0,
    filters=None,
):

    pattern = None
    if wildcard:
        try:
            pattern = WildcardPattern(url)
        except ValueError as e:
            raise WaybackpackException(str(e))
        if pattern.fragment is not None:
            logger.info(
                "Ignoring {0!r}: the CDX API ignores URL fragments.".format(
                    "#" + pattern.fragment
                )
            )
        if pattern.is_wildcard:
            # The CDX API only understands prefix/domain matches, so ask for
            # the coarse superset and apply the full pattern below.
            url = pattern.cdx_url
        else:
            logger.warning(
                "--wildcard was given, but the URL contains no wildcard "
                "characters (*, ?, [); treating it as an ordinary URL."
            )
            pattern = None

    params = {
        "url": url,
        "from": from_date,
        "to": to_date,
        "showDupeCount": "true",
        "output": "json",
        "collapse": collapse,
        "filter": ignore_mimetype_case(filters),
    }
    kwargs = {}
    if pattern is not None:
        # Wildcard queries can match a lot of snapshots, so fetch them in pages.
        # Skip redirects and errors, but keep revisits (status "-"): a live
        # check showed they download the earlier capture's content.
        params["filter"] = [SKIP_STATUSES] + (params["filter"] or [])
        params["limit"] = CDX_PAGE_SIZE
        params["showResumeKey"] = "true"
        kwargs["timeout"] = CDX_TIMEOUT
        # A live check showed that the CDX API drops a row at each page
        # boundary when collapse and paging are combined, so collapse below.
        params["collapse"] = None

    session = session or Session()
    fields = None
    rows = []
    seen_keys = set()
    resume_key = None
    while True:
        if seen_keys and delay:
            logger.info("Sleeping {0} seconds".format(delay))
            time.sleep(delay)
        try:
            res, cdx = get_page(session, params, kwargs)
        except READ_ERRORS:
            fail(
                "Lost the connection to the Wayback Machine CDX API while reading its response.",
                rows,
                resume_key,
            )
        except (ValueError, requests.exceptions.RequestException):
            fail(
                "Wayback Machine CDX API returned a response that isn't valid JSON. It may be offline, or may have cut off the response; try again later.",
                rows,
                resume_key,
            )
        if res is None:
            fail("Difficulty connecting to Wayback Machine CDX API", rows, resume_key)

        if res.status_code != 200:
            log_msg = 'CDX exception: "{0}"'
            logger.info(log_msg.format(res.content.decode("utf-8").strip()))
            if rows:
                fail(
                    "Wayback Machine CDX API failed partway through the results.",
                    rows,
                    resume_key,
                )
            return []

        # When there are more results, the API ends the page with an empty row,
        # then a row containing only the resume key.
        next_key = None
        if len(cdx) >= 2 and cdx[-2] == [] and len(cdx[-1]) == 1:
            next_key = cdx[-1][0]
            cdx = cdx[:-2]

        # The first row of the first page is the header. Later pages may or
        # may not repeat it, so drop their first row only if it matches.
        if cdx and fields is None:
            fields, cdx = cdx[0], cdx[1:]
        elif cdx and cdx[0] == fields:
            cdx = cdx[1:]
        rows += cdx
        if pattern is not None:
            logger.info("CDX returned {0} snapshots so far".format(len(rows)))

        if next_key is None or next_key in seen_keys:
            break
        resume_key = next_key
        seen_keys.add(resume_key)
        params = dict(params, resumeKey=resume_key)

    if not rows:
        if pattern is not None:
            logger.info("CDX returned no snapshots for {0!r}".format(url))
        return []
    snapshots = [dict(zip(fields, row)) for row in rows]
    if pattern is not None:
        # Defensive: drop any row repeated across pages, keeping the first.
        seen = set()
        unique = []
        for snap in snapshots:
            key = (snap.get("urlkey"), snap.get("timestamp"), snap.get("original"))
            if key not in seen:
                seen.add(key)
                unique.append(snap)
        if len(unique) < len(snapshots):
            logger.info(
                "Dropped {0} duplicate CDX rows".format(len(snapshots) - len(unique))
            )
        snapshots = unique
        if collapse:
            if isinstance(collapse, str):
                collapse = [collapse]
            snapshots = collapse_rows(snapshots, collapse)
        total = len(snapshots)
        snapshots = [s for s in snapshots if pattern.matches(s["original"])]
        logger.info(
            "CDX returned {0} snapshots for {1!r}; {2} match {3!r}".format(
                total, url, len(snapshots), pattern.pattern
            )
        )
    if uniques_only and pattern is not None:
        # Don't rely on the API's dupecount across pages: per URL, keep the
        # first snapshot of each digest, i.e., of each distinct content.
        seen = set()
        unique = []
        for snap in snapshots:
            key = (snap["urlkey"], snap["digest"])
            if key not in seen:
                seen.add(key)
                unique.append(snap)
        return unique
    if uniques_only:
        if len(snapshots) and "dupecount" not in snapshots[0]:
            raise WaybackpackException(
                "Wayback Machine CDX API not respecting showDupeCount=true; retry without --uniques-only."
            )
        return [s for s in snapshots if int(s["dupecount"]) == 0]
    else:
        return snapshots
