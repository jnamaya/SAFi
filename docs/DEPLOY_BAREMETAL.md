# Bare-metal deployment

Running SAFi directly on a host with systemd, a virtualenv and a system MySQL,
rather than in containers. This is how the public demo at
[safi.selfalignmentframework.com](https://safi.selfalignmentframework.com) runs,
and the unit files in [`deploy/systemd/`](../deploy/systemd/) are the ones it
uses.

**Docker is the easier path** and the one the [README Quick Start](../README.md)
covers. Choose bare metal when you already operate MySQL, want the app under
your existing process supervision and reverse proxy, or your environment does
not permit containers.

---

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3-venv mysql-server gcc g++
```

`gcc`/`g++` are needed because a few Python wheels build from source.

**`requirements.txt` does not install a database.** It contains
`mysql-connector-python`, the client driver your code uses to *talk to* MySQL.
The server is a separate system package — the line above.

## 2. Database

Create the database and user to match what you will put in `.env`. You do **not**
create tables: `init_db()` builds the entire schema on first start.

```bash
sudo mysql <<'SQL'
CREATE DATABASE safi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'safi'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON safi.* TO 'safi'@'localhost';
FLUSH PRIVILEGES;
SQL
```

## 3. Service user and application directory

```bash
sudo useradd --system --create-home --home-dir /home/safi --shell /usr/sbin/nologin safi
sudo mkdir -p /var/www/safi && sudo chown safi:safi /var/www/safi
sudo -u safi git clone https://github.com/jnamaya/SAFi.git /var/www/safi
```

**Make sure the service user owns its home directory.** If `/home/safi` belongs
to root, pip silently disables its cache and the embedding model fails to write
its own cache on every single load — falling back each time, with only a
misleading `Permission denied` in the logs. This is a real defect we hit on the
demo host and it is invisible until you look for it.

```bash
sudo chown -R safi:safi /home/safi
```

## 4. Virtualenv

```bash
cd /var/www/safi
sudo -u safi python3 -m venv venv
sudo -u safi ./venv/bin/pip install --upgrade pip
sudo -u safi ./venv/bin/pip install -r requirements.txt
```

Expect roughly **800 MB–1 GB**. Embeddings run locally through ONNX Runtime, so
no prompt or document text ever leaves the host.

## 5. Configuration

```bash
sudo -u safi cp .env.example .env
```

Edit `.env`. Beyond the database credentials and at least one LLM API key, four
settings matter more on bare metal than they do under Docker:

| Setting | Why |
| :--- | :--- |
| `WEB_BASE_URL` | The address users actually browse to, e.g. `https://safi.example.com`. Defaults to `http://localhost:5000`; leave it wrong and OAuth callbacks and CORS break. |
| `ALLOWED_ORIGINS` | Comma-separated, normally the same host. |
| `SAFI_ENCRYPTION_KEY` | **Without it, `crypto.py` is a passthrough and prompts, drafts and conscience ledgers are stored in plaintext.** `FLASK_ENV=production` refuses to start without it; other values do not. |
| `FLASK_ENV` | `production` enforces secret key, DB password, a login method and the encryption key. Anything else skips those checks. |

Generate the encryption key and **back it up off the host** — Fernet keys are not
recoverable, and losing one makes every encrypted column permanently unreadable:

```bash
./venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Note that `FLASK_ENV` and `SAFI_DEPLOYMENT_MODE` both accept the word
`production` and mean different things — strictness versus audience. See the
comments in `.env.example`.

## 6. Warm the embedding model

Do this before the first request, and after every venv rebuild:

```bash
cd /var/www/safi
sudo -u safi ./venv/bin/python -c \
  "from safi_app.core.services.retriever import get_shared_embedding_model as g; g(); print('model cached')"
```

Container deployments get this automatically from `docker-entrypoint.sh`, which
**systemd never runs**. Skip it and the first query to a knowledge-base-backed
agent downloads ~90 MB inside a live HTTP request, holding a lock, racing
gunicorn's 120-second timeout — presenting to the user as an indefinite hang
with nothing useful in the logs.

## 7. systemd

```bash
sudo cp deploy/systemd/safi.service /etc/systemd/system/
sudo cp deploy/systemd/safi-retention-purge.{service,timer} /etc/systemd/system/
sudo cp deploy/systemd/safi-backup.{service,timer} /etc/systemd/system/
sudo cp deploy/systemd/safi-backup-verify.{service,timer} /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now safi
sudo systemctl enable --now safi-retention-purge.timer safi-backup.timer safi-backup-verify.timer
```

Adjust `User`, `Group` and paths in the units if yours differ from
`safi`/`www-data`/`/var/www/safi`.

The retention-purge timer is not optional if you rely on the retention or legal
hold behaviour described in the compliance docs — those policies only take
effect because something runs `scripts/retention_purge.py` on a schedule. Under
Docker the `purge` compose service does this instead.

### Why one worker and many threads

`safi.service` runs `--workers 1 --threads 20 --worker-class gthread`
deliberately. SAFi keeps per-agent orchestrator state in process, and the
embedding model is a per-process singleton — four workers would load four copies
and split the cache. **Scale threads before workers**, and only add workers once
you have understood the cache implications.

## 8. Reverse proxy

The app listens on `127.0.0.1:5001` and expects a proxy to terminate TLS. This
is the demo host's Apache configuration, reduced to the essentials:

```apache
<VirtualHost *:443>
    ServerName safi.example.com

    ProxyPreserveHost On
    ProxyPass        /api/ http://127.0.0.1:5001/api/
    ProxyPassReverse /api/ http://127.0.0.1:5001/api/
    ProxyPass        /     http://127.0.0.1:5001/
    ProxyPassReverse /     http://127.0.0.1:5001/

    SSLCertificateFile    /etc/letsencrypt/live/safi.example.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/safi.example.com/privkey.pem
</VirtualHost>
```

Requires `a2enmod proxy proxy_http ssl`. nginx works equally well with a
`proxy_pass` to the same address.

`ProxyPreserveHost On` matters: the app builds OAuth callback URLs from the
incoming host, and `ProxyFix` in `safi_app/__init__.py` trusts one layer of
`X-Forwarded-*`.

**Serve over HTTPS.** Several browser APIs the front end relies on —
`crypto.randomUUID`, `navigator.clipboard` — exist only in a
[secure context](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts).
Over plain HTTP to a bare IP they are simply absent, and features fail with no
visible error. `localhost` counts as secure; `http://192.168.1.50:5000` does not.

## 9. Verify

```bash
systemctl is-active safi
curl -sI http://127.0.0.1:5001/ | head -1        # expect 200
curl -sI https://safi.example.com | head -1      # expect 200

cd /var/www/safi && sudo -u safi ./venv/bin/python -c "
from safi_app.config import Config
print('base      :', Config.WEB_BASE_URL)
print('encryption:', 'ON' if Config.ENCRYPTION_KEY else 'OFF — PLAINTEXT AT REST')
Config.validate(); print('validate  : OK')"
```

Then send a prompt in the browser. If it hangs with nothing in the logs, open
the browser console — see the secure-context note above.

## 10. Upgrading

```bash
cd /var/www/safi
sudo -u safi cp .env .env.bak-$(date +%F)
sudo -u safi git pull

# Only when requirements.txt changed. Keep the old venv for rollback:
sudo -u safi mv venv venv.old
sudo -u safi python3 -m venv venv
sudo -u safi ./venv/bin/pip install -r requirements.txt

# Re-warm after any venv rebuild (step 6)
sudo -u safi ./venv/bin/python -c \
  "from safi_app.core.services.retriever import get_shared_embedding_model as g; g()"

sudo systemctl restart safi
```

Rollback is `rm -rf venv && mv venv.old venv`, `git checkout <previous>`,
restart.

### Two traps when upgrading

**Ownership after a `git pull` run as root.** If only root holds the repository
credentials, a pull writes root-owned files into a service-user-owned tree, and
the app then cannot write `__pycache__`. Either give the service user the
credentials, or `chown -R safi:safi` the tree afterwards.

**Hand-installed packages disappear.** Anything you ever `pip install`ed
directly, rather than adding to `requirements.txt`, is gone after a venv rebuild
— and if a scheduled job needs it, that job fails silently at its next run
rather than at deploy time. Capture the set before rebuilding:

```bash
./venv/bin/pip freeze > /tmp/venv-before.txt
```

and diff it afterwards. Better: add those packages to `requirements.txt` so they
survive.

## 11. Existing FAISS indexes

Indexes are portable across upgrades. Vectors are unit-normalised
`all-MiniLM-L6-v2` embeddings, identical between the previous PyTorch stack and
the current ONNX one, so **upgrading does not require rebuilding an index**.
