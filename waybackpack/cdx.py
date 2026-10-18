import logging

from .session import Session
from .wildcard import WildcardPattern

logger = logging.getLogger(__name__)

SEARCH_URL = "https://web.archive.org/cdx/search/cdx"


class WaybackpackException(Exception):
    pass


def search(
    url,
    from_date=None,
    to_date=None,
    uniques_only=False,
    collapse=None,
    session=None,
    wildcard=False,
):

    pattern = None
    if wildcard:
        try:
            pattern = WildcardPattern(url)
        except ValueError as e:
            raise WaybackpackException(str(e))
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

    session = session or Session()
    res = session.get(
        SEARCH_URL,
        params={
            "url": url,
            "from": from_date,
            "to": to_date,
            "showDupeCount": "true",
            "output": "json",
            "collapse": collapse,
        },
    )
    if res is None:
        raise WaybackpackException("Difficulty connecting to Wayback Machine CDX API")

    if res.status_code == 200:
        cdx = res.json()

    else:
        log_msg = 'CDX exception: "{0}"'
        logger.info(log_msg.format(res.content.decode("utf-8").strip()))
        return []

    if len(cdx) < 2:
        return []
    fields = cdx[0]
    snapshots = [dict(zip(fields, row)) for row in cdx[1:]]
    if pattern is not None:
        snapshots = [s for s in snapshots if pattern.matches(s["original"])]
    if uniques_only:
        if len(snapshots) and "dupecount" not in snapshots[0]:
            raise WaybackpackException(
                "Wayback Machine CDX API not respecting showDupeCount=true; retry without --uniques-only."
            )
        return [s for s in snapshots if int(s["dupecount"]) == 0]
    else:
        return snapshots
