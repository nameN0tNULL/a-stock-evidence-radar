from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import yaml

DEFAULT_EASTMONEY_TEST_URL = (
    "https://82.push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz=1&po=1&np=1"
    "&ut=bd1d9ddb04089700cf9c27f6f7426281"
    "&fltt=2&invt=2&fid=f3"
    "&fs=m%3A1+t%3A2"
    "&fields=f2%2Cf3%2Cf12%2Cf14"
)


def _provider_host(provider_url: str) -> str | None:
    host = urlparse(provider_url).hostname
    return host.lower() if host else None


def build_config() -> dict:
    provider_url = os.getenv(
        "MIHOMO_PROVIDER_URL",
        "https://mergelist.vercel.app/api/all",
    )
    health_url = os.getenv(
        "MIHOMO_HEALTHCHECK_URL",
        os.getenv("MIHOMO_NODE_TEST_URL", DEFAULT_EASTMONEY_TEST_URL),
    )
    socks_port = int(os.getenv("MIHOMO_SOCKS_PORT", "7891"))
    mixed_port = int(os.getenv("MIHOMO_MIXED_PORT", "7890"))
    controller_port = int(os.getenv("MIHOMO_CONTROLLER_PORT", "9090"))

    provider: dict = {
        "type": "http",
        "url": provider_url,
        "path": "./providers/mergelist.yaml",
        "interval": 3600,
        # The provider cannot be downloaded through a group that itself depends
        # on this provider. Force the bootstrap request to DIRECT.
        "proxy": "DIRECT",
        "header": {
            "User-Agent": ["mihomo/a-stock-evidence-radar"],
            "Accept": ["*/*"],
        },
        "health-check": {
            "enable": True,
            "url": health_url,
            "interval": 300,
            "timeout": 12000,
            "lazy": False,
            "expected-status": "200-399",
        },
        "override": {"additional-prefix": "[mergelist] "},
    }

    rules: list[str] = []
    provider_host = _provider_host(provider_url)
    if provider_host:
        rules.append(f"DOMAIN,{provider_host},DIRECT")
    rules.append("MATCH,RADAR-SELECT")

    return {
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
        "proxy-providers": {"mergelist": provider},
        "proxy-groups": [
            {
                "name": "RADAR-AUTO",
                "type": "url-test",
                "use": ["mergelist"],
                "url": health_url,
                "interval": 300,
                "timeout": 12000,
                "tolerance": 150,
                "lazy": False,
                "expected-status": "200-399",
            },
            {
                # The readiness script selects an exact node in this group only
                # after requests/OpenSSL and Playwright both pass against the
                # real Eastmoney API host.
                "name": "RADAR-SELECT",
                "type": "select",
                "proxies": ["RADAR-AUTO", "DIRECT"],
                "use": ["mergelist"],
            },
        ],
        "rules": rules,
    }


def main() -> None:
    runtime_dir = Path(os.getenv("MIHOMO_RUNTIME_DIR", "runtime/mihomo"))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "providers").mkdir(parents=True, exist_ok=True)

    config = build_config()
    output = runtime_dir / "config.yaml"
    output.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    provider_url = str(config["proxy-providers"]["mergelist"]["url"])
    socks_port = int(config["socks-port"])
    print(f"Wrote Mihomo config to {output}")
    print(f"SOCKS endpoint: socks5://127.0.0.1:{socks_port}")
    print(f"Provider host: {_provider_host(provider_url) or 'unknown'}")
    print("Provider bootstrap route: DIRECT")
    print("Runtime route: RADAR-SELECT")


if __name__ == "__main__":
    main()
