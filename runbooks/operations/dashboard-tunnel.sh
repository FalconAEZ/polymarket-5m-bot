#!/usr/bin/env bash
#
# dashboard-tunnel.sh — forward laptop ports to VPS dashboard services.
#
# Default forwards both:
#   laptop:8505 → VPS:127.0.0.1:8505   (v3 React dashboard, primary)
#   laptop:8503 → VPS:127.0.0.1:8503   (v2.1 Streamlit, /audit)
#
# Both services on the VPS bind to 127.0.0.1 only — never the public
# interface. SSH tunnel is the only access path.
#
# Run with: bash runbooks/operations/dashboard-tunnel.sh
#                    (or `make dash-tunnel`)
#
# Override defaults with env vars:
#   PMB_VPS_HOST       (default: 108.132.51.116)
#   PMB_VPS_SSH_PORT   (default: 2222)
#   PMB_VPS_USER       (default: ops)
#   PMB_VPS_ALIAS      (optional ssh config Host alias; if set, used
#                       instead of explicit -p/user/host)
#
# Per design/dashboard-v3.md §10. Quit the tunnel with Ctrl-C.

set -euo pipefail

VPS_HOST="${PMB_VPS_HOST:-108.132.51.116}"
VPS_PORT="${PMB_VPS_SSH_PORT:-2222}"
VPS_USER="${PMB_VPS_USER:-ops}"
VPS_ALIAS="${PMB_VPS_ALIAS:-}"

V3_PORT="${PMB_V3_PORT:-8505}"
V2_PORT="${PMB_V2_PORT:-8503}"

cat <<EOF
[tunnel] Forwarding two ports to ${VPS_ALIAS:-${VPS_USER}@${VPS_HOST}}:
[tunnel]   laptop:${V3_PORT}  →  127.0.0.1:${V3_PORT}   (v3 dashboard)
[tunnel]   laptop:${V2_PORT}  →  127.0.0.1:${V2_PORT}   (v2.1 audit)
[tunnel]
[tunnel] Open: http://127.0.0.1:${V3_PORT}/  (v3, primary)
[tunnel]       http://127.0.0.1:${V2_PORT}/  (v2.1, deep-dive audit)
[tunnel]
[tunnel] Press Ctrl-C to disconnect.
EOF

if [[ -n "${VPS_ALIAS}" ]]; then
  exec ssh \
    -L "${V3_PORT}:127.0.0.1:${V3_PORT}" \
    -L "${V2_PORT}:127.0.0.1:${V2_PORT}" \
    -N \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    "${VPS_ALIAS}"
else
  exec ssh \
    -p "${VPS_PORT}" \
    -L "${V3_PORT}:127.0.0.1:${V3_PORT}" \
    -L "${V2_PORT}:127.0.0.1:${V2_PORT}" \
    -N \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    "${VPS_USER}@${VPS_HOST}"
fi
