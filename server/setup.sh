#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu 24.04 VPS for CyberAlertX.
#
# Run AS ROOT once after `ssh root@<VPS_IP>` on a clean Hetzner box.
# Adjust APP_USER / APP_DIR if you deviate from defaults.
#
# What this does:
#   1. Create non-root user with sudo + your SSH key.
#   2. Disable root SSH login.
#   3. UFW firewall (SSH/HTTP/HTTPS).
#   4. Install Python venv, Node.js 20, nginx, git, rsync.
#   5. Clone the repo (you'll be prompted for git URL).
#   It does not build or start the application: releases are built per
#   docs/operations/OPERATIONS.md.
#
# What this does NOT do (do those manually after):
#   - Configure .env (secrets — never script secrets).
#   - Install/configure SSL certs (manual or Cloudflare Origin Cert).
#   - Symlink nginx config + reload.
#   - Enable systemd services.
#   - rsync existing data/ from your dev machine.
#
# Re-run safe: every block checks before changing state.

set -euo pipefail

APP_USER="${APP_USER:-cax}"
APP_DIR="${APP_DIR:-/home/${APP_USER}/cax}"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Must run as root. Try: sudo $0" >&2
    exit 1
fi

echo "→ Bootstrapping VPS for user=${APP_USER}, app dir=${APP_DIR}"

# ----- 1. Non-root user -----------------------------------------------
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    echo "→ Creating user ${APP_USER}"
    adduser --disabled-password --gecos "" "${APP_USER}"
    usermod -aG sudo "${APP_USER}"
    # Copy root's authorized_keys to the new user.
    mkdir -p "/home/${APP_USER}/.ssh"
    cp /root/.ssh/authorized_keys "/home/${APP_USER}/.ssh/" 2>/dev/null || true
    chown -R "${APP_USER}:${APP_USER}" "/home/${APP_USER}/.ssh"
    chmod 700 "/home/${APP_USER}/.ssh"
    chmod 600 "/home/${APP_USER}/.ssh/authorized_keys" 2>/dev/null || true
    echo "  ${APP_USER} now has sudo. Add a password later via: passwd ${APP_USER}"
else
    echo "→ User ${APP_USER} already exists; skipping creation"
fi

# ----- 2. Lock down SSH -----------------------------------------------
if grep -qE '^#?PermitRootLogin' /etc/ssh/sshd_config; then
    sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
    systemctl restart sshd
    echo "→ Disabled root SSH login"
fi

# ----- 3. UFW firewall ------------------------------------------------
echo "→ Configuring UFW firewall"
ufw allow OpenSSH         >/dev/null
ufw allow 80/tcp          >/dev/null
ufw allow 443/tcp         >/dev/null
ufw --force enable        >/dev/null

# ----- 4. System packages ---------------------------------------------
echo "→ Installing system packages"
apt update -qq
apt upgrade -y -qq
apt install -y -qq nginx python3-venv git curl rsync ufw

if ! command -v node >/dev/null; then
    echo "→ Installing Node.js 20 LTS"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
    apt install -y -qq nodejs
fi
node --version

# ----- 5. Clone repo --------------------------------------------------
if [[ ! -d "${APP_DIR}/.git" ]]; then
    read -p "Git repo URL (e.g. https://github.com/USER/cyberalertx.git): " GIT_URL
    sudo -u "${APP_USER}" git clone "${GIT_URL}" "${APP_DIR}"
else
    echo "→ Repo already cloned at ${APP_DIR}"
fi

# Nothing is built in the checkout: production runs from immutable releases
# under /home/${APP_USER}/cyberalertx/releases (docs/operations/OPERATIONS.md).

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Bootstrap done. Next, follow docs/operations/OPERATIONS.md in ${APP_DIR}:"
echo
echo "  1. Create ${APP_DIR}/.env from .env.example (secrets by hand; chmod 600, owner ${APP_USER})."
echo "  2. Build the first release from a reviewed commit (§3): git archive, venv from"
echo "     requirements.lock, npm ci + build, data -> ${APP_DIR}/data, RELEASE provenance."
echo "  3. Point /home/${APP_USER}/cyberalertx/current at it; run migrations FROM the release"
echo "     (python -m cyberalertx.tools.pg_migrate) if Postgres is used."
echo "  4. Install server/systemd/* including cyberalertx-telegram.service.d/ (Telegram stays"
echo "     held: do not create STAGE_D_AUTHORIZED, do not enable its timer)."
echo "  5. nginx (server/nginx/), Cloudflare origin certificate, backup cron:"
echo "     sudo cp ${APP_DIR}/server/backup.sh /usr/local/bin/cax-backup"
echo "     echo '0 3 * * * ${APP_USER} /usr/local/bin/cax-backup' | sudo tee /etc/cron.d/cax-backup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
