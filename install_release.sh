#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 ]]; then
  cat >&2 <<'EOF'
Usage:
  ./install_release.sh /path/to/git-workspace [additional options]

Example:
  ./install_release.sh /workspaces/a-stock-evidence-radar \
    --message "fix: repair Mihomo provider bootstrap"

Additional options are forwarded to scripts/update_workspace.py.
EOF
  exit 2
fi

WORKSPACE="$1"
shift
exec python3 "$SCRIPT_DIR/scripts/update_workspace.py" \
  --source "$SCRIPT_DIR" \
  --workspace "$WORKSPACE" \
  "$@"
