from __future__ import annotations

import os
from pathlib import Path

import yaml


def main() -> None:
    runtime_dir = Path(os.getenv("MIHOMO_RUNTIME_DIR", "runtime/mihomo"))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "providers").mkdir(parents=True, exist_ok=True)

    provider_url = os.getenv(
        "MIHOMO_PROVIDER_URL",
        "https://mergelist.vercel.app/api/all",
    )
    health_url = os.getenv(
        "MIHOMO_HEALTHCHECK_URL",
        "https://quote.eastmoney.com/",
    )
    socks_port = int(os.getenv("MIHOMO_SOCKS_PORT", "7891"))
    mixed_port = int(os.getenv("MIHOMO_MIXED_PORT", "7890"))
    controller_port = int(os.getenv("MIHOMO_CONTROLLER_PORT", "9090"))

    config = {
        "mixed-port": mixed_port,
        "socks-port": socks_port,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "mode": "rule",
        "log-level": os.getenv("MIHOMO_LOG_LEVEL", "info"),
        "ipv6": False,
        "unified-delay": True,
        "tcp-concurrent": True,
        "external-controller": f"127.0.0.1:{controller_port}",
        "secret": os.getenv("MIHOMO_CONTROLLER_SECRET", ""),
        "profile": {
            "store-selected": False,
            "store-fake-ip": False,
        },
        "dns": {
            "enable": True,
            "ipv6": False,
            "enhanced-mode": "redir-host",
            "default-nameserver": ["1.1.1.1", "8.8.8.8"],
            "nameserver": [
                "https://1.1.1.1/dns-query",
                "https://dns.google/dns-query",
            ],
        },
        "proxy-providers": {
            "mergelist": {
                "type": "http",
                "url": provider_url,
                "path": "./providers/mergelist.yaml",
                "interval": 3600,
                "health-check": {
                    "enable": True,
                    "url": health_url,
                    "interval": 300,
                    "timeout": 8000,
                    "lazy": False,
                    "expected-status": "200-399",
                },
                "override": {"additional-prefix": "[mergelist] "},
            }
        },
        "proxy-groups": [
            {
                "name": "RADAR-AUTO",
                "type": "url-test",
                "use": ["mergelist"],
                "url": health_url,
                "interval": 300,
                "timeout": 8000,
                "tolerance": 150,
                "lazy": False,
                "expected-status": "200-399",
            }
        ],
        "rules": ["MATCH,RADAR-AUTO"],
    }

    output = runtime_dir / "config.yaml"
    output.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Wrote Mihomo config to {output}")
    print(f"SOCKS endpoint: socks5://127.0.0.1:{socks_port}")
    print(f"Provider URL: {provider_url}")


if __name__ == "__main__":
    main()
