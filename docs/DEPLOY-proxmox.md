# AMG — Deploying to Proxmox

How AMG gets onto the home lab, how it's updated, and how it comes back from a
backup. It follows paint-decoder's guide (`C:\projects\paint-decoder\paintdecoder-proxmox-deploy.md`)
and reuses its nginx container.

```
Phone (NordVPN) / desktop
        │  http://amg.home.arpa          (or http://<nginx-ip>:8080)
        ▼
[LXC 300 · paintdecoder-nginx]  <nginx-ip>   — one more site: amg
        │  proxies to
        ▼
[LXC 302 · amg]                 <amg-ip>:8000   — uvicorn, 2 workers
```

**What lives where on LXC 302**

| Path | What | Owned by | Survives a deploy? |
|---|---|---|---|
| `/opt/amg/app/` | The code, copied by `scripts/deploy.sh` | root, read-only to the app | Replaced every deploy |
| `/opt/amg/venv/` | Python and the dependencies | root | Updated when `pyproject.toml` changes |
| `/opt/amg/app/.env` | Your Anthropic key and preferences | root, readable by `amg` | Yes — the deploy never sends or deletes it |
| `/var/lib/amg/` | **The data**: `amg.sqlite3`, `files/` (every receipt, manual and photo you uploaded), `backups/`, `previews/` (a cache) | `amg` | Yes — outside the code, so no deploy can reach it |

The app runs as the `amg` user and can write only to `/var/lib/amg`. The code
belongs to root, so the paint-decoder trap — rsync as root leaving files the
app can't write — can't happen, and there's no `chown` step.

Commands are marked with where they run: **Proxmox host** (the `pve` shell in
the web UI), **WSL** (Ubuntu on your PC, in `/mnt/c/projects/amg`), **LXC 302**
or **LXC 300** (`pct enter 302` from the host, or `ssh root@<amg-ip>`).
A `pct enter` shell leaves `/usr/local/bin` off its `PATH`, which is where the
`amg` command lives. Step 3 fixes that for root's shell; `ssh` never needed it.

---

## 1 · Create the container

**Proxmox host.** Use the Ubuntu 24.04 template paint-decoder was built from:

```bash
pveam list local | grep ubuntu-24.04
```

```bash
pct create 302 local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst \
  --hostname amg \
  --cores 2 \
  --memory 2048 \
  --swap 1024 \
  --rootfs local-lvm:16 \
  --net0 name=eth0,bridge=vmbr0,ip=<amg-ip>/24,gw=<router-ip> \
  --nameserver 1.1.1.1 \
  --timezone America/New_York \
  --unprivileged 1 \
  --features nesting=1 \
  --onboot 1

pct start 302
pct exec 302 -- date        # must say EDT (EST in winter)
```

- **Use the template file name `pveam list` printed** if it isn't `…24.04-2…`.
- **2 GB of memory:** scans are turned into page images in memory, and two
  workers can each be doing one.
- **16 GB of disk:** every receipt, manual and photo is kept as uploaded, plus
  the backups you take on the server.
- **`--timezone`:** AMG takes "today" from the container's clock. That clock
  sets the default service date and the check that a date isn't in the future.
  If `date` doesn't show Eastern time, run
  `pct exec 302 -- timedatectl set-timezone America/New_York`.

## 2 · Let WSL log in with a key

`scripts/deploy.sh` logs in to the container as root over SSH. With a key, you
won't type a password on every deploy.

**WSL** — make a key if you don't have one, and print its **public** half:

```bash
ls ~/.ssh/id_ed25519.pub 2>/dev/null || ssh-keygen -t ed25519 -C "amg deploy"
cat ~/.ssh/id_ed25519.pub
```

**Proxmox host** — paste that one line (it starts `ssh-ed25519 AAAA…`) between
the quotes:

```bash
pct exec 302 -- bash -c "mkdir -p -m 700 /root/.ssh && echo 'ssh-ed25519 AAAA…paste…' >> /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys"
```

> Only the `.pub` line goes into the container. The file without `.pub` is
> the private half, and it never leaves your PC or goes into a document.
> Ubuntu already accepts key logins for root (`PermitRootLogin
> prohibit-password`), so `sshd_config` stays as it is.

