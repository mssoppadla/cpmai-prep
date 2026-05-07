#!/usr/bin/env bash
# ==============================================================================
# provision.sh — one-time VPS bootstrap (root)
# ==============================================================================
# Run ONCE on a fresh Ubuntu 24.04 VPS as root. Idempotent — re-running on a
# provisioned box only fixes drift, never breaks an existing install.
#
# What it sets up:
#   • System updates + essentials (curl, git, ufw, fail2ban)
#   • Docker CE + Docker Compose plugin
#   • Caddy (reverse proxy with auto-TLS via Let's Encrypt)
#   • Firewall: allow 22 (SSH), 80, 443 — block everything else
#   • A non-root `deploy` user (in docker + sudo groups) for app management
#   • /opt/cpmai-prep        — where the app lives
#   • /var/backups/cpmai-prep — daily DB dumps
#   • /var/log/caddy          — Caddy access logs
#
# Usage:   sudo bash provision.sh
#
# After it finishes, log out of root and continue as the deploy user
# for everything else. See docs/vps-deployment.md for the next steps.
# ==============================================================================
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

# Colorless output — survives ssh + log scraping
say()  { printf '==> %s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }

DEPLOY_USER="${DEPLOY_USER:-deploy}"
APP_DIR="${APP_DIR:-/opt/cpmai-prep}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/cpmai-prep}"

# ------------------------------------------------------------------------------
# 1. Apt: update, install essentials
# ------------------------------------------------------------------------------
say "Updating apt index"
apt-get update -y
apt-get upgrade -y

say "Installing essentials (curl, git, ufw, fail2ban, debian-keyring, etc.)"
apt-get install -y \
  curl ca-certificates git ufw fail2ban \
  debian-keyring debian-archive-keyring apt-transport-https \
  unattended-upgrades software-properties-common
ok "essentials"

# Auto-install security patches
dpkg-reconfigure -plow unattended-upgrades || true

# ------------------------------------------------------------------------------
# 2. Docker
# ------------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker CE + Compose plugin"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  ARCH=$(dpkg --print-architecture)
  CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
  echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.asc] \
       https://download.docker.com/linux/ubuntu $CODENAME stable" \
       > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io \
                     docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"
else
  ok "docker already installed: $(docker --version)"
fi

# ------------------------------------------------------------------------------
# 3. Caddy (reverse proxy with auto-TLS)
# ------------------------------------------------------------------------------
if ! command -v caddy >/dev/null 2>&1; then
  say "Installing Caddy"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
  systemctl enable --now caddy
  ok "caddy installed + enabled"
else
  ok "caddy already installed: $(caddy version | head -1)"
fi

# ------------------------------------------------------------------------------
# 4. Firewall
# ------------------------------------------------------------------------------
say "Configuring ufw firewall (22, 80, 443)"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp     comment 'SSH'
ufw allow 80/tcp     comment 'HTTP (Caddy ACME challenge + 301 to https)'
ufw allow 443/tcp    comment 'HTTPS'
ufw --force enable
ok "ufw active: $(ufw status | head -1 | tr -s ' ')"

systemctl enable --now fail2ban
ok "fail2ban active"

# ------------------------------------------------------------------------------
# 5. Deploy user
# ------------------------------------------------------------------------------
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  say "Creating deploy user '$DEPLOY_USER'"
  useradd -m -s /bin/bash "$DEPLOY_USER"
  # Generate a long random password — user will switch to SSH keys
  TEMP_PW=$(tr -dc 'A-Za-z0-9!@#%^*' </dev/urandom | head -c 24 || true)
  echo "${DEPLOY_USER}:${TEMP_PW}" | chpasswd
  warn "Initial password for '$DEPLOY_USER': $TEMP_PW"
  warn "Switch to SSH keys ASAP: ssh-copy-id $DEPLOY_USER@<this-host>"
fi
usermod -aG docker "$DEPLOY_USER"
usermod -aG sudo   "$DEPLOY_USER"
# Passwordless sudo for the deploy user — required for systemctl reload caddy etc.
# Restrict if you want; the deploy user still needs a password for full sudo otherwise.
echo "${DEPLOY_USER} ALL=(ALL) NOPASSWD:ALL" \
  > "/etc/sudoers.d/90-${DEPLOY_USER}"
chmod 0440 "/etc/sudoers.d/90-${DEPLOY_USER}"
ok "user '$DEPLOY_USER' in groups: docker, sudo (NOPASSWD)"

# ------------------------------------------------------------------------------
# 6. App directories
# ------------------------------------------------------------------------------
say "Creating app + backup + log directories"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0755 "$APP_DIR"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "$BACKUP_DIR"
install -d -o caddy -g caddy -m 0755 /var/log/caddy
ok "app dir   : $APP_DIR (owned by $DEPLOY_USER)"
ok "backup dir: $BACKUP_DIR (owned by $DEPLOY_USER)"

# ------------------------------------------------------------------------------
# 7. Port-conflict check (n8n / Coolify often grabs 80/443)
# ------------------------------------------------------------------------------
if ss -ltn '( sport = :80 or sport = :443 )' 2>/dev/null \
     | awk 'NR>1' | grep -qv 'caddy'; then
  warn "Port 80 or 443 is in use by something other than Caddy."
  warn "Likely culprit: n8n / Coolify / Traefik. Caddy needs both ports."
  warn "Fix BEFORE running install_app.sh:"
  warn "  $ ss -ltnp | grep -E ':(80|443) '"
  warn "  $ docker ps                                # find the container"
  warn "  $ docker stop <id>  &&  systemctl restart caddy"
fi

# ------------------------------------------------------------------------------
# Done
# ------------------------------------------------------------------------------
echo
echo "============================================================"
echo "  ✓ Provisioning complete"
echo "============================================================"
echo
echo "Next steps:"
echo "  1. Add your SSH public key to ~${DEPLOY_USER}/.ssh/authorized_keys"
echo "     (so you can ssh in as ${DEPLOY_USER} without the password)."
echo "  2. Disable password auth + root login in /etc/ssh/sshd_config:"
echo "       PasswordAuthentication no"
echo "       PermitRootLogin no"
echo "       systemctl reload ssh"
echo "  3. Point DNS A records:"
echo "       cpmaiexamprep.com        → $(curl -fs ifconfig.me 2>/dev/null || echo 'this-vps-ip')"
echo "       www.cpmaiexamprep.com    → same"
echo "       api.cpmaiexamprep.com    → same"
echo "  4. Switch to the deploy user and run install_app.sh:"
echo "       su - ${DEPLOY_USER}"
echo "       git clone https://github.com/mssoppadla/cpmai-prep.git ${APP_DIR}"
echo "       cd ${APP_DIR}"
echo "       ./scripts/vps/install_app.sh"
