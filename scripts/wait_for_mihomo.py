from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

import requests


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


def main() -> int:
    diagnostics = Path(os.getenv("RADAR_DIAGNOSTICS_DIR", "diagnostics"))
    diagnostics.mkdir(parents=True, exist_ok=True)
    socks_port = int(os.getenv("MIHOMO_SOCKS_PORT", "7891"))
    controller_port = int(os.getenv("MIHOMO_CONTROLLER_PORT", "9090"))
    timeout = int(os.getenv("MIHOMO_START_TIMEOUT", "90"))
    secret = os.getenv("MIHOMO_CONTROLLER_SECRET", "")

    try:
        wait_tcp("127.0.0.1", controller_port, timeout)
        wait_tcp("127.0.0.1", socks_port, timeout)

        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        controller = requests.get(
            f"http://127.0.0.1:{controller_port}/proxies",
            headers=headers,
            timeout=10,
        )
        controller.raise_for_status()
        controller_json = controller.json()
        (diagnostics / "mihomo-proxies.json").write_text(
            json.dumps(controller_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if "RADAR-AUTO" not in controller_json.get("proxies", {}):
            raise RuntimeError("RADAR-AUTO proxy group was not loaded")

        proxy = f"socks5h://127.0.0.1:{socks_port}"
        test_urls = [
            os.getenv("MIHOMO_EGRESS_TEST_URL", "https://api.ipify.org?format=json"),
            os.getenv("MIHOMO_TARGET_TEST_URL", "https://quote.eastmoney.com/"),
        ]
        results = []
        for url in test_urls:
            response = requests.get(
                url,
                proxies={"http": proxy, "https": proxy},
                timeout=30,
                allow_redirects=True,
            )
            results.append(
                {
                    "url": url,
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "body_preview": response.text[:200],
                }
            )
            response.raise_for_status()
        (diagnostics / "proxy-smoke.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(results, ensure_ascii=False, indent=2))
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
