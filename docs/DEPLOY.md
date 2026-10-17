# Deploying to Vultr

**How it works:** every push to `main` runs CI (backend tests, app lint, web build, Docker build).
If all of it passes, GitHub Actions copies the code + web build to the Vultr server over SSH and
restarts the stack. Caddy serves the web app at `/` and the API at `/api` on the same address.

```
GitHub push to main ─► CI green ─► rsync to /opt/runway ─► docker compose up --build ─► smoke test /api/health
                                                            ├── api   (FastAPI, :8000, internal only)
                                                            └── caddy (:80/:443 → web + /api)
```

## One-time setup (≈15 min, done once by rshah2001)

1. **Create the server** — Vultr dashboard → Deploy → Cloud Compute (Shared CPU) → **Ubuntu 24.04**,
   the smallest plan (1 vCPU / 1 GB is enough), a US region. Add **your own** SSH key so you can log
   in as root. Note the server's IP. (Claim the MLH Vultr credits first.)

2. **Prepare it** — from the repo root on your laptop:
   ```bash
   ssh root@<SERVER_IP> "bash -s -- '$(cat ~/.ssh/runway_deploy_ed25519.pub)'" < deploy/setup-server.sh
   ```
   This installs Docker, creates a `deploy` user that only GitHub Actions uses, opens ports 22/80/443,
   and creates `/opt/runway/.env` for the server's secrets.

3. **Tell GitHub where the server is** (repo variables — not secret):
   ```bash
   gh variable set VULTR_HOST --body "<SERVER_IP>"
   gh variable set VULTR_KNOWN_HOSTS --body "$(ssh-keyscan -t ed25519 <SERVER_IP> 2>/dev/null)"
   gh variable set PUBLIC_API_URL --body "http://<SERVER_IP>/api"
   ```
   The deploy SSH key is already stored as the `VULTR_SSH_KEY` repo secret.

4. **Deploy** — `gh workflow run CI/CD` (or push to `main`). Then open `http://<SERVER_IP>` (web app)
   and `http://<SERVER_IP>/api/docs` (live API docs).

## Server secrets

Secrets live only in `/opt/runway/.env` on the server — never in git or in GitHub variables:

```bash
ssh root@<SERVER_IP> 'sudo -u deploy nano /opt/runway/.env'
```

Then re-run the workflow (or push) to restart with the new values.

## Adding the domain (GoDaddy Registry)

1. Point an **A record** for the domain at the server IP.
2. In `/opt/runway/.env` set `SITE_ADDRESS="yourdomain.xyz, www.yourdomain.xyz"` — Caddy fetches HTTPS
   certificates itself. After this the bare IP no longer serves the site; use the domain.
3. `gh variable set PUBLIC_API_URL --body "https://yourdomain.xyz/api"` and redeploy. The post-deploy
   smoke test uses `PUBLIC_API_URL`, so it follows automatically.

**Live:** https://sixsevenbucksleft.vip (API: https://sixsevenbucksleft.vip/api, docs: /api/docs).

## Teammates

Point the app at the shared server to see backend changes ~1 minute after they merge:

```bash
# app/.env
EXPO_PUBLIC_API_URL=https://sixsevenbucksleft.vip/api
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Deploy job skipped | `VULTR_HOST` repo variable not set yet |
| `Host key verification failed` | Re-run the `VULTR_KNOWN_HOSTS` command from step 3 |
| Smoke test fails | `ssh root@<SERVER_IP> 'cd /opt/runway/deploy && docker compose logs --tail 50'` |
