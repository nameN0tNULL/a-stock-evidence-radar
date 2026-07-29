from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):  # noqa: ANN202
    path = PROJECT_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mihomo_provider_bootstraps_direct(monkeypatch) -> None:  # noqa: ANN001
    module = _load_script("render_mihomo_config.py")
    monkeypatch.setenv("MIHOMO_PROVIDER_URL", "https://mergelist.vercel.app/api/all")
    config = module.build_config()

    provider = config["proxy-providers"]["mergelist"]
    groups = {group["name"]: group for group in config["proxy-groups"]}
    assert provider["proxy"] == "DIRECT"
    assert config["rules"][0] == "DOMAIN,mergelist.vercel.app,DIRECT"
    assert config["rules"][-1] == "MATCH,RADAR-SELECT"
    assert groups["RADAR-SELECT"]["type"] == "select"
    assert groups["RADAR-SELECT"]["use"] == ["mergelist"]
    assert groups["RADAR-AUTO"]["url"].startswith("https://82.push2.eastmoney.com/")


def test_provider_node_detection_rejects_placeholders() -> None:
    module = _load_script("wait_for_mihomo.py")

    provider = {"proxies": [{"name": "node-a", "alive": True}]}
    proxies = {
        "proxies": {
            "RADAR-SELECT": {
                "all": ["RADAR-AUTO", "DIRECT", "[mergelist] node-a"],
                "now": "RADAR-AUTO",
            }
        }
    }

    assert len(module._provider_nodes(provider)) == 1
    assert module._group_real_names(proxies) == ["[mergelist] node-a"]
    assert module._group_real_names(
        {"proxies": {"RADAR-SELECT": {"all": ["RADAR-AUTO", "DIRECT"]}}}
    ) == []


def test_candidate_nodes_prioritize_alive_low_latency() -> None:
    module = _load_script("wait_for_mihomo.py")
    provider = {
        "proxies": [
            {"name": "dead", "alive": False, "history": [{"delay": 20}]},
            {"name": "slow", "alive": True, "history": [{"delay": 500}]},
            {"name": "fast", "alive": True, "history": [{"delay": 80}]},
        ]
    }

    assert [node["name"] for node in module._candidate_nodes(provider, 3)] == [
        "fast",
        "slow",
        "dead",
    ]


def test_eastmoney_target_response_validation_accepts_json() -> None:
    module = _load_script("wait_for_mihomo.py")
    result = module._validate_target_response(
        200,
        "application/json",
        '{"rc":0,"data":{"diff":[{"f12":"600000"}]}}',
    )
    assert result["rc"] == 0
    assert result["has_data"] is True


def test_eastmoney_target_response_validation_rejects_html() -> None:
    module = _load_script("wait_for_mihomo.py")
    try:
        module._validate_target_response(200, "text/html", "<html>blocked</html>")
    except RuntimeError as exc:
        assert "HTML" in str(exc)
    else:
        raise AssertionError("HTML response must be rejected")
