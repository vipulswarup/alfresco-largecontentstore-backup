"""Alfresco Tomcat and Solr control helpers for restore workflows."""

import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

TOMCAT_PGREP = ['pgrep', '-f', 'java.*tomcat|java.*alfresco.*tomcat']
DEFAULT_STOP_WAIT_SECONDS = 60


def _yes_no(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = input(prompt + suffix).strip().lower()
    if not answer:
        return default
    return answer in ('y', 'yes')


def _path_with_leading_slash_hint(path: Path) -> Path:
    if path.is_absolute():
        return path
    return Path('/') / path


def confirm_alf_base_dir(default: Path) -> Path:
    """Ask the user to verify or change the EisenVault restore folder before restore."""
    print("\n" + "=" * 80)
    print("  EisenVault Restore Folder")
    print("=" * 80)
    print(f"\nCurrent EisenVault restore folder: {default}")
    print("This is the EisenVault installation folder to restore into.")
    print("Press Enter to keep the current value.")

    while True:
        answer = input(f"EisenVault restore folder [{default}]: ").strip()
        chosen = Path(answer).expanduser() if answer else default

        if chosen.exists():
            break

        slash_candidate = _path_with_leading_slash_hint(chosen)
        if slash_candidate != chosen and slash_candidate.exists():
            if _yes_no(f"Did you mean {slash_candidate}?", default=True):
                chosen = slash_candidate
                break

        print(f"ERROR: Directory does not exist: {chosen}")
        print("Please edit the path and try again, or press Ctrl+C to cancel.")

    alf_script = chosen / 'alfresco.sh'
    if not alf_script.exists():
        print(f"WARNING: alfresco.sh not found at {alf_script}")

    os.environ['ALF_BASE_DIR'] = str(chosen)
    return chosen


def is_tomcat_running() -> bool:
    result = subprocess.run(TOMCAT_PGREP, capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip())


def is_postgresql_ready(
    alf_base_dir: Path,
    pg_host: str,
    pg_port: str,
    pg_user: str,
    pg_password: str,
    pg_database: str,
) -> tuple:
    """Return (ready, message) by making a real psql connection."""
    psql = 'psql'
    embedded = alf_base_dir / 'postgresql' / 'bin' / 'psql'
    if embedded.exists():
        psql = str(embedded)

    env = os.environ.copy()
    if pg_password:
        env['PGPASSWORD'] = pg_password

    try:
        result = subprocess.run(
            [psql, '-h', pg_host, '-p', pg_port, '-U', pg_user, '-d', pg_database, '-t', '-A', '-c', 'SELECT 1;'],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        return False, f"psql not found. Install postgresql-client or use embedded psql under {alf_base_dir}."
    except subprocess.TimeoutExpired:
        return False, f"Timed out connecting to PostgreSQL at {pg_host}:{pg_port}."
    except Exception as e:
        return False, f"Error checking PostgreSQL: {e}"

    if result.returncode == 0:
        return True, "PostgreSQL is accepting connections."

    message = result.stderr.strip() or result.stdout.strip() or f"psql exited {result.returncode}"
    return False, message


def _run_as_user(user: str, cmd: list, timeout: int = 300) -> subprocess.CompletedProcess:
    if user and user != os.getenv('USER', ''):
        full_cmd = ['sudo', '-u', user] + cmd
    else:
        full_cmd = cmd
    return subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def start_postgresql(alf_base_dir: Path, alfresco_user: str) -> bool:
    """Start PostgreSQL without requiring the restore wizard to restart."""
    pg_ctl = alf_base_dir / 'postgresql' / 'scripts' / 'ctl.sh'
    alf_script = alf_base_dir / 'alfresco.sh'

    commands = []
    if pg_ctl.exists():
        commands.append([str(pg_ctl), 'start'])
    if alf_script.exists():
        commands.append([str(alf_script), 'start-postgresql'])
        commands.append([str(alf_script), 'start'])

    if not commands:
        print(f"ERROR: No PostgreSQL start script found under {alf_base_dir}")
        return False

    for cmd in commands:
        print(f"Starting PostgreSQL with: {' '.join(cmd)}")
        try:
            result = _run_as_user(alfresco_user, cmd, timeout=300)
        except subprocess.TimeoutExpired:
            print("WARNING: PostgreSQL start command timed out; it may still be starting.")
            return True
        except Exception as e:
            print(f"ERROR: Failed to run PostgreSQL start command: {e}")
            continue

        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            print(result.stderr.strip())
        if result.returncode == 0:
            return True

    print("ERROR: PostgreSQL start command did not succeed.")
    return False


def ensure_postgresql_ready(
    alf_base_dir: Path,
    alfresco_user: str,
    pg_host: str,
    pg_port: str,
    pg_user: str,
    pg_password: str,
    pg_database: str,
) -> bool:
    """Check PostgreSQL and offer to start it without restarting the restore flow."""
    ready, message = is_postgresql_ready(
        alf_base_dir, pg_host, pg_port, pg_user, pg_password, pg_database
    )
    if ready:
        print(message)
        return True

    print("PostgreSQL is not accepting connections.")
    print(message)
    if not _yes_no("Start PostgreSQL now?", default=True):
        return False

    if not start_postgresql(alf_base_dir, alfresco_user):
        return False

    for _ in range(12):
        ready, message = is_postgresql_ready(
            alf_base_dir, pg_host, pg_port, pg_user, pg_password, pg_database
        )
        if ready:
            print(message)
            return True
        time.sleep(5)

    print("PostgreSQL still is not accepting connections after waiting.")
    print(message)
    return False


def _tomcat_pids() -> list:
    result = subprocess.run(TOMCAT_PGREP, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return [pid for pid in result.stdout.strip().split('\n') if pid]


def _kill_tomcat_processes(alfresco_user: str) -> bool:
    pids = _tomcat_pids()
    if not pids:
        return True

    print(f"Killing Tomcat process(es): {', '.join(pids)}")
    for pid in pids:
        _run_as_user(alfresco_user, ['kill', pid], timeout=30)

    time.sleep(5)
    if not is_tomcat_running():
        print("Tomcat stopped after kill.")
        return True

    for pid in _tomcat_pids():
        _run_as_user(alfresco_user, ['kill', '-9', pid], timeout=30)

    time.sleep(2)
    if is_tomcat_running():
        print("ERROR: Tomcat is still running after kill -9.")
        return False

    print("Tomcat stopped after kill -9.")
    return True


def stop_tomcat(
    alf_base_dir: Path,
    alfresco_user: str,
    wait_seconds: int = DEFAULT_STOP_WAIT_SECONDS,
) -> bool:
    """Stop Tomcat only, leaving PostgreSQL running. Force-kill after wait_seconds."""
    if not is_tomcat_running():
        print("Tomcat is not running.")
        return True

    tomcat_ctl = alf_base_dir / 'tomcat' / 'scripts' / 'ctl.sh'
    alf_script = alf_base_dir / 'alfresco.sh'

    print("Stopping Tomcat (PostgreSQL will remain running)...")
    if tomcat_ctl.exists():
        result = _run_as_user(alfresco_user, [str(tomcat_ctl), 'stop'], timeout=120)
        if result.stdout:
            logger.info(result.stdout.strip())
        if result.stderr:
            logger.info(result.stderr.strip())
    elif alf_script.exists():
        result = _run_as_user(alfresco_user, [str(alf_script), 'stop-tomcat'], timeout=120)
        if result.stdout:
            logger.info(result.stdout.strip())
        if result.stderr:
            logger.info(result.stderr.strip())
    else:
        print("Tomcat control script not found; waiting for graceful shutdown...")

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if not is_tomcat_running():
            print("Tomcat stopped.")
            return True
        time.sleep(2)

    print(f"Tomcat did not stop within {wait_seconds} seconds.")
    return _kill_tomcat_processes(alfresco_user)


def start_tomcat(alf_base_dir: Path, alfresco_user: str) -> bool:
    """Start Tomcat only (PostgreSQL should already be running)."""
    tomcat_ctl = alf_base_dir / 'tomcat' / 'scripts' / 'ctl.sh'
    alf_script = alf_base_dir / 'alfresco.sh'

    print("Starting Tomcat...")
    try:
        if tomcat_ctl.exists():
            result = _run_as_user(alfresco_user, [str(tomcat_ctl), 'start'], timeout=300)
        elif alf_script.exists():
            result = _run_as_user(alfresco_user, [str(alf_script), 'start-tomcat'], timeout=300)
        else:
            print(f"ERROR: No Tomcat start script found under {alf_base_dir}")
            return False

        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            print(result.stderr.strip())
        if result.returncode != 0:
            print(f"ERROR: Tomcat start command exited {result.returncode}")
            return False

        catalina_out = alf_base_dir / 'tomcat' / 'logs' / 'catalina.out'
        print("Tomcat start command completed.")
        print(f"Monitor startup: tail -f {catalina_out}")
        return True
    except subprocess.TimeoutExpired:
        print("WARNING: Tomcat start command timed out; Tomcat may still be starting.")
        return True
    except Exception as e:
        print(f"ERROR: Failed to start Tomcat: {e}")
        return False


def clear_solr_indexes(alf_base_dir: Path, alfresco_user: str) -> bool:
    """Clear Solr4 indexes so Alfresco can rebuild them on startup."""
    solr4_dir = alf_base_dir / 'alf_data' / 'solr4'
    if not solr4_dir.exists():
        print(f"Solr4 directory not found: {solr4_dir}")
        print("Solr may be external or indexes already cleared.")
        return True

    cleared_any = False
    workspace_index = solr4_dir / 'workspace' / 'SpacesStore' / 'index'
    archive_index = solr4_dir / 'archive' / 'SpacesStore' / 'index'
    external_index = solr4_dir / 'index'

    targets = [
        ('workspace', workspace_index),
        ('archive', archive_index),
        ('external', external_index),
    ]

    for label, index_path in targets:
        if not index_path.exists():
            continue
        print(f"Clearing {label} Solr index: {index_path}")
        try:
            _run_as_user(alfresco_user, ['rm', '-rf', str(index_path)], timeout=120)
            cleared_any = True
        except Exception as e:
            print(f"ERROR: Failed to clear {label} index: {e}")
            return False

    if cleared_any:
        print("Solr4 indexes cleared. Alfresco will rebuild them on startup.")
    else:
        print("No Solr indexes found to clear.")

    return True
