from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

import requests


PLACEHOLDER_PROXY_NAMES = {
    "COMPATIBLE",
    "DIRECT",
    "GLOBAL",
    "PASS",
    "PASS-RULE",
    "REJECT",
    "REJECT-DROP",
    "RADAR-AUTO",
}


def wait_tcp(host: str, port: int, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"port {host}:{port} did not become ready: {last_error}")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _provider_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = payload.get("proxies")
    if isinstance(nodes, list):
        return [node for node in nodes if isinstance(node, dict)]
    if isinstance(nodes, dict):
        return [node for node in nodes.values() if isinstance(node, dict)]
    return []


def _group_real_names(payload: dict[str, Any]) -> list[str]:
    group = payload.get("proxies", {}).get("RADAR-AUTO", {})
    names = group.get("all") if isinstance(group, dict) else None
    if not isinstance(names, list):
        return []
    return [
        str(name)
        for name in names
        if str(name).strip() and str(name) not in PLACEHOLDER_PROXY_NAMES
    ]


def _controller_session() -> requests.Session:
    session = requests.Session()
    # Do not inherit HTTP_PROXY/ALL_PROXY while talking to the local controller.
    session.trust_env = False
    return session


def wait_provider(
    controller_base: str,
    headers: dict[str, str],
    diagnostics: Path,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last_provider: dict[str, Any] = {}
    last_proxies: dict[str, Any] = {}
    session = _controller_session()
    update_triggered = False

    while time.monotonic() < deadline:
        try:
            provider_response = session.get(
                f"{controller_base}/providers/proxies/mergelist",
                headers=headers,
                timeout=10,
            )
            provider_response.raise_for_status()
            last_provider = provider_response.json()
            _write_json(diagnostics / "mihomo-provider.json", last_provider)

            proxies_response = session.get(
                f"{controller_base}/proxies",
                headers=headers,
                timeout=10,
            )
            proxies_response.raise_for_status()
            last_proxies = proxies_response.json()
            _write_json(diagnostics / "mihomo-proxies.json", last_proxies)

            provider_nodes = _provider_nodes(last_provider)
            real_group_names = _group_real_names(last_proxies)
            if provider_nodes and real_group_names:
                return last_provider, last_proxies

            if not update_triggered:
                try:
                    session.put(
                        f"{controller_base}/providers/proxies/mergelist",
                        headers=headers,
                        timeout=10,
                    )
                finally:
                    update_triggered = True
        except Exception as exc:
            (diagnostics / "mihomo-provider-wait-error.txt").write_text(
                f"{type(exc).__name__}: {exc}\n",
                encoding="utf-8",
            )
        time.sleep(2)

    provider_nodes = _provider_nodes(last_provider)
    real_group_names = _group_real_names(last_proxies)
    raise RuntimeError(
        "proxy provider did not load real nodes before timeout: "
        f"provider_nodes={len(provider_nodes)}, group_nodes={len(real_group_names)}"
    )


def smoke_test_proxy(socks_port: int, diagnostics: Path) -> list[dict[str, Any]]:
    proxy = f"socks5h://127.0.0.1:{socks_port}"
    required_url = os.getenv("MIHOMO_TARGET_TEST_URL", "https://quote.eastmoney.com/")
    optional_url = os.getenv("MIHOMO_EGRESS_TEST_URL", "https://api.ipify.org?format=json")
    tests = [
        ("target", required_url, True),
        ("egress", optional_url, False),
    ]

    session = requests.Session()
    session.trust_env = False
    results: list[dict[str, Any]] = []
    required_ok = False

    for name, url, required in tests:
        item: dict[str, Any] = {"name": name, "url": url, "required": required}
        try:
            response = session.get(
                url,
                proxies={"http": proxy, "https": proxy},
                timeout=45,
                allow_redirects=True,
            )
            item.update(
                {
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "body_preview": response.text[:200],
                    "ok": 200 <= response.status_code < 400,
                }
            )
            if required and item["ok"]:
                required_ok = True
        except Exception as exc:
            item.update(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        results.append(item)

    _write_json(diagnostics / "proxy-smoke.json", results)
    if not required_ok:
        raise RuntimeError("selected proxy could not reach the required target URL")
    return results


def main() -> int:
    diagnostics = Path(os.getenv("RADAR_DIAGNOSTICS_DIR", "diagnostics"))
    diagnostics.mkdir(parents=True, exist_ok=True)
    socks_port = int(os.getenv("MIHOMO_SOCKS_PORT", "7891"))
    controller_port = int(os.getenv("MIHOMO_CONTROLLER_PORT", "9090"))
    timeout = int(os.getenv("MIHOMO_START_TIMEOUT", "120"))
    secret = os.getenv("MIHOMO_CONTROLLER_SECRET", "")
    controller_base = f"http://127.0.0.1:{controller_port}"

    try:
        wait_tcp("127.0.0.1", controller_port, timeout)
        wait_tcp("127.0.0.1", socks_port, timeout)

        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        provider_json, proxies_json = wait_provider(
            controller_base=controller_base,
            headers=headers,
            diagnostics=diagnostics,
            timeout=timeout,
        )
        results = smoke_test_proxy(socks_port=socks_port, diagnostics=diagnostics)
        summary = {
            "provider_nodes": len(_provider_nodes(provider_json)),
            "group_nodes": len(_group_real_names(proxies_json)),
            "selected": proxies_json.get("proxies", {}).get("RADAR-AUTO", {}).get("now"),
            "smoke": results,
        }
        _write_json(diagnostics / "proxy-ready-summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        (diagnostics / "proxy-start-error.txt").write_text(
            f"{type(exc).__name__}: {exc}\n",
            encoding="utf-8",
        )
        print(f"Mihomo readiness failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
