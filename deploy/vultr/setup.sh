#!/usr/bin/env bash
# Set up and run the app on a fresh Vultr Cloud Compute VM (Ubuntu 22.04+, x86_64).
# Not tested end to end: read it before running it as root on a real server.
#
#   ssh root@<vm-ip>
#   curl -fsSLO https://raw.githubusercontent.com/saumyajain2007/HTB26-Main/main/deploy/vultr/setup.sh
#   REPO_BRANCH=main bash setup.sh
#
# Then put the secrets in /opt/htb/.env (see .env.example) and `systemctl restart htb`.
# The API listens on port 8000. Put it behind Vultr's firewall group and, for HTTPS,
# a reverse proxy such as Caddy, then set HTB_SESSION_COOKIE_SECURE=true.
set -euo pipefail

REPO_URL=${REPO_URL:-https://github.com/saumyajain2007/HTB26-Main.git}
REPO_BRANCH=${REPO_BRANCH:-main}
APP_DIR=${APP_DIR:-/opt/htb}

apt-get update
apt-get install -y --no-install-recommends git curl ca-certificates build-essential
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch origin "$REPO_BRANCH" && git -C "$APP_DIR" checkout "$REPO_BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$REPO_BRANCH"
else
  git clone --branch "$REPO_BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
uv sync --all-packages

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created $APP_DIR/.env from the template. Fill in DATABASE_URL and any API keys." >&2
fi

cat > /etc/systemd/system/htb.service <<UNIT
[Unit]
Description=HTB26 app (API and workers)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/deploy/serve.sh
Restart=on-failure
RestartSec=5
Environment=HTB_DOCKING=fixture

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable htb

cat >&2 <<MSG

Next:
  1. Edit $APP_DIR/.env: DATABASE_URL (Vultr Managed Postgres or Tiger Data), keys.
  2. uv run deploy/db/migrate.py
  3. systemctl start htb      (journalctl -u htb -f for logs)
For real docking (HTB_DOCKING=vina) see app/worker/README.md and .devcontainer/docking.Dockerfile.
MSG
