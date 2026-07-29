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
    assert provider["proxy"] == "DIRECT"
    assert config["rules"][0] == "DOMAIN,mergelist.vercel.app,DIRECT"
    assert config["rules"][-1] == "MATCH,RADAR-AUTO"


def test_provider_node_detection_rejects_compatible_placeholder() -> None:
    module = _load_script("wait_for_mihomo.py")

    provider = {"proxies": [{"name": "node-a", "alive": True}]}
    proxies = {
        "proxies": {
            "RADAR-AUTO": {
                "all": ["COMPATIBLE", "[mergelist] node-a"],
                "now": "[mergelist] node-a",
            }
        }
    }

    assert len(module._provider_nodes(provider)) == 1
    assert module._group_real_names(proxies) == ["[mergelist] node-a"]
    assert module._group_real_names(
        {"proxies": {"RADAR-AUTO": {"all": ["COMPATIBLE"]}}}
    ) == []
