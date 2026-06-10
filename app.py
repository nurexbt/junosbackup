from flask import Flask, render_template, request, jsonify, url_for, flash, redirect, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
from functools import wraps
import difflib
import logging
import os
import zoneinfo

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

TZ_DHAKA = zoneinfo.ZoneInfo('Asia/Dhaka')

def now_dhaka():
    return datetime.now(TZ_DHAKA).replace(tzinfo=None)   # store as naive local time

def today_dhaka():
    return datetime.now(TZ_DHAKA).date()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///juniper_configs.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ── Flask-Login setup ─────────────────────────────────────────────────────────

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.context_processor
def inject_globals():
    now = datetime.now(TZ_DHAKA)
    return {'now': now, 'today': now.date().isoformat(),
            'DEVICE_TYPES': DEVICE_TYPES, 'DTYPE_JUNOS': DTYPE_JUNOS, 'DTYPE_HUAWEI': DTYPE_HUAWEI}


# ── Role constants ─────────────────────────────────────────────────────────────

ROLE_SUPER_ADMIN = 'super_admin'
ROLE_ADMIN       = 'admin'
ROLE_READ_ONLY   = 'read_only'

ROLE_LABELS = {
    ROLE_SUPER_ADMIN: 'Super Admin',
    ROLE_ADMIN:       'Admin',
    ROLE_READ_ONLY:   'Read Only',
}

# ── Role decorators ───────────────────────────────────────────────────────────

