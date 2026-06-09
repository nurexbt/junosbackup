# Juniper Config Manager

A web application for collecting, storing, and managing Juniper network device configurations via SSH. Supports manual and scheduled automatic backups, config diff comparison, and a full REST API.

## Features

- **Device inventory** – add/edit/delete Juniper devices (hostname, IP, model, location)
- **SSH collection** – pull `show configuration | display set` directly from devices
- **Scheduled backups** – daily automatic collection via APScheduler (default 02:00 Asia/Dhaka)
- **Config viewer** – syntax-highlighted view with copy and download buttons
- **Config diff** – unified diff between any two snapshots (same or different devices)
- **Encrypted credentials** – SSH passwords stored with Fernet symmetric encryption
- **REST API** – full JSON API for automation and scripting

---

## Installation on Ubuntu

### 1. System requirements

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
```

Verify Python version (3.11+ recommended):

```bash
python3 --version
```

---

### 2. Clone the repository

```bash
git clone <your-repo-url> juniper-config-manager
cd juniper-config-manager
```

Or if you have a zip archive, extract it and enter the directory:

```bash
unzip juniper-config-manager.zip
cd juniper-config-manager
```

---

### 3. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

Your prompt should now show `(venv)`.

---

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

This installs:

| Package | Version | Purpose |
|---|---|---|
| Flask | 3.0.3 | Web framework |
| Flask-SQLAlchemy | 3.1.1 | ORM / database layer |
| SQLAlchemy | 2.0.30 | SQL toolkit |
| Werkzeug | 3.0.3 | WSGI utilities |
| paramiko | 3.4.0 | SSH client |
| APScheduler | 3.10.4 | Background job scheduler |
| cryptography | 42.0.8 | Fernet password encryption |
| requests | 2.32.3 | HTTP client |

---

### 5. Generate the Fernet encryption key

SSH passwords are stored encrypted. A key file is required before first run.

Check if `.fernet_key` already exists:

```bash
ls -la .fernet_key
```

If it does **not** exist, generate one:

```bash
python3 -c "
from cryptography.fernet import Fernet
key = Fernet.generate_key()
with open('.fernet_key', 'wb') as f:
    f.write(key)
print('Fernet key generated.')
"
```

> **Important:** Keep `.fernet_key` safe. Losing it means you cannot decrypt stored SSH passwords. Add it to `.gitignore` and never commit it.

---

### 6. Configure environment variables (optional)

The app works out of the box with defaults, but for production you should set:

```bash
export SECRET_KEY="your-strong-random-secret"
export DATABASE_URL="sqlite:///juniper_configs.db"   # default
```

To make these permanent, add them to `~/.bashrc` or use a `.env` loader.

For PostgreSQL instead of SQLite:

```bash
sudo apt install -y postgresql postgresql-contrib libpq-dev
pip install psycopg2-binary

export DATABASE_URL="postgresql://user:password@localhost/juniperdb"
```

---

### 7. Run the application

```bash
source venv/bin/activate   # if not already active
python app.py
```

Expected output:

```
Scheduler started – daily at 02:00 Asia/Dhaka | next run: ...
 * Serving Flask app 'app'
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://<your-server-ip>:5000
```

Open **http://localhost:5000** in your browser.

---

### 8. Run as a systemd service (production)

To keep the app running after logout and auto-start on reboot:

**Create the service file:**

```bash
sudo nano /etc/systemd/system/juniper-config-manager.service
```

Paste the following (adjust paths and user as needed):

```ini
[Unit]
Description=Juniper Config Manager
After=network.target

[Service]
User=your-linux-username
WorkingDirectory=/home/your-linux-username/juniper-config-manager
Environment="SECRET_KEY=your-strong-random-secret"
Environment="DATABASE_URL=sqlite:////home/your-linux-username/juniper-config-manager/instance/juniper_configs.db"
ExecStart=/home/your-linux-username/juniper-config-manager/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Enable and start the service:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable juniper-config-manager
sudo systemctl start juniper-config-manager
```

**Check status:**

```bash
sudo systemctl status juniper-config-manager
```

**View logs:**

```bash
journalctl -u juniper-config-manager -f
```

---

### 9. Expose via Nginx reverse proxy (optional)

Install Nginx:

```bash
sudo apt install -y nginx
```

Create a site config:

```bash
sudo nano /etc/nginx/sites-available/juniper-config-manager
```

```nginx
server {
    listen 80;
    server_name your-domain-or-ip;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Enable and reload:

```bash
sudo ln -s /etc/nginx/sites-available/juniper-config-manager /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

The app is now accessible on port 80.

---

## REST API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/devices` | List all devices |
| POST | `/api/devices` | Create a device |
| PUT | `/api/devices/<id>` | Update a device |
| DELETE | `/api/devices/<id>` | Delete a device and its configs |
| GET | `/api/configs?device_id=<id>` | List configs (optionally filtered) |
| POST | `/api/configs` | Store a new config snapshot |
| GET | `/api/configs/<id>` | Get a config with full content |
| DELETE | `/api/configs/<id>` | Delete a config snapshot |
| GET | `/api/configs/diff?id1=<id>&id2=<id>` | Unified diff between two configs |
| GET | `/api/devices/<id>/configs` | All configs for a device |
| POST | `/api/collect/manual/<device_id>` | Trigger manual SSH backup |
| POST | `/api/collect/run` | Run collection on all SSH-enabled devices |
| GET | `/api/collect/logs` | View collection logs |
| POST | `/api/collect/schedule` | Update the daily schedule time |

### Example: add a device and store a config

```bash
# Add a device
curl -X POST http://localhost:5000/api/devices \
  -H "Content-Type: application/json" \
  -d '{"hostname":"router-01","ip_address":"10.0.0.1","model":"MX480","location":"DC-1"}'

# Store a config snapshot
curl -X POST http://localhost:5000/api/configs \
  -H "Content-Type: application/json" \
  -d '{"device_id":1,"note":"daily backup","content":"set system host-name router-01\n..."}'
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `change-me-in-production` | Flask session secret key |
| `DATABASE_URL` | `sqlite:///juniper_configs.db` | SQLAlchemy database URI |

---

## File Structure

```
juniper-config-manager/
├── app.py              # Flask app, routes, models
├── collector.py        # SSH collection and APScheduler logic
├── crypto_utils.py     # Fernet encrypt/decrypt helpers
├── migrate_db.py       # DB migration helper
├── seed_data.py        # Sample data loader
├── requirements.txt    # Python dependencies
├── .fernet_key         # Encryption key (do NOT commit)
├── instance/
│   └── juniper_configs.db   # SQLite database (auto-created)
└── templates/          # Jinja2 HTML templates
    ├── base.html
    ├── index.html
    ├── devices.html
    ├── device_detail.html
    ├── config_view.html
    ├── collect.html
    └── diff.html
```

---

## Upgrading

```bash
cd juniper-config-manager
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart juniper-config-manager
```
