"""Opt-in real Chromium tests: RUN_BROWSER_TESTS=1 pytest -q.

Install .[test,browser] and Chromium (or set CHAINLINK_BROWSER_EXECUTABLE).
The server uses the same isolated database fixtures as API tests.
"""

import os
import re
import shutil
import socket
import threading
import time
from copy import deepcopy
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

import pytest
import uvicorn
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import COOKIE, create_account, digest
from app.models import CompletedRound, WebSession

if os.getenv("RUN_BROWSER_TESTS") != "1":
    pytest.skip(
        "Set RUN_BROWSER_TESTS=1 for browser integration tests", allow_module_level=True
    )

playwright = pytest.importorskip("playwright.sync_api")
from app.main import app


@pytest.fixture
def live_server(client):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [sock]}, daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        try:
            assert server.started, "Test HTTP server failed to start"
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=5)


@pytest.fixture
def browser():
    with playwright.sync_playwright() as instance:
        executable = os.getenv("CHAINLINK_BROWSER_EXECUTABLE") or shutil.which(
            "chromium"
        )
        options = {"headless": True, "args": ["--no-sandbox"]}
        if executable:
            options["executable_path"] = executable
        browser = instance.chromium.launch(**options)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page()
    page.set_default_timeout(5000)
    page.set_default_navigation_timeout(10000)
    yield page
    page.close()


def test_dashboard_navigation_and_health(page, live_server):
    page.goto(live_server)
    playwright.expect(
        page.get_by_role("heading", name="Dashboard", exact=True)
    ).to_be_visible()
    playwright.expect(page.get_by_text("● API reachable")).to_be_visible()
    page.get_by_role("navigation", name="Main navigation").get_by_role(
        "link", name="Players", exact=False
    ).click()
    playwright.expect(
        page.get_by_role("heading", name="Disc golf is better together.")
    ).to_be_visible()
    playwright.expect(page.get_by_text("COMING SOON", exact=True)).to_be_visible()
    page.get_by_role("navigation", name="Main navigation").get_by_role(
        "link", name="Round History", exact=True
    ).click()
    playwright.expect(
        page.get_by_text("Sign in to view Round History", exact=True)
    ).to_be_visible()
    assert page.locator('[aria-current="page"]').get_attribute("href") == "#rounds"
    assert page.locator("#main").evaluate("node => node === document.activeElement")


def test_empty_error_retry_and_loading(page, live_server):
    def fail(route):
        route.fulfill(status=503, json={"detail": "Unavailable"})

    page.route("**/v1/courses?*", fail)
    page.goto(live_server + "/#courses")
    playwright.expect(
        page.get_by_role("heading", name="Couldn’t load the catalog.")
    ).to_be_visible()
    page.unroute("**/v1/courses?*", fail)
    page.get_by_role("button", name="Try again").click()
    playwright.expect(
        page.get_by_role("heading", name="The fairway is wide open.")
    ).to_be_visible()
    with page.expect_request("**/v1/courses?*"):
        page.get_by_role("button", name="Refresh", exact=True).click()
    playwright.expect(page.get_by_role("button", name="Next →")).to_be_disabled()
    # Hold a response to verify loading and navigation cancellation.
    page.route("**/v1/courses?*", lambda route: None)
    page.get_by_role("button", name="Refresh", exact=True).click()
    playwright.expect(
        page.get_by_role("heading", name="Loading courses…")
    ).to_be_visible()
    page.get_by_role("navigation", name="Main navigation").get_by_role(
        "link", name="Dashboard", exact=True
    ).click()
    playwright.expect(
        page.get_by_role("heading", name="Dashboard", exact=True)
    ).to_be_visible()


def test_pagination(page, live_server, client):
    for index in range(14):
        assert (
            client.post("/v1/courses", json={"name": f"Course {index:02}"}).status_code
            == 201
        )
    page.goto(live_server + "/#courses")
    playwright.expect(page.locator(".course-card")).to_have_count(12)
    playwright.expect(
        page.get_by_role("button", name="Previous", exact=False)
    ).to_be_disabled()
    page.get_by_role("button", name="Next →").click()
    playwright.expect(page.locator(".course-card")).to_have_count(2)
    playwright.expect(
        page.get_by_role("heading", name="Course 12", exact=True)
    ).to_be_visible()
    playwright.expect(page.get_by_role("button", name="Next →")).to_be_disabled()
    page.get_by_role("button", name="Previous", exact=False).click()
    playwright.expect(page.locator(".course-card")).to_have_count(12)
    page.goto(live_server)
    playwright.expect(page.locator("#catalog-count")).to_have_text("12+")
    playwright.expect(
        page.get_by_text("More courses available · Browse the catalog", exact=True)
    ).to_be_visible()


