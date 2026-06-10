"""
Pure SSH/Telnet collector – NO imports from app.py, NO database access.

All DB writes happen in app.py which calls these functions.
This eliminates the circular import / SQLAlchemy context issue entirely.

Supported device types:
  junos   – SSH, command: show configuration | display set | no-more
  huawei  – SSH or Telnet, command: display current-configuration
"""
import logging
import telnetlib
import threading
import time
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

TZ_DHAKA = zoneinfo.ZoneInfo('Asia/Dhaka')

# ── Device type constants (mirrored from app.py to avoid circular import) ──────
DTYPE_JUNOS  = 'junos'
DTYPE_HUAWEI = 'huawei'

# ── Per-device-type commands ───────────────────────────────────────────────────
COLLECT_COMMANDS = {
    DTYPE_JUNOS:  'show configuration | display set | no-more',
    DTYPE_HUAWEI: 'display current-configuration',
}


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
        name='Daily config collection',
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


# ── Huawei Telnet collector ───────────────────────────────────────────────────

def _telnet_collect_huawei(hostname: str, ip: str, port: int,
                            username: str, password: str) -> dict:
    """
    Connect to a Huawei switch via Telnet and run display current-configuration.
    Returns {'status': ..., 'content': str|None, 'message': str}
    """
    TIMEOUT   = 30
    CMD_TIMEOUT = 120
    ENCODING  = 'utf-8'

    def read_until_any(tn, prompts, timeout=TIMEOUT):
        """Read until one of the prompt strings appears."""
        buf = b''
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                chunk = tn.read_very_eager()
                if chunk:
                    buf += chunk
                    for p in prompts:
                        if p.encode() in buf:
                            return buf.decode(ENCODING, errors='replace')
            except EOFError:
                break
            time.sleep(0.1)
        return buf.decode(ENCODING, errors='replace')

    tn = None
    try:
        logger.info('[%s] Telnet connecting to %s:%s', hostname, ip, port)
        tn = telnetlib.Telnet(ip, port, timeout=TIMEOUT)

        # ── Login ──────────────────────────────────────────────────────────────
        # Wait for Username prompt
        resp = read_until_any(tn, ['Username:', 'username:', 'login:', 'Login:'])
        if not any(p in resp for p in ['Username:', 'username:', 'login:', 'Login:']):
            return {'status': 'failed',
                    'message': 'No username prompt received. Check Telnet access on device.',
                    'content': None}

        tn.write(username.encode() + b'\n')
        time.sleep(0.5)

        # Wait for Password prompt
        resp = read_until_any(tn, ['Password:', 'password:'])
        if not any(p in resp for p in ['Password:', 'password:']):
            return {'status': 'failed',
                    'message': 'No password prompt received after username.',
                    'content': None}

        tn.write(password.encode() + b'\n')
        time.sleep(1)

        # Check login success – wait for shell prompt (> or #)
        resp = read_until_any(tn, ['>', '#', 'incorrect', 'failed', 'Error'])
        if any(bad in resp.lower() for bad in ['incorrect', 'authentication failed', 'login failed']):
            return {'status': 'failed',
                    'message': 'Telnet authentication failed – wrong username or password.',
                    'content': None}
        if '>' not in resp and '#' not in resp:
            return {'status': 'failed',
                    'message': 'Did not reach device prompt after login.',
                    'content': None}

        logger.info('[%s] Telnet authenticated as %s', hostname, username)

        # ── Disable paging ─────────────────────────────────────────────────────
        tn.write(b'screen-length 0 temporary\n')
        time.sleep(0.5)
        tn.read_very_eager()  # discard response

        # ── Run backup command ─────────────────────────────────────────────────
        cmd = COLLECT_COMMANDS[DTYPE_HUAWEI]
        logger.info('[%s] Running: %s', hostname, cmd)
        tn.write(cmd.encode() + b'\n')

        # Collect all output until prompt reappears
        output_buf = ''
        deadline = time.time() + CMD_TIMEOUT
        while time.time() < deadline:
            try:
                chunk = tn.read_very_eager()
                if chunk:
                    output_buf += chunk.decode(ENCODING, errors='replace')
                    # Huawei prompt ends with > or # after config dump
                    lines = output_buf.strip().splitlines()
                    if lines and (lines[-1].endswith('>') or lines[-1].endswith('#')):
                        break
            except EOFError:
                break
            time.sleep(0.2)

        # ── Logout gracefully ──────────────────────────────────────────────────
        try:
            tn.write(b'quit\n')
            time.sleep(0.3)
        except Exception:
            pass

        if not output_buf.strip():
            return {'status': 'failed', 'message': 'Empty output from device.', 'content': None}

        # Strip the command echo and trailing prompt from output
        clean_lines = []
        for line in output_buf.splitlines():
            stripped = line.strip()
            # Skip the command echo itself
            if stripped == cmd:
                continue
            # Skip bare prompts at end
            if stripped and stripped[-1] in ('>', '#') and len(stripped) < 50:
                continue
            clean_lines.append(line)
        content = '\n'.join(clean_lines).strip()

        if not content:
            return {'status': 'failed', 'message': 'Output was empty after cleanup.', 'content': None}

        logger.info('[%s] Telnet collected %d bytes', hostname, len(content))
        return {'status': 'success', 'content': content, 'message': ''}

    except ConnectionRefusedError:
        return {'status': 'failed',
                'message': f'Telnet connection refused on {ip}:{port}. Check Telnet is enabled.',
                'content': None}
    except TimeoutError:
        return {'status': 'failed', 'message': f'Telnet connection timed out to {ip}:{port}.', 'content': None}
    except Exception as exc:
        return {'status': 'failed', 'message': f'Telnet error: {exc}', 'content': None}
    finally:
        if tn:
            try:
                tn.close()
            except Exception:
                pass


