import re

import pytest

from keepair.config import REPO_ROOT
from keepair.health import COMPONENTS
from keepair.web.pages import PAGES
from tests.system.conftest import ALL_PATHS

NAV = [
    "Overview",
    "Spend",
    "Budgets",
    "Gateway",
    "Approvals",
    "Reconciliation",
    "Reports",
    "Admin",
    "Audit log",
]


@pytest.mark.req("UX-1")
@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.slug)
def test_every_page_opens_with_full_navigation(ui, page):
    soup = ui.soup(page.path)
    links = soup.select("nav[aria-label=Main] a")
    assert [a.get_text(strip=True) for a in links] == NAV
    current = [a for a in links if a.get("aria-current") == "page"]
    assert [a.get_text(strip=True) for a in current] == [page.title]
    assert soup.find("h1").get_text(strip=True) == page.title


@pytest.mark.req("Hard rule 2 (DEMO label on every page)")
@pytest.mark.parametrize("path", [*ALL_PATHS, "/no-such-page"])
def test_demo_label_is_in_the_header_of_every_page(ui, path):
    soup = ui.soup(path, status=404 if path == "/no-such-page" else 200)
    label = soup.select_one("[data-demo-label]")
    assert label is not None and "DEMO" in label.get_text()
    assert "(demo)" in soup.title.get_text()


@pytest.mark.req("UX-1", "ISO 12207 (phase plan visible in product)")
@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.slug)
def test_unbuilt_sections_say_which_phase_and_requirement(ui, page):
    rows = ui.soup(page.path).select(".roadmap li")
    assert len(rows) == len(page.sections)
    for row, section in zip(rows, page.sections, strict=True):
        expected = f"Coming in phase {section.phase}" if section.phase else "Not in the MVP phases"
        assert expected in row.get_text()
        reqs = [c.get_text() for c in row.select("code")]
        assert reqs == list(section.reqs)
        assert all(re.fullmatch(r"(FR|UX|SEC)-\d{1,2}", r) for r in reqs)


@pytest.mark.req("UX-6", "FR-21")
@pytest.mark.parametrize("path", ALL_PATHS)
def test_health_strip_shows_every_component_as_unknown(ui, path):
    items = ui.soup(path).select(".health li")
    assert [li["data-component"] for li in items] == [c.id for c in COMPONENTS]
    for li in items:
        chip = li.select_one(".status")
        assert chip["class"] == ["status", "status--unknown"]
        # Status is never colour alone: an icon and a word (UX-14).
        assert chip.select_one(".status__icon[aria-hidden=true]").get_text() == "?"
        assert chip.get_text(strip=True).endswith("Unknown")


@pytest.mark.req("UX-6 (Unknown is never green)")
def test_unknown_status_style_never_uses_the_healthy_colour():
    css = (REPO_ROOT / "ui" / "static" / "app.css").read_text()
    rules = re.findall(r"\.status--unknown[^{]*\{([^}]*)\}", css)
    assert rules, "no style for the unknown status"
    assert all("--ok" not in rule for rule in rules)
    assert "var(--unknown)" in rules[0]


@pytest.mark.req("UX-14", "ISO 25010 usability (accessibility)")
@pytest.mark.parametrize("path", ALL_PATHS)
def test_accessibility_basics(ui, path):
    soup = ui.soup(path)
    assert soup.html["lang"] == "en" and soup.html["dir"] == "ltr"
    assert len(soup.find_all("h1")) == 1
    skip = soup.select_one("a.skip")
    assert skip["href"] == "#main" and soup.select_one("main#main")
    for button in soup.find_all("button"):
        assert button.get("aria-label") or button.get_text(strip=True), "button without a name"
    for th in soup.find_all("th"):
        assert th.get("scope") == "col"
    ids = [el["id"] for el in soup.select("[id]")]
    assert len(ids) == len(set(ids)), "duplicate element IDs"
    for el in soup.select("[aria-labelledby]"):
        assert el["aria-labelledby"] in ids


@pytest.mark.req("SEC-27", "ISO 27001 A.8.28")
@pytest.mark.parametrize("path", ["/", "/gateway", "/no-such-page", "/static/app.css"])
def test_security_headers_on_every_response(ui, path):
    headers = ui.client.get(path).headers
    csp = headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert headers["x-content-type-options"] == "nosniff"


@pytest.mark.req("SEC-27")
@pytest.mark.parametrize("path", ALL_PATHS)
def test_pages_have_no_inline_script_or_style(ui, path):
    soup = ui.soup(path)
    assert all(s.get("src") for s in soup.find_all("script"))
    assert not soup.find_all("style") and not soup.select("[style]")
    assert not [el for el in soup.find_all(True) if any(a.startswith("on") for a in el.attrs)]


@pytest.mark.req("UX-1")
def test_unknown_page_is_a_404_not_a_failure(ui):
    soup = ui.soup("/no-such-page", status=404)
    assert soup.find("h1").get_text() == "Page not found"
    assert ui.metrics.value("keepair_failures_total", code="UNHANDLED_ERROR") == 0


@pytest.mark.req("ISO 27001 A.8.16")
def test_liveness_and_metrics_endpoints(ui):
    assert ui.client.get("/healthz").json()["status"] == "alive"
    assert ui.client.get("/metrics").status_code == 200
