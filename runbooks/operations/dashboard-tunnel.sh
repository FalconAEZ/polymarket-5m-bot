#!/usr/bin/env bash
#
# dashboard-tunnel.sh — forward laptop:8503 → VPS:127.0.0.1:8503
#
# The streamlit-dashboard.service on the VPS binds to 127.0.0.1 only
# (never public). This script opens an SSH tunnel from your laptop so
# you can browse the dashboard at http://127.0.0.1:8503/ locally.
#
# Run with: bash runbooks/operations/dashboard-tunnel.sh
#                    (or `make dash-tunnel`)
#
# Override defaults with env vars:
#   PMB_VPS_HOST       (default: 108.132.51.116)
#   PMB_VPS_SSH_PORT   (default: 2222)
#   PMB_VPS_USER       (default: ops)
#   PMB_LOCAL_PORT     (default: 8503)
#   PMB_REMOTE_PORT    (default: 8503)
#
# Per design/dashboard-v2.md §10. Quit the tunnel with Ctrl-C.

set -euo pipefail

VPS_HOST="${PMB_VPS_HOST:-108.132.51.116}"
VPS_PORT="${PMB_VPS_SSH_PORT:-2222}"
VPS_USER="${PMB_VPS_USER:-ops}"
LOCAL_PORT="${PMB_LOCAL_PORT:-8503}"
REMOTE_PORT="${PMB_REMOTE_PORT:-8503}"

cat <<EOF
[tunnel] Forwarding  laptop:${LOCAL_PORT}  →  ${VPS_USER}@${VPS_HOST}:${REMOTE_PORT}
[tunnel] Dashboard:  http://127.0.0.1:${LOCAL_PORT}/
[tunnel] Press Ctrl-C to disconnect.
EOF

# -N: don't open an interactive shell; -L: local port forward.
# ServerAlive* keeps the tunnel up across short network blips.
exec ssh \
  -p "${VPS_PORT}" \
  -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
  -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  "${VPS_USER}@${VPS_HOST}"
