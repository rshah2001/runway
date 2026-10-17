#!/usr/bin/env bash
# One-time setup for a fresh Vultr Ubuntu 24.04 server. From the repo root, run:
#   ssh root@<SERVER_IP> "bash -s -- '<deploy public key>'" < deploy/setup-server.sh
# After this, every push to main deploys automatically (see .github/workflows/ci.yml).
set -euo pipefail

DEPLOY_KEY="${1:?usage: setup-server.sh '<ssh public key used by GitHub Actions>'}"

apt-get update -y
apt-get install -y ca-certificates curl rsync ufw
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh

# GitHub Actions logs in as this user, never as root. Note: docker group access is root-equivalent
# on this box — acceptable for a single-purpose hackathon server.
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys
grep -qxF "$DEPLOY_KEY" /home/deploy/.ssh/authorized_keys || echo "$DEPLOY_KEY" >> /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys

install -d -o deploy -g deploy /opt/runway /opt/runway/web /opt/runway/backend /opt/runway/deploy
if [ ! -f /opt/runway/.env ]; then
  cat > /opt/runway/.env <<'ENV'
# Server secrets — edit with: sudo -u deploy nano /opt/runway/.env  (then push or re-run the deploy)
SITE_ADDRESS=:80
NESSIE_API_KEY=
NESSIE_BASE_URL=https://api.nessieisreal.com
GEMINI_API_KEY=
DATABASE_URL=
AUTH0_DOMAIN=
AUTH0_AUDIENCE=
CORS_ORIGINS=http://localhost:8081,http://localhost:19006
ENV
  chown deploy:deploy /opt/runway/.env
  chmod 600 /opt/runway/.env
fi

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "✅ Server ready. Fill in /opt/runway/.env, then push to main (or re-run the CI/CD workflow) to deploy."
