"""Complete display-order discovery and stable, nonmutating artwork sorting."""

import copy
from unittest.mock import Mock

import pytest
import requests

from scraper.constants import HEADERS
from scraper.site_order import (
    HOMEPAGE_URL,
    MAX_PROJECTS,
    THUMBNAIL_URL,
    SiteOrderError,
    canonical_work_url,
    fetch_website_order,
    sort_works_by_website_order,
)


def thumbnail(project_id, href):
    return (
        f'<div class="project_thumb" name="{project_id}">'
        '<a href="/filter/2026">Navigation must not enter the artwork list</a>'
        f'<a id="p{project_id}" href="{href}"><span>Artwork</span></a></div>'
    )


def homepage(ids=("31", "22", "13"), visible=None, declaration=None):
    if declaration is None:
        declaration = "var pr_list = new Array(" + ",".join(f'"{item}"' for item in ids) + ");"
    if visible is None:
        visible = thumbnail(ids[0], "/First") if ids else ""
    return (
        f"<html><script>{declaration}</script>"
        '<input type="hidden" id="url" value="es">'
        '<nav><a href="/about">About</a></nav>' + visible + "</html>"
    )


def response(html, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = html.encode("utf-8")
    result.encoding = "utf-8"
    return result


def session_with(home=None, thumbs=None):
    session = Mock(spec=requests.Session)
    session.get.return_value = response(home if home is not None else homepage())
    session.post.return_value = response(
        thumbs
        if thumbs is not None
        else "".join(
            thumbnail(project_id, href)
            for project_id, href in [("31", "/First"), ("22", "/Second"), ("13", "/Third")]
        )
    )
    return session


def test_fetches_every_project_in_one_pagination_request_without_navigation_links():
    session = session_with()
    assert fetch_website_order(session=session, timeout=(2, 7)) == [
        "https://eventstructure.com/First",
        "https://eventstructure.com/Second",
        "https://eventstructure.com/Third",
    ]
    session.get.assert_called_once_with(
        HOMEPAGE_URL, headers=HEADERS, timeout=(2, 7), allow_redirects=False
    )
    session.post.assert_called_once_with(
        THUMBNAIL_URL,
        data={"url": "es", "startRow": 0, "limit": 3, "paginate": "true", "cat": ""},
        headers=HEADERS,
        timeout=(2, 7),
        allow_redirects=False,
    )
    session.close.assert_not_called()
    assert len(session.method_calls) == 2


@pytest.mark.parametrize(
    "declaration",
    [
        "",
        "var pr_list = [];",
        "var pr_list = new Array();",
        'var pr_list = new Array("31", "31");',
        'var pr_list = new Array("31", "22x");',
        'var pr_list = new Array("31", "");',
        'var pr_list = new Array("31", "22",);',
        'var pr_list = new Array("31", alert("do not execute"));',
        'var pr_list = new Array("31" + "22");',
        'var pr_list = new Array("31"); var pr_list = new Array("22");',
    ],
)
def test_rejects_missing_empty_duplicate_or_executable_order_without_post(declaration):
    session = session_with(home=homepage(declaration=declaration))
    with pytest.raises(SiteOrderError, match="pr_list"):
        fetch_website_order(session=session)
    session.post.assert_not_called()


def test_rejects_unreasonably_large_order():
    ids = tuple(str(index) for index in range(1, MAX_PROJECTS + 2))
    session = session_with(home=homepage(ids))
    with pytest.raises(SiteOrderError, match="between"):
        fetch_website_order(session=session)
    session.post.assert_not_called()


@pytest.mark.parametrize(
    "visible",
    [
        "",
        thumbnail("22", "/Second"),
        thumbnail("31", "/First") + thumbnail("13", "/Third"),
        thumbnail("31", "/First") + thumbnail("31", "/First"),
        '<div class="project_thumb"><a href="/First">Missing ID</a></div>',
    ],
)
def test_requires_visible_homepage_thumbnails_to_be_a_valid_order_prefix(visible):
    session = session_with(home=homepage(visible=visible))
    with pytest.raises(SiteOrderError, match="Homepage"):
        fetch_website_order(session=session)
    session.post.assert_not_called()


@pytest.mark.parametrize(
    "site_input",
    [
        "",
        '<input id="url" type="hidden" value="">',
        '<input id="url" type="hidden" value="../other">',
        '<input id="url" type="hidden" value="es"><input id="url" type="hidden" value="other">',
    ],
)
def test_does_not_guess_the_cargo_site_identifier(site_input):
    home = homepage().replace('<input type="hidden" id="url" value="es">', site_input)
    session = session_with(home=home)
    with pytest.raises(SiteOrderError, match="site identifier"):
        fetch_website_order(session=session)
    session.post.assert_not_called()


@pytest.mark.parametrize(
    "thumbs",
    [
        "",
        "Complete",
        "<html><h1>Service unavailable</h1></html>",
        thumbnail("31", "/First"),
        thumbnail("31", "/First") + thumbnail("13", "/Third") + thumbnail("22", "/Second"),
        thumbnail("31", "/First") + thumbnail("22", "/Second") + thumbnail("22", "/Duplicate"),
        thumbnail("31", "/First")
        + thumbnail("22", "/First/?duplicate=yes")
        + thumbnail("13", "/Third"),
        thumbnail("31", "/Changed-Slug") + thumbnail("22", "/Second") + thumbnail("13", "/Third"),
        thumbnail("31", "/First")
        + thumbnail("22", "https://elsewhere.example/Second")
        + thumbnail("13", "/Third"),
        thumbnail("31", "/First")
        + thumbnail("22", "javascript:alert(1)")
        + thumbnail("13", "/Third"),
        thumbnail("31", "/First")
        + thumbnail("22", "/Second")
        + '<div class="project_thumb" name="13"><a',
    ],
)
def test_rejects_error_pages_truncation_reordering_duplicates_and_invalid_links(thumbs):
    with pytest.raises(SiteOrderError):
        fetch_website_order(session=session_with(thumbs=thumbs))


@pytest.mark.parametrize(
    "method,status", [("get", 503), ("post", 503), ("get", 302), ("post", 403)]
)
def test_http_errors_and_redirects_never_yield_a_partial_order(method, status):
    session = session_with()
    getattr(session, method).return_value.status_code = status
    with pytest.raises(SiteOrderError, match=f"HTTP {status}"):
        fetch_website_order(session=session)
    if method == "get":
        session.post.assert_not_called()


def test_owned_session_closes_on_network_failure(monkeypatch):
    session = session_with()
    session.get.side_effect = requests.Timeout("network fixture")
    monkeypatch.setattr(requests, "Session", lambda: session)
    with pytest.raises(SiteOrderError, match="request failed.*Timeout"):
        fetch_website_order()
    session.close.assert_called_once_with()
    session.post.assert_not_called()


def test_fetch_normalizes_project_id_links_without_changing_path_case():
    session = session_with(
        home=homepage(
            ("31",), visible=thumbnail("31", "http://www.eventstructure.com/CaseSensitive/?a=1#old")
        ),
        thumbs=thumbnail("31", "https://eventstructure.com/CaseSensitive/#new"),
    )
    assert fetch_website_order(session=session) == ["https://eventstructure.com/CaseSensitive"]


def test_sort_is_stable_and_preserves_every_original_record_and_nested_value():
    works = [
        {"url": "https://eventstructure.com/Unknown", "images": ["keep"]},
        {"url": "https://eventstructure.com/Second", "title": "Second"},
        {"url": "https://eventstructure.com/first", "title": "Different path case"},
        {"url": "http://www.eventstructure.com/First/?query=1#part", "title": "First"},
        {"url": "https://other.example/First", "title": "External"},
        {"url": "https://eventstructure.com/First/", "title": "Same identity kept"},
        {"title": "Missing URL kept"},
    ]
    before = copy.deepcopy(works)
    order = [
        "https://eventstructure.com/First",
        "https://eventstructure.com/Second",
        "https://eventstructure.com/NotInDataset",
    ]
    result = sort_works_by_website_order(works, order)
    assert result == [works[index] for index in [3, 5, 1, 0, 2, 4, 6]]
    assert all(record is works[index] for record, index in zip(result, [3, 5, 1, 0, 2, 4, 6]))
    assert works == before
    assert order == [
        "https://eventstructure.com/First",
        "https://eventstructure.com/Second",
        "https://eventstructure.com/NotInDataset",
    ]
    assert result is not works


@pytest.mark.parametrize(
    "order",
    [
        [],
        "https://eventstructure.com/First",
        ["https://eventstructure.com/First", "http://www.eventstructure.com/First/?a=1#duplicate"],
        ["https://other.example/First"],
        [None],
    ],
)
def test_sort_rejects_empty_invalid_or_duplicate_order(order):
    with pytest.raises(SiteOrderError):
        sort_works_by_website_order([], order)


@pytest.mark.parametrize(
    "url",
    [
        "https://eventstructure.com/",
        "https://eventstructure.com.evil.example/First",
        "https://user:password@eventstructure.com/First",
        "https://eventstructure.com:444/First",
        "file:///First",
        "https://eventstructure.com/First Second",
        "https://eventstructure.com/../First",
        "https://eventstructure.com\\@elsewhere.example/First",
    ],
)
def test_canonical_identity_rejects_invalid_artwork_urls(url):
    with pytest.raises(SiteOrderError):
        canonical_work_url(url)