**WSL** — check it, and accept the host key when asked:

```bash
ssh root@<amg-ip> hostname      # prints: amg
```

If the connection is refused, install the SSH server:
`pct exec 302 -- apt install -y openssh-server`.

## 3 · Prepare the container

**LXC 302** (`pct enter 302`):

```bash
apt update && apt upgrade -y
apt install -y python3-venv rsync curl tesseract-ocr tesseract-ocr-eng

# The app's own user. It owns the data and nothing else.
useradd --system --user-group --home-dir /var/lib/amg --shell /usr/sbin/nologin amg
install -d -o amg -g amg -m 750 /var/lib/amg

# The code and its Python, owned by root.
install -d -m 755 /opt/amg /opt/amg/app
python3 -m venv /opt/amg/venv

# So `pct enter` shells find the `amg` command (installed by the first deploy).
echo 'export PATH="/usr/local/sbin:/usr/local/bin:$PATH"' >> /root/.bashrc
exit
```

The app doesn't use Tesseract today, because receipts are read as images.
Phase 4 needs it to read scanned owner's manuals, so it's installed now.

## 4 · First deploy

**WSL:**

```bash
cd /mnt/c/projects/amg
bash scripts/deploy.sh
```

The script:

1. Copies the code. It never copies `.env`, `data/`, `samples/`, `.git` or
   `.venv`.
2. Installs the Python dependencies. This takes a minute or two the first time.
3. Installs `/usr/local/bin/amg` (the command-line tasks, run as the app's
   user), the systemd unit from `deploy/amg.service`, and the daily alerts
   run with its timer (`deploy/amg-alerts.*`, step 10).
4. Saves a database-only backup if a database already exists.
5. Restarts the app and waits until it answers `/healthz`.

It ends with `✓ AMG is running`, plus a note that there's no `.env` yet.
Step 5 covers that.

## 5 · Settings and the password

**LXC 302:**

```bash
cp /opt/amg/app/.env.example /opt/amg/app/.env
chown root:amg /opt/amg/app/.env && chmod 640 /opt/amg/app/.env
nano /opt/amg/app/.env          # paste your Anthropic key after ANTHROPIC_API_KEY=
amg set-password
systemctl restart amg
```

Type the key in on the server. `deploy.sh` never copies your local `.env`, on
purpose. `.env.example` explains every other setting; the defaults are right
for this server.

## 6 · Add AMG to the nginx container

**LXC 300** (`pct enter 300`). First, make paint-decoder the explicit default
site:

```bash
grep -n "listen" /etc/nginx/sites-available/paintdecoder
sed -i 's/listen 80;/listen 80 default_server;/' /etc/nginx/sites-available/paintdecoder
```

> **Why:** nginx gives a request whose name matches no site to the *first*
> site it loaded on that port, and it loads them alphabetically. Without
> `default_server`, `amg` loads before `paintdecoder`, and
> `http://<nginx-ip>` would open AMG instead of paint-decoder. That would
> also break the QR labels.

Then add AMG's site:

```bash
cat > /etc/nginx/sites-available/amg << 'EOF'
# AMG, the Automobile Maintenance Genie, on LXC 302.
upstream amg_app {
    server <amg-ip>:8000;
    keepalive 16;
}

server {
    # By name on the usual port. Also by address on 8080, for a device that
    # can't resolve amg.home.arpa (a phone on the VPN, say).
    listen 80;
    listen 8080;
    server_name amg.home.arpa;

    access_log /var/log/nginx/amg_access.log;
    error_log  /var/log/nginx/amg_error.log;

    # A batch of scanned receipts in one upload. AMG itself refuses any single
    # file over 50 MB.
    client_max_body_size 200M;

    location / {
        proxy_pass http://amg_app;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # $http_host rather than $host keeps the :8080, so any address the app
        # builds points back at the way you came in.
        proxy_set_header Host              $http_host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # No request waits on Claude, because receipts are read in the
        # background. The longest wait is a full backup download, which is
        # zipped before its first byte goes out.
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
EOF

ln -s /etc/nginx/sites-available/amg /etc/nginx/sites-enabled/amg
nginx -t && systemctl reload nginx

curl -s -H 'Host: amg.home.arpa' http://127.0.0.1/healthz; echo     # ok
curl -s http://127.0.0.1:8080/healthz; echo                          # ok
exit
```

