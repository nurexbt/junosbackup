# Device Backup Manager

A web-based network device configuration backup tool. Supports SSH and Telnet collection from Juniper (JunOS) and Huawei devices, manual and scheduled automatic backups, config diff comparison, CSV device import/export, role-based user management, and a full REST API.

---

## Features

- **Login system** – username/password authentication with session management
- **Role-based access control** – Super Admin, Admin, and Read Only roles
- **User Manager** – add, edit, delete users with per-role permission enforcement
- **Device inventory** – add/edit/delete devices (hostname, IP, model, location, type)
- **CSV import/export** – bulk import devices from CSV or export full inventory
- **SSH/Telnet collection** – pull `show configuration` from Juniper and Huawei devices
- **Scheduled backups** – daily automatic collection via APScheduler (default 02:00 Asia/Dhaka)
- **Config viewer** – full config view with copy and download buttons
- **Config diff** – unified diff between any two snapshots (same or different devices)
- **Encrypted credentials** – SSH/Telnet passwords stored with Fernet symmetric encryption
- **System dashboard** – live CPU, RAM, disk metrics and recent collection activity
- **REST API** – full JSON API for automation and scripting

---

## Default Login

| Username | Password | Role |
|----------|----------|------|
| `teamzero` | `123456` | Super Admin |

The default user is created automatically on first run if no users exist.  
**Change the password immediately after first login.**

---

## User Roles

| Permission | Super Admin | Admin | Read Only |
|---|:---:|:---:|:---:|
| View dashboard, devices, configs, diff | ✅ | ✅ | ✅ |
| Add / edit / delete devices | ✅ | ✅ | ❌ |
| Import / export devices via CSV | ✅ | ✅ | ❌ |
| Run SSH/Telnet collection | ✅ | ✅ | ❌ |
| View User Manager page | ✅ | ✅ | ❌ |
| Add / edit / delete Admin & Read Only users | ✅ | ✅ | ❌ |
| Add / edit / delete Super Admin users | ✅ | ❌ | ❌ |

---

## Installation on Ubuntu / Debian

### 1. System requirements

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git unzip
```

Verify Python version (3.11+ recommended):

```bash
python3 --version
```

---

### 2. Get the project

**From Git:**
```bash
git clone <your-repo-url> device-backup-manager
cd device-backup-manager
```

**From a zip archive:**
```bash
unzip device-backup-manager.zip
cd device-backup-manager
```

---

### 3. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

Your prompt will now show `(venv)`.

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
| psutil | 5.9.8 | System metrics (CPU/RAM/disk) |
| requests | 2.32.3 | HTTP client |

---

### 5. Generate the Fernet encryption key

SSH/Telnet passwords are stored encrypted. A key file is required before the first run.

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

> **Important:** Keep `.fernet_key` safe and backed up separately.  
> Losing it means stored SSH/Telnet passwords cannot be decrypted.  
> Never commit it to version control — add it to `.gitignore`.

---

### 6. Configure environment variables (optional)

The app works out of the box with defaults. For production you should set:

```bash
export SECRET_KEY="your-strong-random-secret-here"
export DATABASE_URL="sqlite:///juniper_configs.db"   # default
```

To make these permanent, add them to `~/.bashrc`:

```bash
echo 'export SECRET_KEY="your-strong-random-secret-here"' >> ~/.bashrc
source ~/.bashrc
```

---

### 7. Run the application (development)

```bash
source venv/bin/activate
python3 app.py
```

Expected output:

```
Scheduler started – daily at 02:00 Asia/Dhaka | next run: ...
 * Serving Flask app 'app'
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://<your-server-ip>:5000
```

Open **http://localhost:5000** in your browser and sign in with `teamzero` / `123456`.

---

### 8. Run as a systemd service (production)

This keeps the app running after logout and auto-starts it on server reboot.

**Create the service file:**

```bash
sudo nano /etc/systemd/system/device-backup-manager.service
```

Paste the following — adjust `User` and `WorkingDirectory` to match your setup:

```ini
[Unit]
Description=Device Backup Manager
After=network.target

