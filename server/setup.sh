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

# ----- 6. Python venv -------------------------------------------------
if [[ ! -d "${APP_DIR}/venv" ]]; then
    echo "→ Creating Python venv + installing requirements"
    sudo -u "${APP_USER}" bash -c "cd ${APP_DIR} && python3 -m venv venv && ./venv/bin/pip install --quiet --upgrade pip && ./venv/bin/pip install --quiet -r requirements.txt"
fi

# ----- 7. Frontend build ----------------------------------------------
if [[ ! -d "${APP_DIR}/frontend/.next" ]]; then
    echo "→ Building frontend (npm ci + build)"
    sudo -u "${APP_USER}" bash -c "cd ${APP_DIR}/frontend && npm ci --quiet && npm run build"
fi

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Bootstrap done. Remaining manual steps:"
echo
echo "  1. Create ${APP_DIR}/.env (copy from your dev .env, set CYBERALERTX_PG_URL + ANTHROPIC_API_KEY)"
echo "     sudo nano ${APP_DIR}/.env"
echo "     sudo chmod 600 ${APP_DIR}/.env"
echo "     sudo chown ${APP_USER}:${APP_USER} ${APP_DIR}/.env"
echo
echo "  2. Run DB migrations + backfill:"
echo "     sudo -u ${APP_USER} ${APP_DIR}/venv/bin/python -m cyberalertx.tools.pg_migrate"
echo "     # rsync data/ from dev machine first if you want history"
echo
echo "  3. Install systemd units:"
echo "     sudo cp ${APP_DIR}/server/systemd/*.service /etc/systemd/system/"
echo "     sudo systemctl daemon-reload"
echo "     sudo systemctl enable --now cyberalertx-api cyberalertx-run cyberalertx-frontend"
echo
echo "  4. Install nginx config:"
echo "     sudo cp ${APP_DIR}/server/nginx/cyberalertx.conf /etc/nginx/sites-available/cyberalertx"
echo "     sudo ln -sf /etc/nginx/sites-available/cyberalertx /etc/nginx/sites-enabled/"
echo "     sudo rm -f /etc/nginx/sites-enabled/default"
echo "     sudo nginx -t && sudo systemctl reload nginx"
echo
echo "  5. SSL — install Cloudflare Origin Certificate at /etc/ssl/cyberalertx/origin.{crt,key}"
echo
echo "  6. Optional: install daily backup cron"
echo "     sudo cp ${APP_DIR}/server/backup.sh /usr/local/bin/cax-backup"
echo "     sudo chmod +x /usr/local/bin/cax-backup"
echo "     echo '0 3 * * * ${APP_USER} /usr/local/bin/cax-backup' | sudo tee /etc/cron.d/cax-backup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
