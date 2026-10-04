#!/usr/bin/env bash
# Ship this checkout to AMG's container and restart the app.
#
#   bash scripts/deploy.sh                                # to root@<amg-ip>
#   AMG_HOST=root@<scratch-ip> bash scripts/deploy.sh    # to a scratch container
#
# Run it from WSL. docs/DEPLOY-proxmox.md prepares a container the first time;
# after that, this is the whole of a deploy. It never touches the server's data
# (/var/lib/amg) or its settings (/opt/amg/app/.env).
set -euo pipefail

HOST="${AMG_HOST:-root@<amg-ip>}"
cd "$(dirname "$0")/.."
if [ ! -f pyproject.toml ] || [ ! -f deploy/amg.service ]; then
    echo "This isn't the AMG repo — run scripts/deploy.sh from inside it." >&2
    exit 1
fi

# One SSH connection for the whole deploy, so a password, if you use one, is
# asked for once rather than three times.
mkdir -p "$HOME/.ssh"
SSH=(ssh -o ControlMaster=auto -o "ControlPath=$HOME/.ssh/amg-deploy-%C" -o ControlPersist=60)

echo "→ Copying the code to $HOST"
# --delete removes files deleted here; the excluded paths are never deleted
# there. Permissions are set explicitly because everything under /mnt/c looks
# world-writable from WSL. The code ends up owned by root and read-only to the
# app, which only ever writes to /var/lib/amg.
rsync -rlt --perms --chmod=D755,F644 --delete --compress \
    --include=.env.example \
    --exclude=.env --exclude='.env.*' \
    --exclude=.git/ --exclude=.venv/ --exclude=venv/ \
    --exclude=data/ --exclude=samples/ \
    --exclude=__pycache__/ --exclude='*.pyc' --exclude='*.egg-info/' \
    --exclude=.pytest_cache/ --exclude=.claude/ \
    -e "${SSH[*]}" ./ "$HOST:/opt/amg/app/"

echo "→ Installing and restarting"
"${SSH[@]}" "$HOST" bash -s <<'REMOTE'
set -euo pipefail
cd /opt/amg/app

# Python dependencies, whenever pyproject.toml differs from the last install.
if ! cmp -s pyproject.toml /opt/amg/installed-pyproject.toml; then
    echo "  installing Python dependencies (a minute or two the first time)"
    /opt/amg/venv/bin/pip install --quiet --root-user-action=ignore --editable .
    cp pyproject.toml /opt/amg/installed-pyproject.toml
fi

# The `amg` command and the service definition travel with the code.
install -m 755 deploy/amg /usr/local/bin/amg
if ! cmp -s deploy/amg.service /etc/systemd/system/amg.service; then
    install -m 644 deploy/amg.service /etc/systemd/system/amg.service
    systemctl daemon-reload
    systemctl enable --quiet amg
fi

# The daily alerts run (8:00) and its timer.
reload=0
for unit in amg-alerts.service amg-alerts.timer; do
    if ! cmp -s "deploy/$unit" "/etc/systemd/system/$unit"; then
        install -m 644 "deploy/$unit" "/etc/systemd/system/$unit"
        reload=1
    fi
done
if [ "$reload" -eq 1 ]; then
    systemctl daemon-reload
fi
systemctl enable --quiet --now amg-alerts.timer

# The database as it was before the restart, which is when new migrations run.
# Database only, so it's small; the last ten are kept.
if [ -f /var/lib/amg/amg.sqlite3 ]; then
    /usr/local/bin/amg backup --no-files --out "/var/lib/amg/backups/before-deploy-$(date +%Y-%m-%d-%H%M%S).zip" >/dev/null
    ls -1t /var/lib/amg/backups/before-deploy-*.zip | tail -n +11 | xargs -r rm --
fi

systemctl restart amg
for _ in $(seq 30); do
    if curl -fsS -o /dev/null http://127.0.0.1:8000/healthz 2>/dev/null; then
        break
    fi
    sleep 1
done
if ! curl -fsS -o /dev/null http://127.0.0.1:8000/healthz; then
    echo "✗ AMG didn't come back up. The end of its log:" >&2
    journalctl -u amg -n 40 --no-pager >&2
    exit 1
fi
echo "✓ AMG is running"
if [ ! -f /opt/amg/app/.env ]; then
    echo "! There's no /opt/amg/app/.env yet, so receipts can't be read (docs/DEPLOY-proxmox.md, step 5)."
fi
REMOTE