# ── SSH collector ─────────────────────────────────────────────────────────────

def _ssh_collect_raw(hostname: str, ip: str, port: int,
                     username: str, password: str,
                     device_type: str = DTYPE_JUNOS) -> dict:
    """
    Connect via SSH and run the appropriate show/display command.
    Returns {'status': ..., 'content': str|None, 'message': str}
    """
    cmd = COLLECT_COMMANDS.get(device_type, COLLECT_COMMANDS[DTYPE_JUNOS])
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        logger.info('[%s] SSH connecting to %s:%s', hostname, ip, port)
        client.connect(hostname=ip, port=port, username=username, password=password,
                       timeout=30, look_for_keys=False, allow_agent=False)

        _, stdout, stderr = client.exec_command(cmd, timeout=120)
        output = stdout.read().decode('utf-8', errors='replace')
        err    = stderr.read().decode('utf-8', errors='replace').strip()

        if not output.strip():
            return {'status': 'failed',
                    'message': f'Empty output. stderr: {err}' if err else 'Empty output from device',
                    'content': None}

        logger.info('[%s] SSH collected %d bytes', hostname, len(output))
        return {'status': 'success', 'content': output, 'message': ''}

    except paramiko.AuthenticationException:
        return {'status': 'failed', 'message': 'SSH authentication failed – check credentials',
                'content': None}
    except paramiko.SSHException as exc:
        return {'status': 'failed', 'message': f'SSH error: {exc}', 'content': None}
    except OSError as exc:
        return {'status': 'failed', 'message': f'Connection error: {exc}', 'content': None}
    except Exception as exc:
        return {'status': 'failed', 'message': f'Unexpected error: {exc}', 'content': None}
    finally:
        client.close()


# ── Public collect functions ──────────────────────────────────────────────────

def ssh_collect(hostname: str, ip: str, port: int,
                username: str, enc_password: str,
                device_type: str = DTYPE_JUNOS,
                use_telnet: bool = False) -> dict:
    """
    Collect config from a device (SSH or Telnet based on use_telnet flag).
    Returns {'status': 'success'|'failed'|'skipped', 'content': str, 'message': str}
    """
    if not username or not enc_password:
        return {'status': 'skipped', 'message': 'No credentials configured', 'content': None}

    try:
        password = decrypt_password(enc_password)
    except Exception as exc:
        return {'status': 'failed', 'message': f'Credential decrypt error: {exc}', 'content': None}

    if use_telnet:
        return _telnet_collect_huawei(hostname, ip, port, username, password)
    else:
        return _ssh_collect_raw(hostname, ip, port, username, password, device_type)


