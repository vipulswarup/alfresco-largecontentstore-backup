"""Alfresco Tomcat and Solr control helpers for restore workflows."""

import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

TOMCAT_PGREP = ['pgrep', '-f', 'java.*tomcat|java.*alfresco.*tomcat']
DEFAULT_STOP_WAIT_SECONDS = 60


def confirm_alf_base_dir(default: Path) -> Path:
    """Ask the user to verify or change ALF_BASE_DIR before restore."""
    print("\n" + "=" * 80)
    print("  Alfresco Base Directory")
    print("=" * 80)
    print(f"\nALF_BASE_DIR from .env: {default}")
    print("If this path is wrong, enter the correct Alfresco installation directory.")
    print("Press Enter to keep the current value.")

    answer = input(f"Alfresco base directory [{default}]: ").strip()
    chosen = Path(answer).expanduser() if answer else default

    if not chosen.exists():
        print(f"ERROR: Directory does not exist: {chosen}")
        raise SystemExit(1)

    alf_script = chosen / 'alfresco.sh'
    if not alf_script.exists():
        print(f"WARNING: alfresco.sh not found at {alf_script}")

    os.environ['ALF_BASE_DIR'] = str(chosen)
    return chosen


def is_tomcat_running() -> bool:
    result = subprocess.run(TOMCAT_PGREP, capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip())


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
