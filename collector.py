"""
Pure SSH collector – NO imports from app.py, NO database access.

All DB writes happen in app.py which calls these functions.
This eliminates the circular import / SQLAlchemy context issue entirely.
"""
import logging
import threading
from datetime import datetime
import zoneinfo

import paramiko
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from crypto_utils import decrypt_password

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)

TZ_DHAKA      = zoneinfo.ZoneInfo('Asia/Dhaka')
JUNOS_COMMAND = 'show configuration | display set | no-more'


def _today():
    return datetime.now(TZ_DHAKA).date()


# ── Scheduler singleton ───────────────────────────────────────────────────────

_scheduler: BackgroundScheduler | None = None
_schedule_time = {'hour': 2, 'minute': 0}
_app_ref       = None   # set once in start_scheduler()
_collect_fn    = None   # set once in start_scheduler() – avoids re-import inside job


def get_schedule_info() -> dict:
    h, m     = _schedule_time['hour'], _schedule_time['minute']
    next_run = None
    if _scheduler and _scheduler.running:
        job = _scheduler.get_job('daily_collect')
        if job and job.next_run_time:
            next_run = job.next_run_time.astimezone(TZ_DHAKA).strftime('%Y-%m-%d %H:%M %Z')
    return {
        'time':     f"{h:02d}:{m:02d}",
        'running':  _scheduler is not None and _scheduler.running,
        'next_run': next_run,
    }


def set_schedule_time(time_str: str):
    global _schedule_time
    try:
        h, m = map(int, time_str.split(':'))
        _schedule_time = {'hour': h, 'minute': m}
        if _scheduler and _scheduler.running:
            _scheduler.reschedule_job(
                'daily_collect',
                trigger=CronTrigger(hour=h, minute=m, timezone=TZ_DHAKA),
            )
        logger.info('Schedule updated to %02d:%02d Asia/Dhaka', h, m)
    except Exception as exc:
        logger.error('Invalid schedule time %s: %s', time_str, exc)


