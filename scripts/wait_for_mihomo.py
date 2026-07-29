from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

DEFAULT_EASTMONEY_TEST_URL = (
    "https://82.push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz=1&po=1&np=1"
    "&ut=bd1d9ddb04089700cf9c27f6f7426281"
    "&fltt=2&invt=2&fid=f3"
    "&fs=m%3A1+t%3A2"
    "&fields=f2%2Cf3%2Cf12%2Cf14"
)

PLACEHOLDER_PROXY_NAMES = {
    "COMPATIBLE",
    "DIRECT",
    "GLOBAL",
    "PASS",
    "PASS-RULE",
    "REJECT",
    "REJECT-DROP",
    "RADAR-AUTO",
    "RADAR-SELECT",
}


def wait_tcp(host: str, port: int, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
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
    groups = payload.get("proxies", {})
    for group_name in ("RADAR-SELECT", "RADAR-AUTO"):
        group = groups.get(group_name, {}) if isinstance(groups, dict) else {}
        names = group.get("all") if isinstance(group, dict) else None
        if isinstance(names, list):
            real = [
                str(name)
                for name in names
                if str(name).strip() and str(name) not in PLACEHOLDER_PROXY_NAMES
            ]
            if real:
                return real
    return []


def _controller_session() -> requests.Session:
    session = requests.Session()
    # Never inherit HTTP_PROXY/ALL_PROXY while talking to localhost.
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
                    response = session.put(
                        f"{controller_base}/providers/proxies/mergelist",
                        headers=headers,
                        timeout=10,
                    )
                    response.raise_for_status()
                finally:
                    update_triggered = True
        except requests.RequestException as exc:
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


def _node_name(node: dict[str, Any]) -> str:
    return str(node.get("name") or "").strip()


def _node_delay(node: dict[str, Any]) -> int:
    history = node.get("history")
    if isinstance(history, list):
        for item in reversed(history):
            if isinstance(item, dict):
                delay = item.get("delay")
                if isinstance(delay, int) and delay > 0:
                    return delay
    return 1_000_000


def _candidate_nodes(provider_payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    nodes = [node for node in _provider_nodes(provider_payload) if _node_name(node)]
    nodes.sort(
        key=lambda node: (
            node.get("alive") is False,
            _node_delay(node),
            _node_name(node),
        )
    )
    return nodes[: max(1, limit)]


def _select_node(
    session: requests.Session,
    controller_base: str,
    headers: dict[str, str],
    node_name: str,
) -> None:
    group = quote("RADAR-SELECT", safe="")
    response = session.put(
        f"{controller_base}/proxies/{group}",
        headers=headers,
        json={"name": node_name},
        timeout=10,
    )
    response.raise_for_status()
    time.sleep(0.25)


def _trigger_native_node_check(
    session: requests.Session,
    controller_base: str,
    headers: dict[str, str],
    node_name: str,
    target_url: str,
    timeout_ms: int,
) -> dict[str, Any]:
    encoded_name = quote(node_name, safe="")
    endpoint = (
        f"{controller_base}/providers/proxies/mergelist/"
        f"{encoded_name}/healthcheck"
    )
    try:
        response = session.get(
            endpoint,
            headers=headers,
            params={"url": target_url, "timeout": timeout_ms},
            timeout=max(10, timeout_ms / 1000 + 5),
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        return {"ok": True, "payload": payload}
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _parse_json_or_jsonp(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", stripped, flags=re.DOTALL)
        if not match:
            raise ValueError("response is neither JSON nor JSONP") from None
        payload = json.loads(match.group(1))
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object, received {type(payload).__name__}")
    return payload


def _validate_target_response(status: int, content_type: str, text: str) -> dict[str, Any]:
    preview = text[:300]
    if not 200 <= status < 400:
        raise RuntimeError(f"unexpected HTTP status: {status}")
    if not text.strip():
        raise RuntimeError("target returned an empty body")
    lowered = text.lstrip().lower()
    if lowered.startswith("<") or "text/html" in content_type.lower():
        raise RuntimeError("target returned HTML instead of API data")

    payload = _parse_json_or_jsonp(text)
    if "rc" not in payload and "data" not in payload:
        raise RuntimeError("target JSON does not look like an Eastmoney API response")
    return {
        "status": status,
        "content_type": content_type,
        "body_preview": preview,
        "rc": payload.get("rc"),
        "has_data": payload.get("data") is not None,
    }


def _requests_target_check(socks_port: int, target_url: str, timeout: int) -> dict[str, Any]:
    proxy = f"socks5h://127.0.0.1:{socks_port}"
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        target_url,
        proxies={"http": proxy, "https": proxy},
        timeout=timeout,
        allow_redirects=True,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "Mozilla/5.0 a-stock-evidence-radar/0.2.4",
        },
    )
    return _validate_target_response(
        response.status_code,
        response.headers.get("content-type", ""),
        response.text,
    )


def _playwright_target_check(
    socks_port: int,
    target_url: str,
    timeout_ms: int,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed") from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                proxy={"server": f"socks5://127.0.0.1:{socks_port}"},
            )
            try:
                context = browser.new_context(
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    ignore_https_errors=False,
                )
                page = context.new_page()
                response = page.goto(
                    target_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                if response is None:
                    raise RuntimeError("Playwright did not receive an HTTP response")
                body = page.locator("body").inner_text(timeout=timeout_ms)
                return _validate_target_response(
                    response.status,
                    response.headers.get("content-type", ""),
                    body,
                )
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise RuntimeError(f"PlaywrightError: {exc}") from exc


def select_tls_healthy_proxy(
    provider_payload: dict[str, Any],
    *,
    controller_base: str,
    headers: dict[str, str],
    socks_port: int,
    diagnostics: Path,
) -> tuple[str, list[dict[str, Any]]]:
    target_url = os.getenv(
        "MIHOMO_NODE_TEST_URL",
        os.getenv("MIHOMO_TARGET_TEST_URL", DEFAULT_EASTMONEY_TEST_URL),
    )
    limit = int(os.getenv("MIHOMO_NODE_TEST_LIMIT", "20"))
    request_timeout = int(os.getenv("MIHOMO_NODE_REQUEST_TIMEOUT", "18"))
    browser_timeout_ms = int(os.getenv("MIHOMO_NODE_BROWSER_TIMEOUT_MS", "25000"))
    browser_enabled = os.getenv("MIHOMO_NODE_PLAYWRIGHT_CHECK", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    native_timeout_ms = int(os.getenv("MIHOMO_NATIVE_HEALTH_TIMEOUT_MS", "12000"))

    controller = _controller_session()
    attempts: list[dict[str, Any]] = []
    for index, node in enumerate(_candidate_nodes(provider_payload, limit), start=1):
        name = _node_name(node)
        attempt: dict[str, Any] = {
            "index": index,
            "name": name,
            "provider_alive": node.get("alive"),
            "provider_delay_ms": _node_delay(node),
            "target_url": target_url,
        }
        try:
            attempt["native_health"] = _trigger_native_node_check(
                controller,
                controller_base,
                headers,
                name,
                target_url,
                native_timeout_ms,
            )
            _select_node(controller, controller_base, headers, name)
            attempt["requests"] = _requests_target_check(
                socks_port,
                target_url,
                request_timeout,
            )
            if browser_enabled:
                attempt["playwright"] = _playwright_target_check(
                    socks_port,
                    target_url,
                    browser_timeout_ms,
                )
            else:
                attempt["playwright"] = {"skipped": True}
            attempt["ok"] = True
            attempts.append(attempt)
            _write_json(diagnostics / "proxy-node-validation.json", attempts)
            return name, attempts
        except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
            attempt.update(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "ssl_eof": any(
                        marker in str(exc)
                        for marker in (
                            "UNEXPECTED_EOF_WHILE_READING",
                            "SSLEOFError",
                            "EOF occurred in violation of protocol",
                            "ERR_CONNECTION_CLOSED",
                        )
                    ),
                }
            )
            attempts.append(attempt)
            _write_json(diagnostics / "proxy-node-validation.json", attempts)

    raise RuntimeError(
        f"no proxy passed target TLS/API validation; tested={len(attempts)}"
    )


def optional_egress_test(socks_port: int) -> dict[str, Any]:
    proxy = f"socks5h://127.0.0.1:{socks_port}"
    url = os.getenv("MIHOMO_EGRESS_TEST_URL", "https://api.ipify.org?format=json")
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            url,
            proxies={"http": proxy, "https": proxy},
            timeout=20,
            allow_redirects=True,
        )
        return {
            "url": url,
            "ok": 200 <= response.status_code < 400,
            "status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "body_preview": response.text[:200],
        }
    except requests.RequestException as exc:
        return {
            "url": url,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


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
        selected, attempts = select_tls_healthy_proxy(
            provider_json,
            controller_base=controller_base,
            headers=headers,
            socks_port=socks_port,
            diagnostics=diagnostics,
        )
        egress = optional_egress_test(socks_port)
        summary = {
            "provider_nodes": len(_provider_nodes(provider_json)),
            "group_nodes": len(_group_real_names(proxies_json)),
            "selected": selected,
            "tested_nodes": len(attempts),
            "ssl_eof_nodes": sum(bool(item.get("ssl_eof")) for item in attempts),
            "egress": egress,
        }
        _write_json(diagnostics / "proxy-ready-summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (requests.RequestException, RuntimeError, OSError, ValueError) as exc:
        (diagnostics / "proxy-start-error.txt").write_text(
            f"{type(exc).__name__}: {exc}\n",
            encoding="utf-8",
        )
        print(f"Mihomo readiness failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