def ssh_collect_steps(hostname: str, ip: str, port: int,
                      username: str, enc_password: str,
                      device_type: str = DTYPE_JUNOS,
                      use_telnet: bool = False) -> dict:
    """
    Same as ssh_collect but returns step-by-step dict for the wizard UI.
    {'login': {...}, 'backup': {...}}
    """
    protocol = 'Telnet' if use_telnet else 'SSH'
    cmd      = COLLECT_COMMANDS.get(device_type, COLLECT_COMMANDS[DTYPE_JUNOS])

    result = {
        'login':  {'status': 'pending', 'message': '', 'protocol': protocol},
        'backup': {'status': 'pending', 'message': '', 'content': None, 'command': cmd},
    }

    if not username or not enc_password:
        result['login']  = {'status': 'failed',
                            'message': f'No credentials configured. Set them via 🔑 button.',
                            'protocol': protocol}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None, 'command': cmd}
        return result

    try:
        password = decrypt_password(enc_password)
    except Exception as exc:
        result['login']  = {'status': 'failed', 'message': f'Credential decrypt error: {exc}',
                            'protocol': protocol}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None, 'command': cmd}
        return result

    # ── Step 1: connect + login ───────────────────────────────────────────────
    if use_telnet:
        # For Telnet we run the full collection in one step, then split result
        res = _telnet_collect_huawei(hostname, ip, port, username, password)
        if res['status'] == 'success':
            result['login']  = {'status': 'success',
                                'message': f'Authenticated as {username}@{ip}:{port} (Telnet)',
                                'protocol': protocol}
            result['backup'] = {'status': 'success', 'message': '',
                                'content': res['content'], 'command': cmd}
        else:
            # Distinguish login vs backup errors heuristically
            msg = res['message']
            if any(k in msg.lower() for k in ['auth', 'password', 'username', 'prompt', 'incorrect']):
                result['login']  = {'status': 'failed', 'message': msg, 'protocol': protocol}
                result['backup'] = {'status': 'skipped', 'message': '', 'content': None, 'command': cmd}
            else:
                result['login']  = {'status': 'success',
                                    'message': f'Connected to {ip}:{port} (Telnet)',
                                    'protocol': protocol}
                result['backup'] = {'status': 'failed', 'message': msg, 'content': None, 'command': cmd}
        return result

    # ── SSH: two-step (connect, then run command) ─────────────────────────────
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        logger.info('[%s] Manual backup – SSH connecting to %s:%s', hostname, ip, port)
        client.connect(hostname=ip, port=port, username=username, password=password,
                       timeout=30, look_for_keys=False, allow_agent=False)
        result['login'] = {'status': 'success',
                           'message': f'Authenticated as {username}@{ip}:{port} (SSH)',
                           'protocol': protocol}
    except paramiko.AuthenticationException:
        result['login']  = {'status': 'failed',
                            'message': 'Authentication failed – wrong username or password',
                            'protocol': protocol}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None, 'command': cmd}
        client.close()
        return result
    except paramiko.SSHException as exc:
        result['login']  = {'status': 'failed', 'message': f'SSH error: {exc}', 'protocol': protocol}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None, 'command': cmd}
        client.close()
        return result
    except OSError as exc:
        result['login']  = {'status': 'failed',
                            'message': f'Connection refused / unreachable: {exc}',
                            'protocol': protocol}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None, 'command': cmd}
        client.close()
        return result
    except Exception as exc:
        result['login']  = {'status': 'failed', 'message': f'Unexpected error: {exc}',
                            'protocol': protocol}
        result['backup'] = {'status': 'skipped', 'message': '', 'content': None, 'command': cmd}
        client.close()
        return result

    # ── Step 2: run command ───────────────────────────────────────────────────
    try:
        _, stdout, stderr = client.exec_command(cmd, timeout=120)
        output = stdout.read().decode('utf-8', errors='replace')
        err    = stderr.read().decode('utf-8', errors='replace').strip()

        if not output.strip():
            result['backup'] = {
                'status': 'failed',
                'message': f'Empty output. stderr: {err}' if err else 'Empty output from device',
                'content': None, 'command': cmd,
            }
        else:
            result['backup'] = {'status': 'success', 'message': '',
                                'content': output, 'command': cmd}
    except Exception as exc:
        result['backup'] = {'status': 'failed', 'message': f'Command error: {exc}',
                            'content': None, 'command': cmd}
    finally:
        client.close()

    return result