@pytest.mark.parametrize("width", [390, 834, 1440])
def test_real_graph_safe_rendering_and_responsive_layout(
    page, live_server, graph, client, width
):
    payload = '<img src=x onerror="window.catalogExecuted=true">'
    course = client.post(
        "/v1/courses",
        json={"name": payload, "description": "<script>alert(1)</script>"},
    ).json()
    writes = []
    external = []
    page.on(
        "request",
        lambda request: (
            writes.append(request.method) if request.method != "GET" else None
        ),
    )
    page.on(
        "request",
        lambda request: (
            external.append(request.url)
            if not request.url.startswith(live_server)
            else None
        ),
    )
    page.set_viewport_size({"width": width, "height": 950})
    page.goto(live_server + f"/#courses/{graph['id']}")
    playwright.expect(
        page.get_by_role("heading", name="River Park", exact=True)
    ).to_be_visible()
    playwright.expect(page.get_by_text("250 ft", exact=True)).to_be_visible()
    assert page.locator("details").count() == 1
    assert page.locator("tbody tr").count() == 3
    assert page.locator(".default-label", has_text="Default").count() == 2
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.goto(live_server + f"/#layouts/{course['id']}")
    playwright.expect(
        page.get_by_role("heading", name=payload, exact=True)
    ).to_be_visible()
    playwright.expect(
        page.get_by_text("<script>alert(1)</script>", exact=True)
    ).to_be_visible()
    assert page.evaluate("window.catalogExecuted === undefined")
    assert page.locator("#view img").count() == 0
    playwright.expect(
        page.get_by_role("heading", name="A course with room to grow.")
    ).to_be_visible()
    assert not writes
    assert not external


def test_health_failure_and_recovery(page, live_server):
    page.route("**/health", lambda route: route.abort())
    page.goto(live_server)
    playwright.expect(page.get_by_text("○ API unreachable")).to_be_visible()
    page.unroute("**/health")
    page.get_by_role("button", name="Check again").click()
    playwright.expect(page.get_by_text("● API reachable")).to_be_visible()


def test_missing_course_and_layout_navigation(page, live_server, graph):
    page.goto(live_server + "/#courses/00000000-0000-0000-0000-000000000000")
    playwright.expect(
        page.get_by_role("heading", name="Course not found", exact=True)
    ).to_be_visible()
    page.get_by_role("navigation", name="Main navigation").get_by_role(
        "link", name="Layouts", exact=True
    ).click()
    page.get_by_role("link", name="Explore layouts", exact=False).click()
    playwright.expect(
        page.get_by_role("heading", name="River Park", exact=True)
    ).to_be_visible()


def test_dashboard_course_selection_and_scoped_counts(page, live_server, graph, client):
    other = client.post("/v1/courses", json={"name": "Woodland"}).json()
    page.goto(live_server)
    playwright.expect(page.locator("#catalog-count")).to_have_text("2")
    playwright.expect(page.locator("#layout-count")).to_have_text("1")
    playwright.expect(
        page.get_by_text("2 holes · Default par 6", exact=True)
    ).to_be_visible()
    page.get_by_label("Selected course").select_option(other["id"])
    playwright.expect(page.locator("#layout-count")).to_have_text("0")
    playwright.expect(
        page.get_by_role("heading", name="No layouts yet")
    ).to_be_visible()
    playwright.expect(page.get_by_text("In Woodland", exact=True)).to_be_visible()
    assert page.locator(".roadmap button").count() == 0
    playwright.expect(page.locator('.roadmap a[href="#rounds"]')).to_be_visible()
    playwright.expect(page.locator('.roadmap a[href="#statistics"]')).to_be_visible()
    for name in ("Players", "Android sync"):
        playwright.expect(
            page.locator(".roadmap").get_by_text(name, exact=True)
        ).to_be_visible()


def test_dashboard_empty_and_catalog_retry(page, live_server):
    page.route(
        "**/v1/courses?*",
        lambda route: route.fulfill(status=503, json={"detail": "Unavailable"}),
    )
    page.goto(live_server)
    playwright.expect(page.get_by_text("● API reachable")).to_be_visible()
    playwright.expect(
        page.get_by_role("heading", name="Couldn’t load the catalog.")
    ).to_be_visible()
    playwright.expect(page.locator("#catalog-count")).to_have_text("—")
    page.unroute("**/v1/courses?*")
    page.get_by_role("button", name="Try again").click()
    playwright.expect(page.locator("#catalog-count")).to_have_text("0")
    playwright.expect(page.locator("#layout-count")).to_have_text("—")
    playwright.expect(
        page.get_by_role("heading", name="Your catalog starts here.")
    ).to_be_visible()
    playwright.expect(
        page.get_by_role("heading", name="No course selected")
    ).to_be_visible()