Paint-decoder needed 600-second timeouts because it read pages inside the
request. AMG never does, so 300 seconds is generous.

## 7 · The name `amg.home.arpa`

Point `amg.home.arpa` at **<nginx-ip>**, the nginx container, not AMG's own
.232. Add it in the same place `paint-decoder.home.arpa` is defined: your
router's DNS, Pi-hole's local DNS records, or a hosts file. Check it from
Windows:

```powershell
nslookup amg.home.arpa        # → <nginx-ip>
```

Some devices on NordVPN can't resolve home names. Those use
**http://<nginx-ip>:8080**, which needs no DNS.

## 8 · Smoke test

From the desktop:

- [ ] `http://amg.home.arpa` shows AMG's sign-in, and your password works
- [ ] `http://<nginx-ip>` still shows paint-decoder
- [ ] Upload one receipt. Within a minute it waits under **To check**. That
      proves the key, the container's internet access and nginx's upload size
      in one go. Open it and check that the scan shows beside the fields
- [ ] **Back up** (footer) downloads a zip

From the phone, on NordVPN:

- [ ] `http://amg.home.arpa`, or `http://<nginx-ip>:8080`, signs in and
      shows the garage
- [ ] Upload a receipt with the camera
- [ ] *Add to Home Screen* so it opens like an app

## 9 · Backups, and one rehearsed restore

**The habit.** Every so often, open **Back up → Download a backup** and keep the
zip off the server: OneDrive, the NAS, anywhere but LXC 302. The zip holds the
database (including your login password) and every receipt, manual and photo
you uploaded. It doesn't hold `.env`, so keep your Anthropic key somewhere
yourself.

**From a shell** (**LXC 302**), the same zip:

```bash
amg backup                       # → /var/lib/amg/backups/amg-backup-<when>.zip
```

```bash
scp 'root@<amg-ip>:/var/lib/amg/backups/amg-backup-*.zip' .     # WSL: fetch them
```

Every deploy also leaves a database-only `before-deploy-<when>.zip` in
`/var/lib/amg/backups/`, keeping the last ten. For a second layer, add LXC 302
to a Proxmox backup job (*Datacenter → Backup*).

**Restoring** replaces everything, so it's a command run with the app stopped.
The database it replaces is moved into `/var/lib/amg/replaced-<when>/`, not
deleted:

```bash
# WSL
scp amg-backup-2026-10-01-2015.zip root@<amg-ip>:/tmp/
# LXC 302
systemctl stop amg
amg restore /tmp/amg-backup-2026-10-01-2015.zip --replace
systemctl start amg
```

`amg restore` checks the zip first: only the files a backup holds, a database
that passes SQLite's integrity check, and one no newer than the code. If any
check fails it changes nothing. If the backup came from older code, the
restore brings the database up to date.

**Rehearse it once.** This is Phase 3's "done when". Restore into a scratch
container that you throw away afterwards:

1. **Proxmox host:** steps 1–3 with ID **399** and a free address, e.g.
   `ip=<scratch-ip>/24` (drop `--onboot 1`). Add the SSH key as in step 2.
2. **WSL:** `AMG_HOST=root@<scratch-ip> bash scripts/deploy.sh`, then
   `scp <your backup>.zip root@<scratch-ip>:/tmp/`.
3. **LXC 399:** `systemctl stop amg && amg restore /tmp/<your backup>.zip --replace && systemctl start amg`.
   (No `.env` needed: nothing gets read.)
4. Browse `http://<scratch-ip>:8000` and sign in with your usual password,
   which came back with the database. Check that the cars and services are
   there and a receipt's scan opens.
5. **Proxmox host:** `pct stop 399 && pct destroy 399`.