[Service]
User=your-linux-username
WorkingDirectory=/home/your-linux-username/device-backup-manager
Environment="SECRET_KEY=your-strong-random-secret-here"
Environment="DATABASE_URL=sqlite:////home/your-linux-username/device-backup-manager/instance/juniper_configs.db"
ExecStart=/home/your-linux-username/device-backup-manager/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Enable and start:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable device-backup-manager
sudo systemctl start device-backup-manager
```

**Useful service commands:**

```bash
sudo systemctl status device-backup-manager   # check running status
sudo systemctl stop device-backup-manager     # stop the service
sudo systemctl restart device-backup-manager  # restart
journalctl -u device-backup-manager -f        # follow live logs
journalctl -u device-backup-manager --since "1 hour ago"  # recent logs
```

---

### 9. Expose via Nginx reverse proxy (recommended)

Install Nginx:

```bash
sudo apt install -y nginx
```

Create a site config:

```bash
sudo nano /etc/nginx/sites-available/device-backup-manager
```

```nginx
server {
    listen 80;
    server_name your-domain-or-ip;

    # Increase body size limit for CSV imports
    client_max_body_size 10M;

    location / {
        proxy_pass             http://127.0.0.1:5000;
        proxy_set_header       Host $host;
        proxy_set_header       X-Real-IP $remote_addr;
        proxy_set_header       X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout     120s;
    }
}
```

Enable and reload:

```bash
sudo ln -s /etc/nginx/sites-available/device-backup-manager /etc/nginx/sites-enabled/
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

Clone or extract the project folder, then open **Command Prompt** or **PowerShell** in that directory.

---

### 3. Create a virtual environment

```cmd
python -m venv venv
venv\Scripts\activate
```

Your prompt will now show `(venv)`.

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

## CSV Device Import / Export

### Export

Click **Export CSV** on the Devices page to download all devices as a CSV file (Excel-compatible UTF-8 with BOM).

### Import

Click **Import CSV** on the Devices page to open the import modal. You can drag-and-drop a file or click to browse. A live preview of the first 5 rows is shown before submission.

**Required columns:** `hostname`, `ip_address`

**Optional columns:** `device_type` (junos / huawei), `model`, `location`, `description`, `ssh_username`, `ssh_port`, `telnet_port`, `use_telnet` (0/1), `ssh_enabled` (0/1)

**Behaviour:**
- If a `hostname` already exists in the database → the row **updates** that device
- If the `hostname` is new → a new device is **inserted**
- Rows with missing required fields are skipped and reported

A sample template can be downloaded directly from the import modal.

---

## Updating a Deployed Server

### Standard update (Git-based deployment)

```bash
# 1. Go to the project folder
cd /home/your-linux-username/device-backup-manager

# 2. Activate the virtual environment
source venv/bin/activate

# 3. Pull latest changes
git pull origin main

# 4. Install any new or updated dependencies
pip install -r requirements.txt

# 5. Restart the service
sudo systemctl restart device-backup-manager

# 6. Verify it started cleanly
sudo systemctl status device-backup-manager
journalctl -u device-backup-manager -n 30
```

---

### Update from a zip archive (no Git)

```bash
# 1. Upload the new zip to the server (e.g. via scp)
scp device-backup-manager-v2.zip user@your-server:/tmp/

# 2. On the server — stop the running service
sudo systemctl stop device-backup-manager

# 3. Back up the current installation (database + key)
cp -r /home/your-linux-username/device-backup-manager \
       /home/your-linux-username/device-backup-manager.bak

# 4. Extract the new version
unzip /tmp/device-backup-manager-v2.zip -d /tmp/new-release

# 5. Copy new code files — preserve database and fernet key
rsync -av --exclude='instance/' \
          --exclude='.fernet_key' \
          --exclude='venv/' \
          /tmp/new-release/ \
          /home/your-linux-username/device-backup-manager/

# 6. Install any new dependencies
source /home/your-linux-username/device-backup-manager/venv/bin/activate
pip install -r /home/your-linux-username/device-backup-manager/requirements.txt

# 7. Restart the service
sudo systemctl start device-backup-manager

# 8. Confirm it is running
sudo systemctl status device-backup-manager
journalctl -u device-backup-manager -n 30
```

---

### Important notes on updates

> **Never overwrite `.fernet_key`** — replacing it will make all stored SSH/Telnet passwords unreadable. Always keep the key from the running installation.

> **Database migrations** — the app runs `db.create_all()` on startup, which automatically adds new tables and columns. Existing data is not touched. No manual migration step is needed for standard updates.