def test_dashboard_layout_failure_retry(page, live_server, graph):
    pattern = "**/v1/courses/*/graph"
    page.route(
        pattern, lambda route: route.fulfill(status=503, json={"detail": "Unavailable"})
    )
    page.goto(live_server)
    playwright.expect(page.locator("#catalog-count")).to_have_text("1")
    playwright.expect(
        page.get_by_role("heading", name="Couldn’t load layouts.")
    ).to_be_visible()
    playwright.expect(page.locator("#layout-count")).to_have_text("—")
    page.unroute(pattern)
    page.get_by_role("button", name="Try again").click()
    playwright.expect(page.locator("#layout-count")).to_have_text("1")


@pytest.mark.parametrize("width", [390, 834, 1440])
def test_midnight_red_dashboard_preview(
    page, live_server, graph, client, layout_payload, width
):
    for name, description in [
        ("Summit Pines", "Wooded fairways. A different line on every hole."),
        ("Westwood Disc Golf", "Open drives and technical approaches."),
        ("Willow Creek", "Follow the creek through the local course."),
    ]:
        assert (
            client.post(
                "/v1/courses", json={"name": name, "description": description}
            ).status_code
            == 201
        )
    layout_payload["name"] = "Long tees"
    assert (
        client.post(
            f"/v1/courses/{graph['id']}/layouts", json=layout_payload
        ).status_code
        == 201
    )
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(live_server)
    playwright.expect(page.locator("#catalog-count")).to_have_text("4")
    playwright.expect(page.locator("#layout-count")).to_have_text("2")
    playwright.expect(page.get_by_text("● API reachable")).to_be_visible()
    artwork = page.get_by_alt_text("ChainLink Midnight Red disc golf basket artwork")
    playwright.expect(artwork).to_be_visible()
    assert artwork.evaluate("image => image.complete && image.naturalWidth > 0")
    assert artwork.evaluate(
        "image => Math.abs(image.clientWidth / image.clientHeight - 1134 / 1387) < 0.015"
    )
    assert artwork.evaluate("image => image.clientWidth <= 96")
    assert (
        page.locator(".metrics-grid").bounding_box()["y"] < artwork.bounding_box()["y"]
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    colors = page.evaluate("""() => {
        const styles = getComputedStyle(document.documentElement);
        return ['--bg', '--accent', '--surface', '--text', '--muted', '--line'].map(name => styles.getPropertyValue(name).trim().toLowerCase());
    }""")
    assert colors == ["#101014", "#e53935", "#1c1c22", "#ffffff", "#b0b0b8", "#50505a"]
    page.screenshot(
        path=str(Path(gettempdir()) / f"chainlink-midnight-red-{width}.png"),
        full_page=True,
        animations="disabled",
    )
    page.locator(".layout-preview").filter(has_text="Main").click()
    playwright.expect(page.locator("details[open] summary")).to_contain_text("Main")
    assert page.locator("details[open]").count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(
        path=str(Path(gettempdir()) / f"chainlink-midnight-red-layout-{width}.png"),
        full_page=True,
        animations="disabled",
    )
    page.goto(live_server)
    playwright.expect(page.locator("#layout-count")).to_have_text("2")
    page.emulate_media(reduced_motion="reduce")
    assert (
        page.locator(".heading-action").evaluate(
            "node => getComputedStyle(node).transitionDuration"
        )
        == "0s"
    )
    # Keyboard skip navigation remains usable after the visual redesign.
    page.reload()
    page.keyboard.press("Tab")
    playwright.expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
    page.keyboard.press("Enter")
    playwright.expect(page.locator("#main")).to_be_focused()


def test_dashboard_does_not_sum_incomplete_defaults(page, live_server, graph):
    graph["layouts"][0]["holes"][1]["default"] = None
    page.route("**/v1/courses/*/graph", lambda route: route.fulfill(json=graph))
    page.goto(live_server)
    playwright.expect(
        page.get_by_text("2 holes · Defaults incomplete", exact=True)
    ).to_be_visible()
    assert page.locator(".layout-preview", has_text="Default par").count() == 0


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_authentication_form_desktop_and_mobile(page, live_server, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(live_server)
    page.get_by_role("button", name="Sign in", exact=True).click()
    dialog = page.get_by_role("dialog")
    playwright.expect(dialog).to_be_visible()
    page.screenshot(path=f"/tmp/chainlink-login-{width}.png")
    page.get_by_label("Username", exact=True).fill("test-admin")
    page.get_by_label("Password", exact=True).fill("incorrect")
    dialog.get_by_role("button", name="Sign in", exact=True).click()
    playwright.expect(page.locator("#login-message")).to_contain_text(
        "Unable to sign in"
    )
    page.get_by_label("Password", exact=True).fill("test-password-123")
    dialog.get_by_role("button", name="Sign in", exact=True).click()
    playwright.expect(dialog).not_to_be_visible()
    playwright.expect(page.locator("#account-name")).to_have_text("test-admin")
    assert page.evaluate("localStorage.length") == 0
    page.reload()
    playwright.expect(page.locator("#account-name")).to_have_text("test-admin")
    page.get_by_role("button", name="Sign out", exact=True).click()
    playwright.expect(
        page.get_by_role("button", name="Sign in", exact=True)
    ).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.fixture
def history_payload():
    return {
        "id": str(uuid4()),
        "completed_at": "2026-10-18T12:30:00Z",
        "course_name": '<img src=x onerror="window.roundExecuted=true">',
        "layout_name": "Historic Main",
        "holes": [
            {"number": n, "par": 3, "tee_name": "Short", "basket_name": "A"}
            for n in range(1, 5)
        ],
        "participants": [
            {
                "id": str(uuid4()),
                "name": name,
                "scores": [
                    {"hole_number": n, "strokes": strokes[n - 1]} for n in range(1, 5)
                ],
            }
            for name, strokes in [
                ("Alice", [2, 3, 4, 5]),
                ("Bob", [1, 2, 3, 4]),
                ("<script>Guest</script>", [3, 3, 3, 3]),
            ]
        ],
    }


@pytest.fixture
def history_page(page, live_server, client):
    page.context.add_cookies(
        [{"name": COOKIE, "value": client.cookies.get(COOKIE), "url": live_server}]
    )
    return page


@pytest.mark.parametrize("width", [390, 1440])
def test_round_history_scorecard_responsive_and_safe(
    history_page, live_server, client, history_payload, width
):
    page = history_page
    response = client.post("/v1/rounds", json=history_payload)
    assert response.status_code == 201
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(live_server + "/#rounds")
    playwright.expect(page.locator(".round-card")).to_have_count(1)
    playwright.expect(page.locator(".round-card time")).to_have_attribute(
        "datetime", "2026-10-18T12:30:00Z"
    )
    playwright.expect(page.locator(".round-card")).to_contain_text(
        "Historic Main · 4 holes · Par 12"
    )
    playwright.expect(page.locator(".round-results")).to_contain_text("14 strokes (+2)")
    playwright.expect(page.locator(".round-results")).to_contain_text("10 strokes (-2)")
    playwright.expect(page.locator(".round-results")).to_contain_text("12 strokes (E)")
    page.get_by_role("link", name="View scorecard →").click()
    playwright.expect(
        page.get_by_role("heading", name=history_payload["course_name"], exact=True)
    ).to_be_visible()
    playwright.expect(page.locator(".scorecard tbody tr")).to_have_count(4)
    playwright.expect(page.locator(".scorecard thead")).to_contain_text("Alice")
    playwright.expect(page.locator(".scorecard thead")).to_contain_text(
        "<script>Guest</script>"
    )
    playwright.expect(page.locator(".scorecard tfoot tr").first).to_contain_text("14")
    playwright.expect(page.locator(".scorecard tfoot tr").nth(1)).to_contain_text("+2")
    for label in ["Birdie", "Par", "Bogey", "Double bogey", "Eagle"]:
        assert page.locator(f'.scorecard [title="{label}"]').count() > 0
        assert page.locator(".score-detail", has_text=label).count() > 0
    assert page.locator("#view img, #view script").count() == 0
    assert page.evaluate("window.roundExecuted === undefined")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    region = page.get_by_role("region", name="Round scorecard, scroll for all players")
    region.focus()
    playwright.expect(region).to_be_focused()
    if width == 390:
        assert region.evaluate("node => node.scrollWidth > node.clientWidth")
        region.evaluate("node => node.scrollLeft = node.scrollWidth")
        assert region.evaluate("node => node.scrollLeft > 0")
    page.screenshot(path=f"/tmp/chainlink-round-scorecard-{width}.png", full_page=True)
    page.get_by_role("link", name="← Round History").click()
    playwright.expect(page.locator(".round-card")).to_have_count(1)


def test_round_history_empty_and_pagination(
    history_page, live_server, client, history_payload
):
    page = history_page
    page.goto(live_server + "/#rounds")
    playwright.expect(
        page.get_by_role("heading", name="No rounds yet", exact=True)
    ).to_be_visible()
    playwright.expect(page.get_by_role("button", name="Next →")).to_be_disabled()
    for index in range(14):
        payload = deepcopy(history_payload)
        payload["id"] = str(uuid4())
        payload["course_name"] = f"Round {index:02}"
        payload["completed_at"] = f"2026-10-{index + 1:02}T12:30:00Z"
        assert client.post("/v1/rounds", json=payload).status_code == 201
    page.get_by_role("button", name="Refresh", exact=True).click()
    playwright.expect(page.locator(".round-card")).to_have_count(12)
    playwright.expect(page.get_by_role("button", name="← Previous")).to_be_disabled()
    page.get_by_role("button", name="Next →").click()
    playwright.expect(page.locator(".round-card")).to_have_count(2)
    playwright.expect(page.get_by_role("button", name="Next →")).to_be_disabled()
    page.get_by_role("link", name="Round 01", exact=True).click()
    playwright.expect(page.locator(".scorecard")).to_be_visible()
    page.get_by_role("link", name="← Round History").click()
    playwright.expect(page.locator(".round-card")).to_have_count(2)
    page.get_by_role("button", name="← Previous").click()
    playwright.expect(page.locator(".round-card")).to_have_count(12)
    page.goto(live_server + "/#rounds?page=999")
    playwright.expect(
        page.get_by_role("heading", name="No rounds on this page", exact=True)
    ).to_be_visible()
    playwright.expect(page.get_by_role("button", name="← Previous")).to_be_enabled()


def test_round_history_expiration_login_and_logout(
    history_page, live_server, client, engine, history_payload
):
    page = history_page
    assert client.post("/v1/rounds", json=history_payload).status_code == 201
    page.goto(live_server + f"/#rounds/{history_payload['id']}")
    playwright.expect(page.locator(".scorecard")).to_be_visible()
    with Session(engine) as db:
        db.get(WebSession, digest(client.cookies.get(COOKIE))).expires_at = (
            int(time.time()) - 1
        )
        db.commit()
    page.reload()
    playwright.expect(
        page.get_by_role("heading", name="Sign in to view Round History")
    ).to_be_visible()
    assert page.locator(".scorecard, .round-card").count() == 0
    page.locator("#view").get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_label("Username", exact=True).fill("test-admin")
    page.get_by_label("Password", exact=True).fill("test-password-123")
    page.get_by_role("dialog").get_by_role("button", name="Sign in", exact=True).click()
    playwright.expect(page.locator(".scorecard")).to_be_visible()
    page.get_by_role("button", name="Sign out", exact=True).click()
    playwright.expect(
        page.get_by_role("heading", name="Sign in to view Round History")
    ).to_be_visible()
    assert page.locator(".scorecard, .round-card").count() == 0


def test_round_history_api_errors_loading_and_navigation(
    history_page, live_server, client, history_payload
):
    page = history_page
    assert client.post("/v1/rounds", json=history_payload).status_code == 201
    page.route(
        "**/v1/rounds?*",
        lambda route: route.fulfill(status=503, json={"detail": "Unavailable"}),
    )
    page.goto(live_server + "/#rounds")
    playwright.expect(
        page.get_by_role("heading", name="Couldn’t load round history.")
    ).to_be_visible()
    page.unroute("**/v1/rounds?*")
    page.get_by_role("button", name="Try again").click()
    playwright.expect(page.locator(".round-card")).to_have_count(1)
    page.route(
        "**/v1/rounds/*",
        lambda route: route.fulfill(status=503, json={"detail": "Unavailable"}),
    )
    page.get_by_role("link", name="View scorecard →").click()
    playwright.expect(
        page.get_by_role("heading", name="Couldn’t load round history.")
    ).to_be_visible()
    page.unroute("**/v1/rounds/*")
    page.get_by_role("button", name="Try again").click()
    playwright.expect(page.locator(".scorecard")).to_be_visible()
    page.route("**/v1/rounds?*", lambda route: None)
    page.get_by_role("link", name="← Round History").click()
    playwright.expect(
        page.get_by_role("heading", name="Loading rounds…")
    ).to_be_visible()
    page.get_by_role("navigation", name="Main navigation").get_by_role(
        "link", name="Courses", exact=True
    ).click()
    playwright.expect(
        page.get_by_role("heading", name="The fairway is wide open.")
    ).to_be_visible()
    assert page.locator(".round-card, .scorecard").count() == 0


def test_round_history_hides_other_accounts(
    history_page, live_server, client, engine, history_payload
):
    page = history_page
    assert client.post("/v1/rounds", json=history_payload).status_code == 201
    with Session(engine) as db:
        other = create_account(db, "history-other", "long-password-123", "player")
        stored = db.scalar(select(CompletedRound))
        stored.owner_id = other.id
        db.commit()
    page.goto(live_server + "/#rounds")
    playwright.expect(
        page.get_by_role("heading", name="No rounds yet", exact=True)
    ).to_be_visible()
    page.goto(live_server + f"/#rounds/{history_payload['id']}")
    playwright.expect(
        page.get_by_role("heading", name="Round not found", exact=True)
    ).to_be_visible()
    assert page.locator(".scorecard, .round-card").count() == 0


@pytest.fixture
def linked_statistics(client, engine, history_payload):
    from app.models import Account

    with Session(engine) as db:
        history_payload["participants"][0]["account_id"] = str(
            db.scalar(select(Account.id))
        )
    assert client.post("/v1/rounds", json=history_payload).status_code == 201
    return history_payload


@pytest.mark.parametrize("width", [390, 1440])
def test_statistics_responsive_calculations_and_history(
    history_page, live_server, linked_statistics, width
):
    page = history_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(live_server + "/#statistics")
    playwright.expect(
        page.get_by_role("heading", name="Round averages", exact=True)
    ).to_be_visible()
    averages = page.get_by_role("region", name="Averages by round length")
    playwright.expect(averages).to_contain_text("14.00")
    playwright.expect(averages).to_contain_text("+2")
    playwright.expect(page.locator(".scoring-frequency meter")).to_have_count(5)
    playwright.expect(page.locator(".statistics-trend")).to_be_visible()
    playwright.expect(
        page.get_by_role("region", name="Recent round performance")
    ).to_contain_text(linked_statistics["course_name"])
    assert page.evaluate("window.roundExecuted === undefined")
    assert page.locator("#view script, #view img").count() == 0
    page.locator(".statistics-best summary").click()
    playwright.expect(
        page.get_by_role("region", name="Personal best hole setup")
    ).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    averages.focus()
    playwright.expect(averages).to_be_focused()
    page.screenshot(path=f"/tmp/chainlink-statistics-{width}.png", full_page=True)
    page.get_by_role("navigation", name="Main navigation").get_by_role(
        "link", name="Round History", exact=True
    ).click()
    playwright.expect(page.locator(".round-card")).to_have_count(1)
    page.get_by_role("link", name="View scorecard →").click()
    playwright.expect(page.locator(".scorecard tbody tr")).to_have_count(4)


def test_statistics_guest_only_empty_state(
    history_page, live_server, client, history_payload
):
    assert client.post("/v1/rounds", json=history_payload).status_code == 201
    page = history_page
    page.goto(live_server + "/#statistics")
    playwright.expect(
        page.get_by_role("heading", name="No linked rounds yet")
    ).to_be_visible()
    assert page.locator(".metric-value, .statistics-trend").count() == 0


def test_statistics_expiration_login_logout(
    history_page, live_server, engine, client, linked_statistics
):
    page = history_page
    page.goto(live_server + "/#statistics")
    playwright.expect(page.locator(".statistics-trend")).to_be_visible()
    with Session(engine) as db:
        db.get(WebSession, digest(client.cookies.get(COOKIE))).expires_at = (
            int(time.time()) - 1
        )
        db.commit()
    page.reload()
    playwright.expect(
        page.get_by_role("heading", name="Sign in to view Statistics")
    ).to_be_visible()
    assert page.locator(".statistics-content").count() == 0
    page.locator("#view").get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_label("Username", exact=True).fill("test-admin")
    page.get_by_label("Password", exact=True).fill("test-password-123")
    page.get_by_role("dialog").get_by_role("button", name="Sign in", exact=True).click()
    playwright.expect(page.locator(".statistics-trend")).to_be_visible()
    page.get_by_role("button", name="Sign out", exact=True).click()
    playwright.expect(
        page.get_by_role("heading", name="Sign in to view Statistics")
    ).to_be_visible()
    assert page.locator(".statistics-content").count() == 0


def test_statistics_error_retry_and_navigation(
    history_page, live_server, linked_statistics
):
    page = history_page
    page.route(
        "**/v1/statistics",
        lambda route: route.fulfill(status=503, json={"detail": "Unavailable"}),
    )
    page.goto(live_server + "/#statistics")
    playwright.expect(
        page.get_by_role("heading", name="Couldn’t load statistics.")
    ).to_be_visible()
    page.unroute("**/v1/statistics")
    page.get_by_role("button", name="Try again").click()
    playwright.expect(page.locator(".statistics-trend")).to_be_visible()
    page.route("**/v1/statistics", lambda route: None)
    page.get_by_role("button", name="Refresh", exact=True).click()
    playwright.expect(
        page.get_by_role("heading", name="Loading statistics…")
    ).to_be_visible()
    page.get_by_role("navigation", name="Main navigation").get_by_role(
        "link", name="Round History", exact=True
    ).click()
    playwright.expect(page.locator(".round-card")).to_have_count(1)
    assert page.locator(".statistics-content").count() == 0


def test_statistics_trend_length_selection(
    history_page, live_server, client, linked_statistics
):
    payload = deepcopy(linked_statistics)
    payload["id"] = str(uuid4())
    payload["holes"] = [
        {"number": n, "par": 3, "tee_name": "Short", "basket_name": "A"}
        for n in range(1, 10)
    ]
    payload["participants"] = [payload["participants"][0]]
    payload["participants"][0]["scores"] = [
        {"hole_number": n, "strokes": 4} for n in range(1, 10)
    ]
    assert client.post("/v1/rounds", json=payload).status_code == 201
    page = history_page
    page.goto(live_server + "/#statistics")
    playwright.expect(page.locator(".statistics-trend")).to_have_attribute(
        "aria-label", re.compile("4-hole monthly")
    )
    page.get_by_label("Round length", exact=True).select_option("9")
    playwright.expect(page.locator(".statistics-trend")).to_have_attribute(
        "aria-label", re.compile("9-hole monthly")
    )
    playwright.expect(
        page.get_by_role("region", name="Monthly scoring trend")
    ).to_contain_text("+9")


@pytest.mark.parametrize("width", [390, 1440])
def test_add_course_admin_creation(history_page, live_server, client, width):
    page = history_page
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(live_server + "/#courses")
    page.get_by_role("button", name="Add Course", exact=True).click()
    dialog = page.get_by_role("dialog", name="Add Course", exact=True)
    playwright.expect(dialog).to_be_visible()
    page.get_by_label("Course name (required)").fill("  New Course  ")
    description = "Wooded fairways\nTwo loops" if width == 1440 else ""
    page.get_by_label("Description (optional)").fill(description)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    bounds = dialog.bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    assert page.locator("#course-save").bounding_box()["height"] >= 44
    with page.expect_response(
        lambda response: response.url.endswith("/v1/courses")
        and response.request.method == "POST"
    ) as created:
        dialog.get_by_role("button", name="Save", exact=True).click()
    response = created.value
    assert response.status == 201
    assert response.request.headers.get("x-csrf-token")
    course = response.json()
    assert course["name"] == "New Course"
    assert course["description"] == (description or None)
    playwright.expect(page).to_have_url(live_server + f"/#courses/{course['id']}")
    playwright.expect(dialog).not_to_be_visible()
    playwright.expect(page.locator("#course-feedback")).to_have_text(
        "Course “New Course” created successfully."
    )
    playwright.expect(page.get_by_role("heading", name="New Course", exact=True)).to_be_visible()
    assert len(client.get("/v1/courses").json()) == 1


@pytest.mark.parametrize("role", [None, "player"])
def test_add_course_denied_to_non_admins(page, live_server, client, engine, role):
    if role:
        with Session(engine) as db:
            create_account(db, "course-player", "player-password-123", role)
        response = client.post("/v1/auth/login", json={
            "username": "course-player", "password": "player-password-123",
        })
        assert response.status_code == 200
        page.context.add_cookies([
            {"name": COOKIE, "value": client.cookies.get(COOKIE), "url": live_server}
        ])
    page.goto(live_server + "/#courses")
    playwright.expect(page.get_by_role("button", name="Refresh", exact=True)).to_be_visible()
    playwright.expect(page.get_by_role("button", name="Add Course", exact=True)).not_to_be_visible()
    # Unhiding or triggering the button cannot bypass either client or server checks.
    page.locator("#add-course").dispatch_event("click")
    playwright.expect(page.locator("#course-dialog")).not_to_be_visible()
    status = page.evaluate("""async () => {
        const auth = await (await fetch('/v1/auth/session')).json();
        const response = await fetch('/v1/courses', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRF-Token': auth.csrf_token},
            body: JSON.stringify({name: 'Forbidden course'})
        });
        return response.status;
    }""")
    assert status == (403 if role else 401)
    assert client.get("/v1/courses").json() == []


def test_add_course_updates_after_login_and_logout(page, live_server):
    page.goto(live_server + "/#courses")
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_label("Username", exact=True).fill("test-admin")
    page.get_by_label("Password", exact=True).fill("test-password-123")
    page.locator("#login-form").get_by_role("button", name="Sign in", exact=True).click()
    playwright.expect(page.locator("#add-course")).to_be_visible()
    page.get_by_role("button", name="Sign out", exact=True).click()
    playwright.expect(page.locator("#add-course")).not_to_be_visible()
    page.locator("#add-course").dispatch_event("click")
    playwright.expect(page.locator("#course-dialog")).not_to_be_visible()


def test_add_course_validation_and_cancel(history_page, live_server, client):
    page = history_page
    posts = []
    page.on("request", lambda request: posts.append(request) if request.method == "POST" else None)
    page.goto(live_server + "/#courses")
    page.get_by_role("button", name="Add Course", exact=True).click()
    name = page.get_by_label("Course name (required)")
    page.get_by_role("button", name="Save", exact=True).click()
    assert not name.evaluate("node => node.validity.valid")
    name.fill("   ")
    page.get_by_role("button", name="Save", exact=True).click()
    assert name.evaluate("node => node.validationMessage") == "Enter a course name."
    assert not posts
    name.fill("Discard me")
    page.get_by_role("button", name="Cancel", exact=True).click()
    playwright.expect(page.locator("#course-dialog")).not_to_be_visible()
    page.get_by_role("button", name="Add Course", exact=True).click()
    playwright.expect(name).to_have_value("")
    page.keyboard.press("Escape")
    playwright.expect(page.locator("#course-dialog")).not_to_be_visible()
    assert client.get("/v1/courses").json() == []


@pytest.mark.parametrize("failure", [422, 500, "network"])
def test_add_course_preserves_input_on_error(history_page, live_server, client, failure):
    page = history_page
    def fail(route):
        if failure == "network":
            route.abort()
        else:
            route.fulfill(status=failure, json={"detail": "Failed"})
    page.route("**/v1/courses", fail)
    page.goto(live_server + "/#courses")
    page.get_by_role("button", name="Add Course", exact=True).click()
    page.get_by_label("Course name (required)").fill("Retry Course")
    page.get_by_label("Description (optional)").fill("Keep this description")
    page.get_by_role("button", name="Save", exact=True).click()
    playwright.expect(page.locator("#course-message")).to_contain_text("preserved")
    playwright.expect(page.get_by_label("Course name (required)")).to_have_value("Retry Course")
    playwright.expect(page.get_by_label("Description (optional)")).to_have_value("Keep this description")
    playwright.expect(page.locator("#course-save")).to_be_enabled()
    assert client.get("/v1/courses").json() == []
    page.unroute("**/v1/courses", fail)
    page.get_by_role("button", name="Save", exact=True).click()
    playwright.expect(page.locator("#course-feedback")).to_contain_text("created successfully")
    assert len(client.get("/v1/courses").json()) == 1


def test_add_course_prevents_duplicate_submissions(history_page, live_server, client):
    page = history_page
    pending = []
    page.route("**/v1/courses", lambda route: pending.append(route))
    page.goto(live_server + "/#courses")
    page.get_by_role("button", name="Add Course", exact=True).click()
    page.get_by_label("Course name (required)").fill("Only once")
    with page.expect_request(lambda request: request.method == "POST"):
        page.get_by_role("button", name="Save", exact=True).click()
    playwright.expect(page.locator("#course-save")).to_be_disabled()
    playwright.expect(page.locator("#course-cancel")).to_be_disabled()
    page.locator("#course-form").dispatch_event("submit")
    page.keyboard.press("Escape")
    playwright.expect(page.locator("#course-dialog")).to_be_visible()
    assert len(pending) == 1
    pending[0].continue_()
    playwright.expect(page.locator("#course-feedback")).to_contain_text("created successfully")
    assert len(client.get("/v1/courses").json()) == 1


def test_add_course_refreshes_csrf_before_retry(history_page, live_server, client):
    page = history_page
    def missing_csrf(route):
        route.continue_(headers={
            key: value for key, value in route.request.headers.items()
            if key.lower() != "x-csrf-token"
        })
    page.route("**/v1/courses", missing_csrf)
    page.goto(live_server + "/#courses")
    page.get_by_role("button", name="Add Course", exact=True).click()
    page.get_by_label("Course name (required)").fill("Retry with token")
    page.get_by_role("button", name="Save", exact=True).click()
    playwright.expect(page.locator("#course-message")).to_contain_text("security token was refreshed")
    playwright.expect(page.get_by_label("Course name (required)")).to_have_value("Retry with token")
    playwright.expect(page.locator("#course-save")).to_be_enabled()
    assert client.get("/v1/courses").json() == []
    page.unroute("**/v1/courses", missing_csrf)
    page.get_by_role("button", name="Save", exact=True).click()
    playwright.expect(page.locator("#course-feedback")).to_contain_text("created successfully")
    assert len(client.get("/v1/courses").json()) == 1


def test_add_course_expired_session_preserves_input(history_page, live_server, client, engine):
    page = history_page
    page.goto(live_server + "/#courses")
    page.get_by_role("button", name="Add Course", exact=True).click()
    page.get_by_label("Course name (required)").fill("Keep after expiry")
    with Session(engine) as db:
        db.get(WebSession, digest(client.cookies.get(COOKIE))).expires_at = 0
        db.commit()
    page.get_by_role("button", name="Save", exact=True).click()
    playwright.expect(page.locator("#course-message")).to_contain_text("Administrator sign-in is required")
    playwright.expect(page.get_by_label("Course name (required)")).to_have_value("Keep after expiry")
    playwright.expect(page.locator("#course-save")).to_be_disabled()
    playwright.expect(page.locator("#add-course")).not_to_be_visible()
    assert client.get("/v1/courses").json() == []
    page.get_by_role("button", name="Sign in as administrator", exact=True).click()
    page.get_by_label("Username", exact=True).fill("test-admin")
    page.get_by_label("Password", exact=True).fill("test-password-123")
    page.locator("#login-form").get_by_role("button", name="Sign in", exact=True).click()
    playwright.expect(page.locator("#login-dialog")).not_to_be_visible()
    playwright.expect(page.get_by_label("Course name (required)")).to_have_value("Keep after expiry")
    playwright.expect(page.locator("#course-save")).to_be_enabled()
    page.get_by_role("button", name="Save", exact=True).click()
    playwright.expect(page.locator("#course-feedback")).to_contain_text("created successfully")
    assert len(client.get("/v1/courses").json()) == 1
