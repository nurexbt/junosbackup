from flask import Flask, render_template, request, jsonify, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import difflib
import os
import zoneinfo

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


@app.context_processor
def inject_globals():
    now = datetime.now(TZ_DHAKA)
    return {'now': now, 'today': now.date().isoformat()}


# ── Models ────────────────────────────────────────────────────────────────────

class Device(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    hostname    = db.Column(db.String(128), unique=True, nullable=False)
    ip_address  = db.Column(db.String(45),  nullable=False)
    model       = db.Column(db.String(64))
    location    = db.Column(db.String(128))
    description = db.Column(db.Text)
    # SSH credentials (password stored encrypted via Fernet)
    ssh_username = db.Column(db.String(128))
    ssh_password = db.Column(db.Text)          # Fernet-encrypted
    ssh_port     = db.Column(db.Integer, default=22)
    ssh_enabled  = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    configs     = db.relationship('Config',    backref='device', lazy=True, cascade='all, delete-orphan')
    collect_logs= db.relationship('CollectLog', backref='device', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id':           self.id,
            'hostname':     self.hostname,
            'ip_address':   self.ip_address,
            'model':        self.model or '',
            'location':     self.location or '',
            'description':  self.description or '',
            'ssh_username': self.ssh_username or '',
            'ssh_port':     self.ssh_port or 22,
            'ssh_enabled':  self.ssh_enabled,
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


# ── Page routes ───────────────────────────────────────────────────────────────

@app.route('/')
def index():
    devices       = Device.query.order_by(Device.hostname).all()
    total_configs = Config.query.count()
    today_configs = Config.query.filter_by(config_date=today_dhaka()).count()
    recent_logs   = CollectLog.query.order_by(CollectLog.run_at.desc()).limit(20).all()
    return render_template('index.html', devices=devices,
                           total_configs=total_configs,
                           today_configs=today_configs,
                           recent_logs=recent_logs)


@app.route('/devices')
def devices():
    all_devices = Device.query.order_by(Device.hostname).all()
    return render_template('devices.html', devices=all_devices)


@app.route('/devices/<int:device_id>')
def device_detail(device_id):
    device  = Device.query.get_or_404(device_id)
    configs = Config.query.filter_by(device_id=device_id)\
                          .order_by(Config.config_date.desc()).all()
    logs    = CollectLog.query.filter_by(device_id=device_id)\
                              .order_by(CollectLog.run_at.desc()).limit(30).all()
    return render_template('device_detail.html', device=device,
                           configs=configs, logs=logs)


@app.route('/configs/<int:config_id>')
def config_view(config_id):
    config = Config.query.get_or_404(config_id)
    return render_template('config_view.html', config=config)


@app.route('/configs/<int:config_id>/download')
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
def diff_page():
    devices = Device.query.order_by(Device.hostname).all()
    return render_template('diff.html', devices=devices)


@app.route('/collect')
def collect_page():
    devices = Device.query.order_by(Device.hostname).all()
    logs    = CollectLog.query.order_by(CollectLog.run_at.desc()).limit(50).all()
    from collector import get_schedule_info
    schedule = get_schedule_info()
    return render_template('collect.html', devices=devices,
                           logs=logs, schedule=schedule)


# ── API: Devices ──────────────────────────────────────────────────────────────

@app.route('/api/devices', methods=['GET'])
def api_get_devices():
    return jsonify([d.to_dict() for d in Device.query.order_by(Device.hostname).all()])


@app.route('/api/devices', methods=['POST'])
def api_create_device():
    data = request.get_json()
    if not data or not data.get('hostname') or not data.get('ip_address'):
        return jsonify({'error': 'hostname and ip_address are required'}), 400
    if Device.query.filter_by(hostname=data['hostname']).first():
        return jsonify({'error': 'Device with this hostname already exists'}), 409
    device = Device(
        hostname    = data['hostname'],
        ip_address  = data['ip_address'],
        model       = data.get('model', ''),
        location    = data.get('location', ''),
        description = data.get('description', ''),
        ssh_port    = int(data.get('ssh_port', 22)),
    )
    _set_credentials(device, data)
    db.session.add(device)
    db.session.commit()
    return jsonify(device.to_dict()), 201


@app.route('/api/devices/<int:device_id>', methods=['PUT'])
def api_update_device(device_id):
    device = Device.query.get_or_404(device_id)
    data   = request.get_json()
    for field in ('hostname', 'ip_address', 'model', 'location', 'description'):
        if field in data:
            setattr(device, field, data[field])
    if 'ssh_port' in data:
        device.ssh_port = int(data['ssh_port'])
    _set_credentials(device, data)
    db.session.commit()
    return jsonify(device.to_dict())


@app.route('/api/devices/<int:device_id>', methods=['DELETE'])
def api_delete_device(device_id):
    device = Device.query.get_or_404(device_id)
    db.session.delete(device)
    db.session.commit()
    return jsonify({'message': 'Device deleted'})


def _set_credentials(device, data):
    """Encrypt and store SSH credentials if provided."""
    from crypto_utils import encrypt_password
    if data.get('ssh_username'):
        device.ssh_username = data['ssh_username']
        device.ssh_enabled  = True
    if data.get('ssh_password'):
        device.ssh_password = encrypt_password(data['ssh_password'])
        device.ssh_enabled  = True
    if 'ssh_enabled' in data:
        device.ssh_enabled = bool(data['ssh_enabled'])


# ── API: Configs ──────────────────────────────────────────────────────────────

@app.route('/api/configs', methods=['GET'])
def api_get_configs():
    device_id = request.args.get('device_id', type=int)
    query = Config.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    return jsonify([c.to_dict() for c in query.order_by(Config.config_date.desc()).all()])


@app.route('/api/configs', methods=['POST'])
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
def api_get_config(config_id):
    config = Config.query.get_or_404(config_id)
    result = config.to_dict()
    result['content'] = config.content
    return jsonify(result)


@app.route('/api/configs/<int:config_id>', methods=['DELETE'])
def api_delete_config(config_id):
    config = Config.query.get_or_404(config_id)
    db.session.delete(config)
    db.session.commit()
    return jsonify({'message': 'Config deleted'})


@app.route('/api/configs/diff', methods=['GET'])
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
def api_device_configs(device_id):
    Device.query.get_or_404(device_id)
    configs = Config.query.filter_by(device_id=device_id)\
                          .order_by(Config.config_date.desc()).all()
    return jsonify([c.to_dict() for c in configs])


# ── API: Collection ───────────────────────────────────────────────────────────

@app.route('/api/collect/manual/<int:device_id>', methods=['POST'])
def api_collect_manual(device_id):
    """Manual backup with 2-step wizard response."""
    from collector import ssh_collect_steps
    device = Device.query.get_or_404(device_id)
    data   = request.get_json() or {}
    note   = data.get('note', 'manual backup')

    steps = ssh_collect_steps(
        hostname     = device.hostname,
        ip           = device.ip_address,
        port         = device.ssh_port or 22,
        username     = device.ssh_username or '',
        enc_password = device.ssh_password or '',
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
def api_collect_run():
    """Collect all SSH-enabled devices (or one if device_id provided)."""
    data      = request.get_json() or {}
    device_id = data.get('device_id')
    results   = run_collection_job(device_id=device_id)
    return jsonify({'results': results})


def run_collection_job(device_id: int | None = None) -> list[dict]:
    """
    Bulk SSH collection. Called from the route above AND from the scheduler.
    All ORM access happens in the main/calling thread's app context.
    Worker threads push their own app context for DB writes.
    """
    import threading
    from collector import ssh_collect

    query   = Device.query.filter_by(ssh_enabled=True)
    if device_id:
        query = query.filter_by(id=device_id)
    devices = query.order_by(Device.hostname).all()

    if not devices:
        return [{'status': 'skipped', 'message': 'No SSH-enabled devices found'}]

    # Flatten to plain dicts – ORM objects must not cross thread boundaries
    rows = [
        {'id': d.id, 'hostname': d.hostname, 'ip_address': d.ip_address,
         'ssh_port': d.ssh_port or 22, 'ssh_username': d.ssh_username or '',
         'ssh_password': d.ssh_password or ''}
        for d in devices
    ]

    results = []
    lock    = threading.Lock()

    def worker(row):
        ssh_res   = ssh_collect(
            hostname     = row['hostname'],
            ip           = row['ip_address'],
            port         = row['ssh_port'],
            username     = row['ssh_username'],
            enc_password = row['ssh_password'],
        )
        config_id = None
        with app.app_context():
            if ssh_res['status'] == 'success' and ssh_res.get('content'):
                content = ssh_res['content']
                cfg = Config(
                    device_id   = row['id'],
                    config_date = today_dhaka(),
                    content     = content,
                    note        = 'auto-collected',
                    source      = 'auto',
                )
                db.session.add(cfg)
                db.session.flush()
                config_id = cfg.id
            log = CollectLog(
                device_id = row['id'],
                status    = ssh_res['status'],
                message   = ssh_res.get('message', ''),
                config_id = config_id,
            )
            db.session.add(log)
            db.session.commit()

        with lock:
            results.append({
                'device_id': row['id'],
                'hostname':  row['hostname'],
                'status':    ssh_res['status'],
                'message':   ssh_res.get('message', ''),
                'config_id': config_id,
            })

    threads = [threading.Thread(target=worker, args=(r,), daemon=True) for r in rows]
    for t in threads: t.start()
    for t in threads: t.join(timeout=120)
    return results


@app.route('/api/collect/logs', methods=['GET'])
def api_collect_logs():
    device_id = request.args.get('device_id', type=int)
    query = CollectLog.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    logs = query.order_by(CollectLog.run_at.desc()).limit(100).all()
    return jsonify([l.to_dict() for l in logs])


@app.route('/api/collect/schedule', methods=['POST'])
def api_set_schedule():
    data     = request.get_json() or {}
    time_str = data.get('time', '02:00')
    from collector import set_schedule_time
    set_schedule_time(time_str)
    return jsonify({'message': f'Schedule updated to {time_str} daily'})



# ── Bootstrap DB ──────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    # Start the background scheduler before Flask
    from collector import start_scheduler
    start_scheduler(app)
    app.run(debug=False, host='0.0.0.0', port=5000)
