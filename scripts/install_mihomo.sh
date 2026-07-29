#!/usr/bin/env bash
set -euo pipefail

VERSION="${MIHOMO_VERSION:-v1.19.28}"
INSTALL_DIR="${MIHOMO_INSTALL_DIR:-$PWD/runtime/mihomo/bin}"
mkdir -p "$INSTALL_DIR"

case "$(uname -m)" in
  x86_64|amd64) ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 2 ;;
esac

ASSET="mihomo-linux-${ARCH}-${VERSION}.gz"
URL="https://github.com/MetaCubeX/mihomo/releases/download/${VERSION}/${ASSET}"
TMP_GZ="$(mktemp --suffix=.gz)"
trap 'rm -f "$TMP_GZ"' EXIT

curl --fail --location --silent --show-error \
  --retry 3 --retry-delay 3 --connect-timeout 20 --max-time 180 \
  "$URL" --output "$TMP_GZ"
gzip -dc "$TMP_GZ" > "$INSTALL_DIR/mihomo"
chmod +x "$INSTALL_DIR/mihomo"
"$INSTALL_DIR/mihomo" -v