**Moving what you entered locally** (Phase 1's hand-typed cars and services)
onto the server uses the same path, once:

```powershell
# Windows, in C:\projects\amg
.venv\Scripts\python -m amg.cli backup
```

```bash
# WSL
scp /mnt/c/projects/amg/data/backups/amg-backup-*.zip root@<amg-ip>:/tmp/
# then on LXC 302: systemctl stop amg, amg restore /tmp/<that zip> --replace, systemctl start amg
```

Only do this before the server has data of its own: the restore replaces it.

## 10 · Alerts

Every morning at 8:00 a systemd timer (`amg-alerts.timer`, installed by the
deploy) runs AMG's alerts:

- **A push to your phone** through ntfy, one per car, when something on it is
  newly due. Each is pushed once at each step:
  - a job, when it comes due soon and when it goes overdue
  - an inspection or registration, 30 days before it expires, in its last
    week, and the day after it expires
  - a warranty, 60 days before it ends (or the miles you drive in 60 days)
  - a recall NHTSA lists for the car. The run asks NHTSA about each car once
    a week; **Check now**, under Recalls on a car's page, asks now
  - an odometer reading, when a car's jobs fall due by mileage and its last
    reading is over two months old
- **An email on Mondays** with what each car has overdue and due soon, its
  open recalls and warranties ending, and what shops recommended. The next 12
  months of jobs, and when inspections and registrations expire, come attached
  as a calendar file.

Pushes, email and the recall check only need the container to reach the
internet, so the alerts reach you off the VPN. Pushes and email are each off
until their settings are in `.env`.

**Pushes.** Install the **ntfy** app on your phone. Pick a topic name nobody
would guess, because anyone who knows a topic on ntfy.sh can read it. On
**LXC 302**:

```bash
python3 -c "import secrets; print('amg-' + secrets.token_urlsafe(12))"
```

In the app, subscribe to that topic on the default server (ntfy.sh).

**Email.** Gmail needs an **app password**, not your Google password:

1. On your Google account, turn on 2-Step Verification if it isn't on.
2. Go to <https://myaccount.google.com/apppasswords>, make one called "AMG",
   and copy the 16 letters.

**LXC 302.** Put both in the settings file and restart:

```bash
nano /opt/amg/app/.env
#   AMG_NTFY_TOPIC=amg-…the topic…
#   AMG_SMTP_USER=you@gmail.com
#   AMG_SMTP_PASSWORD=…the app password…
systemctl restart amg
```

`.env.example` lists the rest. You don't need them for ntfy.sh and Gmail.

**Check it.** Open **Alerts** (footer):

- [ ] **Send a test push** reaches your phone.
- [ ] **Send a test email** reaches your inbox (look in spam the first time).
- [ ] Turn on alerts for each car you want watched. Turning one on starts from
      now: what's already due goes in Monday's email, not a push. **Leave a car
      off until all its old receipts are in.** Until then, AMG thinks some
      work is overdue that was really done.

The switch covers jobs, odometer readings and what shops recommended.
Inspections, registration, recalls and warranties are watched whatever it
says: they don't come from your old receipts, so they can't be wrong that way.

Then, on **LXC 302**:

```bash
amg alerts --dry-run                  # what a run would send now; sends nothing, asks NHTSA nothing
systemctl list-timers amg-alerts      # the next run, and the last
journalctl -u amg-alerts -n 30        # what the last run said
```

`amg alerts` (without `--dry-run`) runs it there and then. A run never sends
the same alert twice. The Alerts page shows when it last ran, what went out,
and why anything didn't.

**Calendar.** Google Calendar can't subscribe to AMG, because its servers can't
reach your home network. So the calendar is a file you import:

1. Get it from Monday's email, or **Alerts → Download the calendar (.ics)**.
2. In Google Calendar, go to **Settings → Import & export → Import**. Import it
   into a calendar of its own, made first under **Add calendar → Create new
   calendar**, called "Car maintenance".

To refresh it, import a newer file into the same calendar. If that adds copies
instead of moving dates, delete the calendar and import into a fresh one.

---

## Day to day

**Deploy a change** (**WSL**). Run the tests first (`.venv\Scripts\python -m pytest` on Windows):

```bash
cd /mnt/c/projects/amg && bash scripts/deploy.sh
```

A restart stops any receipt being read at that moment. Its page then offers
**Carry on reading**, and nothing already read is lost.

**Logs** (**LXC 302**): `journalctl -u amg -f`. The alerts run's: `journalctl -u amg-alerts -n 30`. nginx's are in
`/var/log/nginx/amg_error.log` on LXC 300.

**Restart** (**LXC 302**): `systemctl restart amg`.

**Change the model, or the key:** edit `/opt/amg/app/.env`, then
`systemctl restart amg`.

**Ubuntu updates** (**LXC 302**), now and then: `apt update && apt upgrade -y`.
If an upgrade ever moves Ubuntu to a new Python version, rebuild the venv:

```bash
rm -rf /opt/amg/venv /opt/amg/installed-pyproject.toml && python3 -m venv /opt/amg/venv
```

Then deploy again.

**Undo a deploy that damaged data.** A migration that *fails* leaves the
database as it was, so the snapshot only matters when one *succeeds* and does
harm.

1. Deploy the previous commit: `git checkout <commit>`, then `bash scripts/deploy.sh`.
2. Restore that deploy's `before-deploy-…zip` with `--replace`.

Do it in that order. A restore brings the database up to the code's version,
so with the new code still in place it would run the same migration again.

## Rebuild from nothing

If LXC 302 is lost, do steps 1–7 with the same ID and address. Then restore
your newest full backup as in step 9.

## When something's wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `http://<nginx-ip>` opens AMG, not paint-decoder | paint-decoder isn't `default_server` | Step 6's `sed`, then `nginx -t && systemctl reload nginx` |
| `amg.home.arpa` doesn't resolve | No DNS record, or the VPN's DNS doesn't know home names | Step 7; or use `http://<nginx-ip>:8080` |
| `502 Bad Gateway` | The app isn't running | **LXC 302:** `systemctl status amg`, `journalctl -u amg -n 50` |
| `413 Request Entity Too Large` | An upload batch over 200 MB | Upload in smaller batches, or raise `client_max_body_size` |
| A receipt fails: "No Anthropic API key is set" | No `.env`, or the key is empty | Step 5, then **Try reading it again** on the receipt |
| A receipt fails: "Couldn't reach Claude" | The container can't reach the internet | **LXC 302:** `curl -sI https://api.anthropic.com` |
| A receipt stuck reading, marked stopped | A restart or deploy during the read | **Carry on reading** |
| `amg: command not found` (`/usr/local/bin` is not included in the PATH) | A `pct enter` shell's bare `PATH` | Once: `echo 'export PATH="/usr/local/sbin:/usr/local/bin:$PATH"' >> /root/.bashrc`, then `exit` and `pct enter 302` again. Or run `/usr/local/bin/amg …` |
| "attempt to write a readonly database", or Permission denied under `/var/lib/amg` | Something ran as root against the data | `chown -R amg:amg /var/lib/amg`, restart; use the `amg` command, which refuses to run as root there |
| New services default to tomorrow's date late in the evening | The container isn't on Eastern time | `pct set 302 --timezone America/New_York`, then `pct reboot 302` |
| `deploy.sh`: "Permission denied (publickey)" | The key isn't in the container | Step 2 |
| Recalls: "Couldn't reach NHTSA's recall service" on a car's page, or "Couldn't check recalls" in the alerts run's log | NHTSA is down, or the container can't reach the internet | Nothing to do: the next run tries again. To see which, **LXC 302:** `curl -sI https://api.nhtsa.gov` |
| **Look up** beside a car's VIN: "Couldn't reach NHTSA's VIN service" | The same, for NHTSA's VIN service | Fill in the details by hand, or try later. **LXC 302:** `curl -sI https://vpic.nhtsa.dot.gov` |
| Test push: "Couldn't reach ntfy.sh" | The container can't reach the internet | **LXC 302:** `curl -sI https://ntfy.sh` |
| Test push sent, but nothing on the phone | The app isn't subscribed to that exact topic | Compare the topic on the Alerts page with the app's |
| Test email: "must be an app password" | `AMG_SMTP_PASSWORD` is your Google password, or the app password was revoked | Step 10: make a new app password |
| No email on Monday | The timer didn't run, or the send failed | Alerts page, "What went out"; **LXC 302:** `systemctl list-timers amg-alerts`, `journalctl -u amg-alerts -n 30` |
| A push for work you'd done | Its receipt isn't in AMG yet | Add the receipt. Leave a car's alerts off until its history is complete |
| `deploy.sh`: "✗ AMG didn't come back up" | The app fails at startup; the log printed below says why | Fix and redeploy; that deploy's database snapshot is in `/var/lib/amg/backups/` |
