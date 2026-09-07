"""Read Cargo's complete display order without changing scraper state."""

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .constants import BASE_URL, HEADERS

HOMEPAGE_URL = BASE_URL.rstrip("/") + "/"
THUMBNAIL_URL = urljoin(HOMEPAGE_URL, "designs/escher/thumb-pagination.php")
MAX_PROJECTS = 5000
_PROJECT_ID = re.compile(r"[1-9][0-9]{0,19}")
_PR_LIST_DECLARATION = re.compile(r"\bvar\s+pr_list\s*=")
_PR_LIST_ARRAY = re.compile(r"\s*new\s+Array\s*\(([^;]*)\)\s*;", re.DOTALL)
_QUOTED_ID = re.compile(r"(['\"])([1-9][0-9]{0,19})\1")


class SiteOrderError(RuntimeError):
    """The website order could not be verified as complete and consistent."""


def canonical_work_url(url: str) -> str:
    """Return a same-site artwork identity without editing the stored URL.

    HTTP/HTTPS, www, query strings, fragments and trailing slashes do not change
    identity. Path case is significant. Invalid URLs are never guessed.
    """
    if not isinstance(url, str) or not url or url != url.strip():
        raise SiteOrderError(
            "Artwork URLs must be nonempty strings without surrounding whitespace."
        )
    if any(character.isspace() or ord(character) < 32 for character in url) or "\\" in url:
        raise SiteOrderError("Artwork URL contains invalid whitespace or a backslash.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise SiteOrderError("Artwork URL is malformed.") from exc
    if (
        parts.scheme.lower() not in {"http", "https"}
        or parts.hostname not in {"eventstructure.com", "www.eventstructure.com"}
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 80 if parts.scheme.lower() == "http" else 443}
    ):
        raise SiteOrderError("Artwork URL must use HTTP or HTTPS on eventstructure.com.")
    path = parts.path.rstrip("/")
    if (
        not path
        or path.startswith("//")
        or any(segment in {".", ".."} for segment in path.split("/"))
    ):
        raise SiteOrderError("Artwork URL must identify a project page, not the homepage.")
    return urlunsplit(("https", "eventstructure.com", path, "", ""))


def _project_ids(soup: BeautifulSoup) -> List[str]:
    declarations = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        for declaration in _PR_LIST_DECLARATION.finditer(text):
            declarations.append(text[declaration.end() :])
    if len(declarations) != 1:
        raise SiteOrderError("Homepage must contain exactly one pr_list display-order declaration.")
    match = _PR_LIST_ARRAY.match(declarations[0])
    if match is None:
        raise SiteOrderError("Homepage pr_list is not a supported numeric ID array.")
    tokens = match.group(1).split(",")
    if not 1 <= len(tokens) <= MAX_PROJECTS:
        raise SiteOrderError(
            f"Homepage pr_list must contain between 1 and {MAX_PROJECTS} project IDs."
        )
    ids = []
    for token in tokens:
        item = _QUOTED_ID.fullmatch(token.strip())
        if item is None:
            raise SiteOrderError("Homepage pr_list may contain only quoted numeric project IDs.")
        ids.append(item.group(2))
    if len(set(ids)) != len(ids):
        raise SiteOrderError("Homepage pr_list contains duplicate project IDs.")
    return ids


def _thumbnails(soup: BeautifulSoup, context: str) -> List[Tuple[str, str]]:
    thumbnails = soup.select(".project_thumb")
    if not thumbnails or len(thumbnails) > MAX_PROJECTS:
        raise SiteOrderError(f"{context} does not contain a valid project thumbnail list.")
    result = []
    for thumbnail in thumbnails:
        project_id = thumbnail.get("name")
        if not isinstance(project_id, str) or _PROJECT_ID.fullmatch(project_id) is None:
            raise SiteOrderError(f"{context} contains a thumbnail without a valid project ID.")
        # Each card also contains category/navigation links. Only its project-ID
        # anchor is authoritative, so those links cannot become artwork entries.
        links = thumbnail.find_all("a", id=f"p{project_id}", href=True)
        if len(links) != 1 or not isinstance(links[0].get("href"), str):
            raise SiteOrderError(f"{context} thumbnail {project_id} has no unique project link.")
        href = links[0]["href"]
        if not href or href.startswith(("#", "?")) or href != href.strip():
            raise SiteOrderError(f"{context} thumbnail {project_id} has an invalid project link.")
        url = canonical_work_url(urljoin(HOMEPAGE_URL, href))
        result.append((project_id, url))
    if len({project_id for project_id, _ in result}) != len(result):
        raise SiteOrderError(f"{context} contains duplicate project IDs.")
    if len({url for _, url in result}) != len(result):
        raise SiteOrderError(f"{context} contains duplicate artwork URLs.")
    return result


