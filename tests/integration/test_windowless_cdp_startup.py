"""A fresh CDP launch owns its initial page with no pre-existing window."""

import json
from urllib.request import ProxyHandler, build_opener

from ai_dev_browser.core.browser import browser_start, browser_stop


def test_windowless_headless_cdp_returns_its_single_owned_page(tmp_path):
    result = browser_start(transport="cdp", headless="new", temp=True, reuse="none")
    evidence = {"startup": result}
    try:
        assert "error" not in result, result
        assert result["connected"] is True
        assert result["reused"] is False
        assert result["automation_target_id"]
        opener = build_opener(ProxyHandler({}))
        with opener.open(
            f"http://127.0.0.1:{result['port']}/json/list", timeout=5
        ) as response:
            pages = [item for item in json.load(response) if item["type"] == "page"]
        evidence["pages"] = [
            {"id": item["id"], "type": item["type"], "url": item["url"]}
            for item in pages
        ]
        assert len(pages) == 1, evidence
        assert pages[0]["id"] == result["automation_target_id"]
        assert pages[0]["url"] == "about:blank"
    finally:
        if isinstance(result.get("port"), int):
            stopped = browser_stop(port=result["port"])
            evidence["cleanup"] = stopped
        (tmp_path / "windowless-cdp-startup-evidence.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        if "cleanup" in evidence:
            assert "error" not in evidence["cleanup"], evidence