def roles_required(*roles):
    """Restrict a route to users with one of the given roles."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def admin_or_super():
    """Shortcut: admin OR super_admin allowed."""
    return roles_required(ROLE_ADMIN, ROLE_SUPER_ADMIN)


# ── Models ────────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(64), unique=True, nullable=False)
    display_name = db.Column(db.String(128))
    password_hash= db.Column(db.String(256), nullable=False)
    role         = db.Column(db.String(32), nullable=False, default=ROLE_READ_ONLY)
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    last_login   = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    def to_dict(self):
        return {
            'id':           self.id,
            'username':     self.username,
            'display_name': self.display_name or '',
            'role':         self.role,
            'role_label':   self.role_label,
            'is_active':    self.is_active,
            'created_at':   self.created_at.isoformat(),
            'last_login':   self.last_login.isoformat() if self.last_login else None,
        }


# ── Device type constants ─────────────────────────────────────────────────────
DTYPE_JUNOS   = 'junos'
DTYPE_HUAWEI  = 'huawei'

DEVICE_TYPES = {
    DTYPE_JUNOS:  'Junos',
    DTYPE_HUAWEI: 'Huawei Switch',
}


class Device(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    hostname     = db.Column(db.String(128), unique=True, nullable=False)
    ip_address   = db.Column(db.String(45),  nullable=False)
    device_type  = db.Column(db.String(32),  nullable=False, default=DTYPE_JUNOS)
    model        = db.Column(db.String(64))
    location     = db.Column(db.String(128))
    description  = db.Column(db.Text)
    # SSH/Telnet credentials (password stored encrypted via Fernet)
    ssh_username = db.Column(db.String(128))
    ssh_password = db.Column(db.Text)          # Fernet-encrypted
    ssh_port     = db.Column(db.Integer, default=22)
    ssh_enabled  = db.Column(db.Boolean, default=False)
    # Telnet (Huawei)
    telnet_port  = db.Column(db.Integer, default=23)
    use_telnet   = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    configs      = db.relationship('Config',    backref='device', lazy=True, cascade='all, delete-orphan')
    collect_logs = db.relationship('CollectLog', backref='device', lazy=True, cascade='all, delete-orphan')

    @property
    def device_type_label(self):
        return DEVICE_TYPES.get(self.device_type, self.device_type)

    def to_dict(self):
        return {
            'id':           self.id,
            'hostname':     self.hostname,
            'ip_address':   self.ip_address,
            'device_type':  self.device_type,
            'device_type_label': self.device_type_label,
            'model':        self.model or '',
            'location':     self.location or '',
            'description':  self.description or '',
            'ssh_username': self.ssh_username or '',
            'ssh_port':     self.ssh_port or 22,
            'ssh_enabled':  self.ssh_enabled,
            'telnet_port':  self.telnet_port or 23,
            'use_telnet':   self.use_telnet,
            'created_at':   self.created_at.isoformat(),
            'config_count': len(self.configs),
        }


class Config(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    device_id   = db.Column(db.Integer, db.ForeignKey('device.id'), nullable=False)
    config_date = db.Column(db.Date,    nullable=False, default=date.today)
    content     = db.Column(db.Text,    nullable=False)
    note        = db.Column(db.String(256))
    source      = db.Column(db.String(32), default='manual')   # 'manual' | 'auto'
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':              self.id,
            'device_id':       self.device_id,
            'device_hostname': self.device.hostname,
            'config_date':     self.config_date.isoformat(),
            'note':            self.note or '',
            'source':          self.source or 'manual',
            'created_at':      self.created_at.isoformat(),
            'size':            len(self.content),
        }


class CollectLog(db.Model):
    """One row per device per collection run."""
    id         = db.Column(db.Integer, primary_key=True)
    device_id  = db.Column(db.Integer, db.ForeignKey('device.id'), nullable=False)
    run_at     = db.Column(db.DateTime, default=datetime.utcnow)
    status     = db.Column(db.String(16))   # 'success' | 'failed' | 'skipped'
    message    = db.Column(db.Text)
    config_id  = db.Column(db.Integer, db.ForeignKey('config.id'), nullable=True)

    def to_dict(self):
        return {
            'id':        self.id,
            'device_id': self.device_id,
            'hostname':  self.device.hostname,
            'run_at':    self.run_at.isoformat(),
            'status':    self.status,
            'message':   self.message or '',
            'config_id': self.config_id,
        }


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            user.last_login = now_dhaka()
            db.session.commit()
            login_user(user, remember=True)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            error = 'Invalid username or password.'
    return render_template('login.html', error=error)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ── Page routes ───────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    import psutil
    devices       = Device.query.order_by(Device.hostname).all()
    total_configs = Config.query.count()
    today_configs = Config.query.filter_by(config_date=today_dhaka()).count()
    recent_logs   = CollectLog.query.order_by(CollectLog.run_at.desc()).limit(20).all()

    junos_count  = Device.query.filter_by(device_type=DTYPE_JUNOS).count()
    huawei_count = Device.query.filter_by(device_type=DTYPE_HUAWEI).count()

    # System metrics
    cpu_pct  = psutil.cpu_percent(interval=0.5)
    ram      = psutil.virtual_memory()
    disk     = psutil.disk_usage('/')
    sys_info = {
        'cpu_pct':    round(cpu_pct, 1),
        'ram_pct':    round(ram.percent, 1),
        'ram_used':   round(ram.used  / (1024**3), 1),
        'ram_total':  round(ram.total / (1024**3), 1),
        'disk_pct':   round(disk.percent, 1),
        'disk_used':  round(disk.used  / (1024**3), 1),
        'disk_total': round(disk.total / (1024**3), 1),
    }

    return render_template('index.html', devices=devices,
                           total_configs=total_configs,
                           today_configs=today_configs,
                           recent_logs=recent_logs,
                           junos_count=junos_count,
                           huawei_count=huawei_count,
                           sys_info=sys_info)


@app.route('/api/system/stats')
@login_required
def api_system_stats():
    """Live system metrics polled by the dashboard."""
    import psutil
    cpu_pct = psutil.cpu_percent(interval=0.5)
    ram     = psutil.virtual_memory()
    disk    = psutil.disk_usage('/')
    return jsonify({
        'cpu_pct':    round(cpu_pct, 1),
        'ram_pct':    round(ram.percent, 1),
        'ram_used':   round(ram.used  / (1024**3), 1),
        'ram_total':  round(ram.total / (1024**3), 1),
        'disk_pct':   round(disk.percent, 1),
        'disk_used':  round(disk.used  / (1024**3), 1),
        'disk_total': round(disk.total / (1024**3), 1),
    })


@app.route('/devices')
@login_required
def devices():
    all_devices = Device.query.order_by(Device.hostname).all()
    return render_template('devices.html', devices=all_devices)


@app.route('/devices/<int:device_id>')
@login_required
def device_detail(device_id):
    device  = Device.query.get_or_404(device_id)
    configs = Config.query.filter_by(device_id=device_id)\
                          .order_by(Config.config_date.desc()).all()
    logs    = CollectLog.query.filter_by(device_id=device_id)\
                              .order_by(CollectLog.run_at.desc()).limit(30).all()
    return render_template('device_detail.html', device=device,
                           configs=configs, logs=logs)


@app.route('/configs/<int:config_id>')
@login_required
def config_view(config_id):
    config = Config.query.get_or_404(config_id)
    return render_template('config_view.html', config=config)


@app.route('/configs/<int:config_id>/download')
@login_required
def download_config(config_id):
    from flask import Response
    config = Config.query.get_or_404(config_id)
    filename = f"{config.device.hostname}_{config.config_date}.txt"
    return Response(
        config.content,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@app.route('/diff')
@login_required
def diff_page():
    devices = Device.query.order_by(Device.hostname).all()
    return render_template('diff.html', devices=devices)


@app.route('/collect')
@login_required
def collect_page():
    devices = Device.query.order_by(Device.hostname).all()
    logs    = CollectLog.query.order_by(CollectLog.run_at.desc()).limit(50).all()
    from collector import get_schedule_info
    schedule = get_schedule_info()
    return render_template('collect.html', devices=devices,
                           logs=logs, schedule=schedule)


# ── User Manager page ─────────────────────────────────────────────────────────

@app.route('/users')
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def user_manager():
    users = User.query.order_by(User.created_at).all()
    return render_template('users.html',
                           users=users,
                           ROLE_LABELS=ROLE_LABELS,
                           ROLE_SUPER_ADMIN=ROLE_SUPER_ADMIN,
                           ROLE_ADMIN=ROLE_ADMIN,
                           ROLE_READ_ONLY=ROLE_READ_ONLY)


# ── API: Users ─────────────────────────────────────────────────────────────────

@app.route('/api/users', methods=['GET'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_get_users():
    return jsonify([u.to_dict() for u in User.query.order_by(User.created_at).all()])


@app.route('/api/users', methods=['POST'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_create_user():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role     = data.get('role', ROLE_READ_ONLY)

    if not username or not password:
        return jsonify({'error': 'Username and password are required.'}), 400
    if role not in (ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_READ_ONLY):
        return jsonify({'error': 'Invalid role.'}), 400
    # Admin cannot create Super Admin
    if current_user.role == ROLE_ADMIN and role == ROLE_SUPER_ADMIN:
        return jsonify({'error': 'Admins cannot create Super Admin users.'}), 403
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists.'}), 409

    user = User(
        username     = username,
        display_name = data.get('display_name', '').strip() or username,
        role         = role,
        is_active    = True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_update_user(user_id):
    target = User.query.get_or_404(user_id)
    data   = request.get_json() or {}

    # Admin cannot edit a Super Admin
    if current_user.role == ROLE_ADMIN and target.role == ROLE_SUPER_ADMIN:
        return jsonify({'error': 'Admins cannot edit Super Admin users.'}), 403
    # Admin cannot promote to Super Admin
    new_role = data.get('role', target.role)
    if current_user.role == ROLE_ADMIN and new_role == ROLE_SUPER_ADMIN:
        return jsonify({'error': 'Admins cannot assign the Super Admin role.'}), 403

    if 'display_name' in data:
        target.display_name = data['display_name'].strip()
    if 'role' in data:
        if new_role not in (ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_READ_ONLY):
            return jsonify({'error': 'Invalid role.'}), 400
        target.role = new_role
    if 'is_active' in data:
        # Prevent deactivating yourself
        if target.id == current_user.id:
            return jsonify({'error': 'You cannot deactivate your own account.'}), 400
        target.is_active = bool(data['is_active'])
    if data.get('password'):
        target.set_password(data['password'])

    # Prevent username change conflicts
    if 'username' in data:
        new_username = data['username'].strip()
        if new_username != target.username:
            if User.query.filter_by(username=new_username).first():
                return jsonify({'error': 'Username already taken.'}), 409
            target.username = new_username

    db.session.commit()
    return jsonify(target.to_dict())


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_delete_user(user_id):
    target = User.query.get_or_404(user_id)
    # Cannot delete yourself
    if target.id == current_user.id:
        return jsonify({'error': 'You cannot delete your own account.'}), 400
    # Admin cannot delete Super Admin
    if current_user.role == ROLE_ADMIN and target.role == ROLE_SUPER_ADMIN:
        return jsonify({'error': 'Admins cannot delete Super Admin users.'}), 403
    db.session.delete(target)
    db.session.commit()
    return jsonify({'message': 'User deleted.'})


# ── API: Devices ──────────────────────────────────────────────────────────────

@app.route('/api/devices', methods=['GET'])
@login_required
def api_get_devices():
    return jsonify([d.to_dict() for d in Device.query.order_by(Device.hostname).all()])


@app.route('/api/devices', methods=['POST'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_create_device():
    data = request.get_json()
    if not data or not data.get('hostname') or not data.get('ip_address'):
        return jsonify({'error': 'hostname and ip_address are required'}), 400
    if Device.query.filter_by(hostname=data['hostname']).first():
        return jsonify({'error': 'Device with this hostname already exists'}), 409
    dtype = data.get('device_type', DTYPE_JUNOS)
    if dtype not in DEVICE_TYPES:
        return jsonify({'error': f'Invalid device_type. Choose: {list(DEVICE_TYPES.keys())}'}), 400
    device = Device(
        hostname     = data['hostname'],
        ip_address   = data['ip_address'],
        device_type  = dtype,
        model        = data.get('model', ''),
        location     = data.get('location', ''),
        description  = data.get('description', ''),
        ssh_port     = int(data.get('ssh_port', 22)),
        telnet_port  = int(data.get('telnet_port', 23)),
        use_telnet   = bool(data.get('use_telnet', False)),
    )
    _set_credentials(device, data)
    db.session.add(device)
    db.session.commit()
    return jsonify(device.to_dict()), 201


@app.route('/api/devices/<int:device_id>', methods=['PUT'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_update_device(device_id):
    device = Device.query.get_or_404(device_id)
    data   = request.get_json()
    for field in ('hostname', 'ip_address', 'model', 'location', 'description'):
        if field in data:
            setattr(device, field, data[field])
    if 'device_type' in data:
        if data['device_type'] not in DEVICE_TYPES:
            return jsonify({'error': f'Invalid device_type'}), 400
        device.device_type = data['device_type']
    if 'ssh_port' in data:
        device.ssh_port = int(data['ssh_port'])
    _set_credentials(device, data)
    db.session.commit()
    return jsonify(device.to_dict())


@app.route('/api/devices/<int:device_id>', methods=['DELETE'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_delete_device(device_id):
    device = Device.query.get_or_404(device_id)
    db.session.delete(device)
    db.session.commit()
    return jsonify({'message': 'Device deleted'})


# ── API: Device CSV Export ────────────────────────────────────────────────────

@app.route('/api/devices/export.csv', methods=['GET'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_export_devices():
    """Export all devices as a CSV file."""
    import csv
    import io
    from flask import Response

    devices = Device.query.order_by(Device.hostname).all()

    output = io.StringIO()
    writer = csv.writer(output)
    # Header row
    writer.writerow([
        'hostname', 'ip_address', 'device_type', 'model',
        'location', 'description', 'ssh_username',
        'ssh_port', 'telnet_port', 'use_telnet', 'ssh_enabled',
    ])
    for d in devices:
        writer.writerow([
            d.hostname,
            d.ip_address,
            d.device_type,
            d.model or '',
            d.location or '',
            d.description or '',
            d.ssh_username or '',
            d.ssh_port or 22,
            d.telnet_port or 23,
            '1' if d.use_telnet else '0',
            '1' if d.ssh_enabled else '0',
        ])

    csv_bytes = output.getvalue().encode('utf-8-sig')  # BOM for Excel compatibility
    return Response(
        csv_bytes,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename="devices_export.csv"'},
    )


# ── API: Device CSV Import ────────────────────────────────────────────────────

@app.route('/api/devices/import', methods=['POST'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_import_devices():
    """
    Import devices from a CSV file.
    Required columns : hostname, ip_address
    Optional columns : device_type, model, location, description,
                       ssh_username, ssh_port, telnet_port, use_telnet, ssh_enabled
    Behaviour: existing hostname → update; new hostname → insert.
    """
    import csv
    import io

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded.'}), 400

    f = request.files['file']
    if not f.filename.lower().endswith('.csv'):
        return jsonify({'error': 'Only .csv files are accepted.'}), 400

    try:
        content = f.read().decode('utf-8-sig')   # handle BOM
    except Exception:
        return jsonify({'error': 'Could not decode file. Make sure it is UTF-8.'}), 400

    reader = csv.DictReader(io.StringIO(content))
    # Normalise header names (strip whitespace, lowercase)
    if reader.fieldnames is None:
        return jsonify({'error': 'CSV file appears to be empty.'}), 400

    required = {'hostname', 'ip_address'}
    headers  = {h.strip().lower() for h in reader.fieldnames}
    missing  = required - headers
    if missing:
        return jsonify({'error': f'Missing required columns: {", ".join(sorted(missing))}'}), 400

    inserted = 0
    updated  = 0
    errors   = []

    for row_num, raw_row in enumerate(reader, start=2):   # row 1 = header
        row = {k.strip().lower(): (v or '').strip() for k, v in raw_row.items()}

        hostname   = row.get('hostname', '').strip()
        ip_address = row.get('ip_address', '').strip()

        if not hostname or not ip_address:
            errors.append(f'Row {row_num}: hostname and ip_address are required.')
            continue

        device_type = row.get('device_type', DTYPE_JUNOS).strip()
        if device_type not in DEVICE_TYPES:
            device_type = DTYPE_JUNOS

        try:
            ssh_port    = int(row.get('ssh_port', 22) or 22)
            telnet_port = int(row.get('telnet_port', 23) or 23)
        except ValueError:
            errors.append(f'Row {row_num}: ssh_port / telnet_port must be integers.')
            continue

        use_telnet  = row.get('use_telnet', '0') in ('1', 'true', 'yes')
        ssh_enabled = row.get('ssh_enabled', '0') in ('1', 'true', 'yes')

        existing = Device.query.filter_by(hostname=hostname).first()
        if existing:
            existing.ip_address  = ip_address
            existing.device_type = device_type
            existing.model       = row.get('model', existing.model or '')
            existing.location    = row.get('location', existing.location or '')
            existing.description = row.get('description', existing.description or '')
            existing.ssh_port    = ssh_port
            existing.telnet_port = telnet_port
            existing.use_telnet  = use_telnet
            if row.get('ssh_username'):
                existing.ssh_username = row['ssh_username']
                existing.ssh_enabled  = True
            else:
                existing.ssh_enabled = ssh_enabled
            updated += 1
        else:
            device = Device(
                hostname    = hostname,
                ip_address  = ip_address,
                device_type = device_type,
                model       = row.get('model', ''),
                location    = row.get('location', ''),
                description = row.get('description', ''),
                ssh_username= row.get('ssh_username', ''),
                ssh_port    = ssh_port,
                telnet_port = telnet_port,
                use_telnet  = use_telnet,
                ssh_enabled = ssh_enabled or bool(row.get('ssh_username')),
            )
            db.session.add(device)
            inserted += 1

    if errors and inserted == 0 and updated == 0:
        return jsonify({'error': 'No valid rows found.', 'row_errors': errors}), 400

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': f'Database error: {exc}'}), 500

    return jsonify({
        'inserted':   inserted,
        'updated':    updated,
        'row_errors': errors,
        'message':    f'Import complete: {inserted} added, {updated} updated'
                      + (f', {len(errors)} row(s) skipped.' if errors else '.'),
    })


def _set_credentials(device, data):
    """Encrypt and store SSH/Telnet credentials if provided."""
    from crypto_utils import encrypt_password
    if data.get('ssh_username'):
        device.ssh_username = data['ssh_username']
    if data.get('ssh_password'):
        device.ssh_password = encrypt_password(data['ssh_password'])
    if 'ssh_enabled' in data:
        device.ssh_enabled = bool(data['ssh_enabled'])
    if 'telnet_port' in data:
        device.telnet_port = int(data['telnet_port'])
    if 'use_telnet' in data:
        device.use_telnet = bool(data['use_telnet'])
    # Auto-enable SSH/Telnet when credentials provided
    if data.get('ssh_username') or data.get('ssh_password'):
        if not device.use_telnet:
            device.ssh_enabled = True


# ── API: Configs ──────────────────────────────────────────────────────────────

@app.route('/api/configs', methods=['GET'])
@login_required
def api_get_configs():
    device_id = request.args.get('device_id', type=int)
    query = Config.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    return jsonify([c.to_dict() for c in query.order_by(Config.config_date.desc()).all()])


@app.route('/api/configs', methods=['POST'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_create_config():
    data = request.get_json()
    if not data or not data.get('device_id') or not data.get('content'):
        return jsonify({'error': 'device_id and content are required'}), 400
    device = Device.query.get(data['device_id'])
    if not device:
        return jsonify({'error': 'Device not found'}), 404
    config_date = date.today()
    if data.get('config_date'):
        try:
            config_date = date.fromisoformat(data['config_date'])
        except ValueError:
            return jsonify({'error': 'Invalid config_date, use YYYY-MM-DD'}), 400
    config = Config(
        device_id   = data['device_id'],
        config_date = config_date,
        content     = data['content'],
        note        = data.get('note', ''),
        source      = data.get('source', 'manual'),
    )
    db.session.add(config)
    db.session.commit()
    return jsonify(config.to_dict()), 201


@app.route('/api/configs/<int:config_id>', methods=['GET'])
@login_required
def api_get_config(config_id):
    config = Config.query.get_or_404(config_id)
    result = config.to_dict()
    result['content'] = config.content
    return jsonify(result)


@app.route('/api/configs/<int:config_id>', methods=['DELETE'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_delete_config(config_id):
    config = Config.query.get_or_404(config_id)
    db.session.delete(config)
    db.session.commit()
    return jsonify({'message': 'Config deleted'})


@app.route('/api/configs/diff', methods=['GET'])
@login_required
def api_diff_configs():
    id1 = request.args.get('id1', type=int)
    id2 = request.args.get('id2', type=int)
    if not id1 or not id2:
        return jsonify({'error': 'id1 and id2 query params required'}), 400
    c1 = Config.query.get_or_404(id1)
    c2 = Config.query.get_or_404(id2)
    diff = list(difflib.unified_diff(
        c1.content.splitlines(keepends=True),
        c2.content.splitlines(keepends=True),
        fromfile=f'{c1.device.hostname} ({c1.config_date})',
        tofile=f'{c2.device.hostname} ({c2.config_date})',
        lineterm='',
    ))
    return jsonify({'config1': c1.to_dict(), 'config2': c2.to_dict(), 'diff': ''.join(diff)})


@app.route('/api/devices/<int:device_id>/configs', methods=['GET'])
@login_required
def api_device_configs(device_id):
    Device.query.get_or_404(device_id)
    configs = Config.query.filter_by(device_id=device_id)\
                          .order_by(Config.config_date.desc()).all()
    return jsonify([c.to_dict() for c in configs])


# ── API: Collection ───────────────────────────────────────────────────────────

@app.route('/api/collect/manual/<int:device_id>', methods=['POST'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_collect_manual(device_id):
    """Manual backup with 2-step wizard response."""
    from collector import ssh_collect_steps
    device = Device.query.get_or_404(device_id)
    data   = request.get_json() or {}
    note   = data.get('note', 'manual backup')

    steps = ssh_collect_steps(
        hostname     = device.hostname,
        ip           = device.ip_address,
        port         = (device.telnet_port or 23) if device.use_telnet else (device.ssh_port or 22),
        username     = device.ssh_username or '',
        enc_password = device.ssh_password or '',
        device_type  = device.device_type or DTYPE_JUNOS,
        use_telnet   = device.use_telnet,
    )

    backup = steps['backup']
    if backup['status'] == 'success' and backup.get('content'):
        content = backup.pop('content')
        lines   = len(content.splitlines())
        cfg = Config(
            device_id   = device.id,
            config_date = today_dhaka(),
            content     = content,
            note        = note,
            source      = 'manual',
        )
        db.session.add(cfg)
        log = CollectLog(device_id=device.id, status='success',
                         message=f'Manual backup – {lines} lines')
        db.session.add(log)
        db.session.flush()
        log.config_id = cfg.id
        db.session.commit()
        backup['message']   = f'Saved {lines} lines ({max(1, len(content)//1024)} KB)'
        backup['config_id'] = cfg.id
        backup['lines']     = lines
    else:
        backup.pop('content', None)

    return jsonify(steps)


@app.route('/api/collect/run', methods=['POST'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_collect_run():
    """Collect all SSH-enabled devices (or one if device_id provided)."""
    data      = request.get_json() or {}
    device_id = data.get('device_id')
    results   = run_collection_job(device_id=device_id)
    return jsonify({'results': results})


def run_collection_job(device_id: int | None = None) -> list[dict]:
    """
    Bulk SSH/Telnet collection. Called from the route above AND from the scheduler.
    Collects all devices that have ssh_enabled=True OR use_telnet=True.
    SSH/Telnet is done in parallel threads; DB writes are serialised in the calling
    thread's app context to avoid SQLite "database is locked" errors.
    """
    import threading
    from collector import ssh_collect
    from sqlalchemy import or_

    # Include both SSH-enabled and Telnet-enabled devices
    query = Device.query.filter(
        or_(Device.ssh_enabled == True, Device.use_telnet == True)
    )
    if device_id:
        query = query.filter_by(id=device_id)
    devices = query.order_by(Device.hostname).all()

    if not devices:
        logger.info('run_collection_job: no enabled devices found')
        return [{'status': 'skipped', 'message': 'No devices with SSH or Telnet enabled'}]

    # Flatten to plain dicts – ORM objects must not cross thread boundaries
    rows = [
        {'id': d.id, 'hostname': d.hostname, 'ip_address': d.ip_address,
         'ssh_port': d.ssh_port or 22, 'ssh_username': d.ssh_username or '',
         'ssh_password': d.ssh_password or '',
         'device_type': d.device_type or DTYPE_JUNOS,
         'use_telnet': d.use_telnet,
         'telnet_port': d.telnet_port or 23}
        for d in devices
    ]

    # ── Phase 1: SSH collection in parallel (no DB access) ───────────────────
    ssh_results = {}   # row['id'] -> ssh_res dict
    lock = threading.Lock()

    def worker(row):
        res = ssh_collect(
            hostname     = row['hostname'],
            ip           = row['ip_address'],
            port         = (row['telnet_port']) if row['use_telnet'] else row['ssh_port'],
            username     = row['ssh_username'],
            enc_password = row['ssh_password'],
            device_type  = row['device_type'],
            use_telnet   = row['use_telnet'],
        )
        with lock:
            ssh_results[row['id']] = res

    threads = [threading.Thread(target=worker, args=(r,), daemon=True) for r in rows]
    for t in threads: t.start()
    for t in threads: t.join(timeout=120)

    # ── Phase 2: DB writes serialised in calling thread ───────────────────────
    results = []
    for row in rows:
        ssh_res   = ssh_results.get(row['id'], {'status': 'failed', 'message': 'Timed out'})
        config_id = None
        try:
            if ssh_res['status'] == 'success' and ssh_res.get('content'):
                content = ssh_res['content']
                cfg = Config(
                    device_id   = row['id'],
                    config_date = today_dhaka(),
                    content     = content,
                    note        = 'auto-collected',
                    source      = 'auto',
                    created_at  = now_dhaka(),
                )
                db.session.add(cfg)
                db.session.flush()   # get cfg.id before adding log
                config_id = cfg.id

            log = CollectLog(
                device_id = row['id'],
                run_at    = now_dhaka(),
                status    = ssh_res['status'],
                message   = ssh_res.get('message', ''),
                config_id = config_id,
            )
            db.session.add(log)
            db.session.commit()
            logger.info('[%s] saved – status=%s config_id=%s',
                        row['hostname'], ssh_res['status'], config_id)
        except Exception as exc:
            db.session.rollback()
            logger.error('[%s] DB write failed: %s', row['hostname'], exc)
            ssh_res = {'status': 'failed', 'message': f'DB error: {exc}'}

        results.append({
            'device_id': row['id'],
            'hostname':  row['hostname'],
            'status':    ssh_res['status'],
            'message':   ssh_res.get('message', ''),
            'config_id': config_id,
        })

    return results


@app.route('/api/collect/logs', methods=['GET'])
@login_required
def api_collect_logs():
    device_id = request.args.get('device_id', type=int)
    query = CollectLog.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    logs = query.order_by(CollectLog.run_at.desc()).limit(100).all()
    return jsonify([l.to_dict() for l in logs])


@app.route('/api/collect/schedule', methods=['POST'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_set_schedule():
    data     = request.get_json() or {}
    time_str = data.get('time', '02:00')
    from collector import set_schedule_time
    set_schedule_time(time_str)
    return jsonify({'message': f'Schedule updated to {time_str} daily'})


@app.route('/api/collect/trigger', methods=['POST'])
@login_required
@roles_required(ROLE_SUPER_ADMIN, ROLE_ADMIN)
def api_trigger_now():
    """Manually fire the scheduled job immediately (for testing)."""
    from collector import _scheduled_run
    import threading
    t = threading.Thread(target=_scheduled_run, daemon=True)
    t.start()
    return jsonify({'message': 'Scheduled collection triggered manually'})


# ── Error handlers ─────────────────────────────────────────────────────────────

@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403


# ── Bootstrap DB ──────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    # Seed default super admin if no users exist
    if User.query.count() == 0:
        default = User(
            username     = 'teamzero',
            display_name = 'Team Zero',
            role         = ROLE_SUPER_ADMIN,
            is_active    = True,
        )
        default.set_password('123456')
        db.session.add(default)
        db.session.commit()
        logger.info('Default user "teamzero" created (role: super_admin)')

if __name__ == '__main__':
    # Start the background scheduler before Flask
    from collector import start_scheduler
    start_scheduler(app, run_collection_job)
    app.run(debug=False, host='0.0.0.0', port=5000)