> **Rollback** — if something breaks, restore from the backup made in step 3 and restart the service:
> ```bash
> sudo systemctl stop device-backup-manager
> rm -rf /home/your-linux-username/device-backup-manager
> mv /home/your-linux-username/device-backup-manager.bak \
>    /home/your-linux-username/device-backup-manager
> sudo systemctl start device-backup-manager
> ```

---

## REST API Reference

All endpoints require an active login session. Unauthenticated requests redirect to `/login`.

### Devices

| Method | Endpoint | Role | Description |
|--------|----------|------|-------------|
| GET | `/api/devices` | Any | List all devices |
| POST | `/api/devices` | Admin+ | Create a device |
| PUT | `/api/devices/<id>` | Admin+ | Update a device |
| DELETE | `/api/devices/<id>` | Admin+ | Delete device and all its configs |
| GET | `/api/devices/export.csv` | Admin+ | Export all devices as CSV |
| POST | `/api/devices/import` | Admin+ | Import devices from CSV file upload |

### Configs

| Method | Endpoint | Role | Description |
|--------|----------|------|-------------|
| GET | `/api/configs?device_id=<id>` | Any | List configs (optionally filtered by device) |
| POST | `/api/configs` | Admin+ | Store a new config snapshot |
| GET | `/api/configs/<id>` | Any | Get a config with full content |
| DELETE | `/api/configs/<id>` | Admin+ | Delete a config snapshot |
| GET | `/api/configs/diff?id1=<id>&id2=<id>` | Any | Unified diff between two configs |
| GET | `/api/devices/<id>/configs` | Any | All configs for a specific device |

### Collection

| Method | Endpoint | Role | Description |
|--------|----------|------|-------------|
| POST | `/api/collect/manual/<device_id>` | Admin+ | Trigger manual backup for one device |
| POST | `/api/collect/run` | Admin+ | Collect all SSH/Telnet-enabled devices |
| GET | `/api/collect/logs` | Any | View collection logs |
| POST | `/api/collect/schedule` | Admin+ | Update the daily schedule time |
| POST | `/api/collect/trigger` | Admin+ | Fire the scheduled job immediately |

### Users

| Method | Endpoint | Role | Description |
|--------|----------|------|-------------|
| GET | `/api/users` | Admin+ | List all users |
| POST | `/api/users` | Admin+ | Create a user |
| PUT | `/api/users/<id>` | Admin+ | Update a user |
| DELETE | `/api/users/<id>` | Admin+ | Delete a user |

> **Admin+** = Admin or Super Admin. Admins cannot create, edit, or delete Super Admin accounts.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `change-me-in-production` | Flask session secret key |
| `DATABASE_URL` | `sqlite:///juniper_configs.db` | SQLAlchemy database URI |

---

## File Structure

```
device-backup-manager/
├── app.py                  # Flask app — routes, models, auth, API
├── collector.py            # SSH/Telnet collection and APScheduler logic
├── crypto_utils.py         # Fernet encrypt/decrypt helpers
├── migrate_db.py           # DB migration helper
├── seed_data.py            # Sample data loader
├── requirements.txt        # Python dependencies
├── .fernet_key             # Encryption key (DO NOT commit)
├── instance/
│   └── juniper_configs.db  # SQLite database (auto-created on first run)
└── templates/
    ├── base.html           # Sidebar layout, navigation, user card
    ├── login.html          # Login page
    ├── 403.html            # Forbidden error page
    ├── index.html          # Dashboard with system metrics
    ├── devices.html        # Device list with CSV import/export
    ├── device_detail.html  # Device detail and config history
    ├── config_view.html    # Full config viewer
    ├── collect.html        # Collection manager and scheduler
    ├── diff.html           # Config diff viewer
    └── users.html          # User Manager
```

---

## Security Recommendations

- Change the default `teamzero` password immediately after first login
- Set a strong random `SECRET_KEY` environment variable in production
- Keep `.fernet_key` backed up securely and out of version control
- Run behind Nginx (not directly exposed) and consider adding HTTPS via Let's Encrypt
- Restrict access to port 5000 with a firewall — only Nginx should reach it:
  ```bash
  sudo ufw allow 'Nginx Full'
  sudo ufw deny 5000
  sudo ufw enable
  ```
