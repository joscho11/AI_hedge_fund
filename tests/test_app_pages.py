"""Smoke-test every dashboard page renders without raising (AppTest). Matches the standing rule:
after any app change, render every page and confirm none error before calling it committable.
Skipped automatically if streamlit isn't installed or the results artifacts are absent."""
from __future__ import annotations

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = st_testing.AppTest

APP = Path(__file__).resolve().parents[1] / "app"
RESULTS = Path(__file__).resolve().parents[1] / "data_cache" / "results"

pytestmark = pytest.mark.skipif(
    not (RESULTS / "meta.json").exists(),
    reason="dashboard artifacts not built (run scripts/phase2_baselines.py)",
)

PAGES = [
    APP / "main.py",
    APP / "pages" / "2_Universe_explorer.py",
    APP / "pages" / "3_Performance_baselines.py",
    APP / "pages" / "4_Model_rankings.py",
    APP / "pages" / "5_Methodology_and_rigor.py",
]


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_page_renders_without_exception(page):
    at = AppTest.from_file(str(page), default_timeout=30).run()
    assert not at.exception, f"{page.name} raised: {at.exception}"
    # Honesty layer present on every page (the warning banner).
    assert any("not investment advice" in w.value for w in at.warning), \
        f"{page.name} missing the honesty banner"