def _response_html(response: requests.Response, context: str) -> BeautifulSoup:
    if response.status_code != 200:
        raise SiteOrderError(
            f"{context} request returned HTTP {response.status_code}; website order is unavailable."
        )
    if not response.content.strip():
        raise SiteOrderError(f"{context} returned an empty response.")
    return BeautifulSoup(response.content, "html.parser")


def fetch_website_order(
    *, session: Optional[requests.Session] = None, timeout: Tuple[int, int] = (5, 20)
) -> List[str]:
    """Fetch and verify the complete homepage order in exactly two requests.

    The first response supplies pr_list and a visible prefix; Cargo's read-only
    thumbnail pagination endpoint supplies all project URLs. Missing, partial or
    inconsistent evidence raises SiteOrderError. No sitemap or AI calls are made.
    """
    client = session if session is not None else requests.Session()
    try:
        homepage = _response_html(
            client.get(HOMEPAGE_URL, headers=HEADERS, timeout=timeout, allow_redirects=False),
            "Homepage",
        )
        ids = _project_ids(homepage)
        visible = _thumbnails(homepage, "Homepage")
        if [project_id for project_id, _ in visible] != ids[: len(visible)]:
            raise SiteOrderError("Homepage thumbnails do not match the pr_list prefix.")
        site_inputs = homepage.select('input#url[type="hidden"]')
        if len(site_inputs) != 1:
            raise SiteOrderError("Homepage is missing its unique Cargo site identifier.")
        site_id = site_inputs[0].get("value")
        if not isinstance(site_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", site_id) is None:
            raise SiteOrderError("Homepage Cargo site identifier is invalid.")
        thumbnails = _response_html(
            client.post(
                THUMBNAIL_URL,
                data={
                    "url": site_id,
                    "startRow": 0,
                    "limit": len(ids),
                    "paginate": "true",
                    "cat": "",
                },
                headers=HEADERS,
                timeout=timeout,
                allow_redirects=False,
            ),
            "Complete thumbnail list",
        )
        complete = _thumbnails(thumbnails, "Complete thumbnail list")
        if [project_id for project_id, _ in complete] != ids:
            raise SiteOrderError(
                "Complete thumbnail IDs differ from pr_list: the response is incomplete or the website order changed."
            )
        if complete[: len(visible)] != visible:
            raise SiteOrderError(
                "Visible project URLs changed between the homepage and thumbnail responses."
            )
        return [url for _, url in complete]
    except requests.RequestException as exc:
        raise SiteOrderError(f"Website order request failed ({type(exc).__name__}).") from exc
    finally:
        if session is None:
            client.close()


def sort_works_by_website_order(
    works: Iterable[Dict[str, Any]], ordered_urls: Iterable[str]
) -> List[Dict[str, Any]]:
    """Return original records in site order, keeping unknown records stable.

    This does not create, drop, copy or edit individual records. The caller must
    obtain a verified complete order; empty, invalid and duplicate ranks fail.
    """
    if isinstance(ordered_urls, (str, bytes)):
        raise SiteOrderError("Website order must be a nonempty URL list.")
    urls = [canonical_work_url(url) for url in ordered_urls]
    if not 1 <= len(urls) <= MAX_PROJECTS or len(set(urls)) != len(urls):
        raise SiteOrderError("Website order must contain a nonempty, unique list of artwork URLs.")
    ranks = {url: rank for rank, url in enumerate(urls)}

    def rank(record: Dict[str, Any]) -> int:
        try:
            return ranks.get(canonical_work_url(record.get("url")), len(ranks))
        except SiteOrderError:
            return len(ranks)

    return sorted(works, key=rank)
