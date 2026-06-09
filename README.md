# Juniper Config Manager

A web application for collecting, storing, and managing Juniper network device configurations via SSH. Supports manual and scheduled automatic backups, config diff comparison, role-based user management, and a full REST API.

## Features

- **Login system** – username/password authentication with session management
- **Role-based access control** – Super Admin, Admin, and Read Only roles
- **User Manager** – add, edit, and deactivate users from the sidebar
- **Device inventory** – add/edit/delete Juniper devices (hostname, IP, model, location)
- **SSH collection** – pull `show configuration | display set` directly from devices
- **Scheduled backups** – daily automatic collection via APScheduler (default 02:00 Asia/Dhaka)
- **Config viewer** – full config view with copy and download buttons
- **Config diff** – unified diff between any two snapshots (same or different devices)
- **Encrypted credentials** – SSH passwords stored with Fernet symmetric encryption
- **REST API** – full JSON API for automation and scripting

---

## Default Login

| Username | Password | Role |
|----------|----------|------|
| `teamzero` | `123456` | Super Admin |

The default user is created automatically on first run if no users exist. **Change the password after first login.**

---

## User Roles

| Permission | Super Admin | Admin | Read Only |
|---|:---:|:---:|:---:|
| View dashboard, devices, configs, diff | ✅ | ✅ | ✅ |
| Add / edit / delete devices | ✅ | ✅ | ❌ |
| Run SSH collection | ✅ | ✅ | ❌ |
| View User Manager page | ✅ | ✅ | ❌ |
| Add / edit / delete Admin & Read Only users | ✅ | ✅ | ❌ |
| Add / edit / delete Super Admin users | ✅ | ❌ | ❌ |

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

Or extract from a zip archive:

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

| Package | Version | Purpose |
|---|---|---|
| Flask | 3.0.3 | Web framework |
| Flask-SQLAlchemy | 3.1.1 | ORM / database layer |
| Flask-Login | 0.6.3 | Session-based authentication |
| SQLAlchemy | 2.0.30 | SQL toolkit |
| Werkzeug | 3.0.3 | Password hashing, WSGI utilities |
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
Default user "teamzero" created (role: super_admin)   ← first run only
Scheduler started – daily at 02:00 Asia/Dhaka | next run: ...
 * Serving Flask app 'app'
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://<your-server-ip>:5000
```

Open **http://localhost:5000** in your browser. You will be redirected to the login page.

Sign in with `teamzero` / `123456`, then go to **User Manager** in the sidebar to create your team accounts.

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

## Installation on Windows

### 1. System requirements

- Python 3.11+ from [python.org](https://www.python.org/downloads/) — check **"Add Python to PATH"** during install
- Git (optional) from [git-scm.com](https://git-scm.com)

Verify:

```cmd
python --version
```

---

### 2. Get the project

Clone or extract the project folder, then open a terminal in that directory.

---

### 3. Create a virtual environment

```cmd
python -m venv venv
venv\Scripts\activate
```

Your prompt should now show `(venv)`.

---

### 4. Install dependencies

```cmd
pip install -r requirements.txt
```

---

### 5. Generate the Fernet key

```cmd
python -c "from cryptography.fernet import Fernet; open('.fernet_key','wb').write(Fernet.generate_key()); print('Key generated.')"
```

---

### 6. Run the application

```cmd
venv\Scripts\python app.py
```

Open **http://localhost:5000** in your browser.

---

## REST API Reference

All API endpoints require an active login session. Unauthenticated requests are redirected to `/login`.

### Devices

| Method | Endpoint | Role required | Description |
|--------|----------|---------------|-------------|
| GET | `/api/devices` | Any | List all devices |
| POST | `/api/devices` | Admin+ | Create a device |
| PUT | `/api/devices/<id>` | Admin+ | Update a device |
| DELETE | `/api/devices/<id>` | Admin+ | Delete a device and its configs |

### Configs

| Method | Endpoint | Role required | Description |
|--------|----------|---------------|-------------|
| GET | `/api/configs?device_id=<id>` | Any | List configs (optionally filtered) |
| POST | `/api/configs` | Admin+ | Store a new config snapshot |
| GET | `/api/configs/<id>` | Any | Get a config with full content |
| DELETE | `/api/configs/<id>` | Admin+ | Delete a config snapshot |
| GET | `/api/configs/diff?id1=<id>&id2=<id>` | Any | Unified diff between two configs |
| GET | `/api/devices/<id>/configs` | Any | All configs for a device |

### Collection

| Method | Endpoint | Role required | Description |
|--------|----------|---------------|-------------|
| POST | `/api/collect/manual/<device_id>` | Admin+ | Trigger manual SSH backup |
| POST | `/api/collect/run` | Admin+ | Run collection on all SSH-enabled devices |
| GET | `/api/collect/logs` | Any | View collection logs |
| POST | `/api/collect/schedule` | Admin+ | Update the daily schedule time |
| POST | `/api/collect/trigger` | Admin+ | Fire the scheduled job immediately |

### Users

| Method | Endpoint | Role required | Description |
|--------|----------|---------------|-------------|
| GET | `/api/users` | Admin+ | List all users |
| POST | `/api/users` | Admin+ | Create a user |
| PUT | `/api/users/<id>` | Admin+ | Update a user |
| DELETE | `/api/users/<id>` | Admin+ | Delete a user |

> **Admin+** = Admin or Super Admin. Admins cannot create, edit, or delete Super Admin accounts.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `change-me-in-production` | Flask session secret / Fernet key seed |
| `DATABASE_URL` | `sqlite:///juniper_configs.db` | SQLAlchemy database URI |

---

## File Structure

```
juniper-config-manager/
├── app.py              # Flask app, routes, models, auth
├── collector.py        # SSH collection and APScheduler logic
├── crypto_utils.py     # Fernet encrypt/decrypt helpers
├── migrate_db.py       # DB migration helper
├── seed_data.py        # Sample data loader
├── requirements.txt    # Python dependencies
├── .fernet_key         # Encryption key (do NOT commit)
├── instance/
│   └── juniper_configs.db   # SQLite database (auto-created)
└── templates/
    ├── base.html        # Sidebar layout, nav, user card
    ├── login.html       # Login page
    ├── 403.html         # Forbidden error page
    ├── index.html       # Dashboard
    ├── devices.html     # Device list
    ├── device_detail.html
    ├── config_view.html
    ├── collect.html     # Collection manager
    ├── diff.html        # Config diff
    └── users.html       # User Manager
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

> The database schema is updated automatically on startup via `db.create_all()`. New tables (e.g. `user`) are added without touching existing data.