def start_scheduler(flask_app, collect_fn):
    """
    collect_fn: the run_collection_job function from app.py.
    Passed in explicitly so the scheduler never re-imports app.py,
    which would create a second SQLAlchemy instance and break DB access.
    """
    global _scheduler, _app_ref, _collect_fn
    _app_ref    = flask_app
    _collect_fn = collect_fn

    _scheduler = BackgroundScheduler(daemon=True)
    h, m = _schedule_time['hour'], _schedule_time['minute']
    _scheduler.add_job(
        func=_scheduled_run,
        trigger=CronTrigger(hour=h, minute=m, timezone=TZ_DHAKA),
        id='daily_collect',
        name='Daily Juniper config collection',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    job      = _scheduler.get_job('daily_collect')
    next_run = job.next_run_time.astimezone(TZ_DHAKA).strftime('%Y-%m-%d %H:%M %Z') if job else '?'
    logger.info('Scheduler started – daily at %02d:%02d Asia/Dhaka | next run: %s', h, m, next_run)


def _scheduled_run():
    """Called by APScheduler – runs collection inside the app context."""
    if _app_ref is None or _collect_fn is None:
        logger.error('Scheduler fired but app/collect_fn not initialised')
        return
    logger.info('Scheduled collection triggered at %s',
                datetime.now(TZ_DHAKA).strftime('%Y-%m-%d %H:%M %Z'))
    try:
        with _app_ref.app_context():
            results = _collect_fn()
            ok   = sum(1 for r in results if r.get('status') == 'success')
            fail = sum(1 for r in results if r.get('status') == 'failed')
            skip = sum(1 for r in results if r.get('status') == 'skipped')
            logger.info('Scheduled collection done – %d success, %d failed, %d skipped',
                        ok, fail, skip)
    except Exception as exc:
        logger.error('Scheduled collection crashed: %s', exc, exc_info=True)


# ── Pure SSH functions (no DB, no app imports) ────────────────────────────────

def ssh_collect(hostname: str, ip: str, port: int,
                username: str, enc_password: str) -> dict:
    """
    Connect via SSH and run the show command.
    Returns {'status': 'success'|'failed'|'skipped', 'content': str, 'message': str}
    """
    if not username or not enc_password:
        return {'status': 'skipped', 'message': 'No SSH credentials configured'}

    try:
        password = decrypt_password(enc_password)
    except Exception as exc:
        return {'status': 'failed', 'message': f'Credential decrypt error: {exc}'}

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        logger.info('[%s] Connecting to %s:%s', hostname, ip, port)
        client.connect(hostname=ip, port=port, username=username, password=password,
                       timeout=30, look_for_keys=False, allow_agent=False)

        _, stdout, stderr = client.exec_command(JUNOS_COMMAND, timeout=120)
        output = stdout.read().decode('utf-8', errors='replace')
        err    = stderr.read().decode('utf-8', errors='replace').strip()

        if not output.strip():
            return {'status': 'failed',
                    'message': f'Empty output. stderr: {err}' if err else 'Empty output from device'}

        logger.info('[%s] Collected %d bytes', hostname, len(output))
        return {'status': 'success', 'content': output, 'message': ''}

    except paramiko.AuthenticationException:
        return {'status': 'failed', 'message': 'SSH authentication failed – check credentials'}
    except paramiko.SSHException as exc:
        return {'status': 'failed', 'message': f'SSH error: {exc}'}
    except OSError as exc:
        return {'status': 'failed', 'message': f'Connection error: {exc}'}
    except Exception as exc:
        return {'status': 'failed', 'message': f'Unexpected error: {exc}'}
    finally:
        client.close()


def ssh_collect_steps(hostname: str, ip: str, port: int,
                      username: str, enc_password: str) -> dict:
    """
    Same as ssh_collect but returns step-by-step dict for the wizard UI.
    {'login': {...}, 'backup': {...}}
    """
    result = {
        'login':  {'status': 'pending', 'message': ''},
        'backup': {'status': 'pending', 'message': '', 'content': None},
    }

    if not username or not enc_password:
        result['login']  = {'status': 'failed',
                            'message': 'No SSH credentials configured. Set them in Collection → 🔑'}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None}
        return result

    try:
        password = decrypt_password(enc_password)
    except Exception as exc:
        result['login']  = {'status': 'failed', 'message': f'Credential decrypt error: {exc}'}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None}
        return result

    # ── Step 1: connect ───────────────────────────────────────────────────────
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        logger.info('[%s] Manual backup – connecting to %s:%s', hostname, ip, port)
        client.connect(hostname=ip, port=port, username=username, password=password,
                       timeout=30, look_for_keys=False, allow_agent=False)
        result['login'] = {'status': 'success',
                           'message': f'Authenticated as {username}@{ip}:{port}'}

    except paramiko.AuthenticationException:
        result['login']  = {'status': 'failed',
                            'message': 'Authentication failed – wrong username or password'}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None}
        client.close()
        return result
    except paramiko.SSHException as exc:
        result['login']  = {'status': 'failed', 'message': f'SSH error: {exc}'}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None}
        client.close()
        return result
    except OSError as exc:
        result['login']  = {'status': 'failed',
                            'message': f'Connection refused / unreachable: {exc}'}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None}
        client.close()
        return result
    except Exception as exc:
        result['login']  = {'status': 'failed', 'message': f'Unexpected error: {exc}'}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None}
        client.close()
        return result

    # ── Step 2: run command ───────────────────────────────────────────────────
    try:
        _, stdout, stderr = client.exec_command(JUNOS_COMMAND, timeout=120)
        output = stdout.read().decode('utf-8', errors='replace')
        err    = stderr.read().decode('utf-8', errors='replace').strip()

        if not output.strip():
            result['backup'] = {
                'status': 'failed',
                'message': f'Empty output. stderr: {err}' if err else 'Empty output from device',
                'content': None,
            }
        else:
            result['backup'] = {'status': 'success', 'message': '', 'content': output}

    except Exception as exc:
        result['backup'] = {'status': 'failed', 'message': f'Command error: {exc}', 'content': None}
    finally:
        client.close()

    return result
