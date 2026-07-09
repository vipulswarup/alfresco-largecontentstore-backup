"""User-facing restore helpers shared by restore workflows."""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from alfresco_backup.restore.alfresco_control import is_postgresql_ready, is_tomcat_running


PRODUCT_NAME = "EisenVault"
SESSION_FILE = Path('.restore-session.json')


@dataclass
class PreflightCheck:
    label: str
    ok: bool
    detail: str
    required: bool = True


def section(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_restore_plan(steps: Iterable[str]) -> None:
    section(f"{PRODUCT_NAME} Restore Plan")
    for idx, step in enumerate(steps, 1):
        print(f"  {idx}. {step}")


def _ok_text(check: PreflightCheck) -> str:
    if check.ok:
        return "OK"
    return "FAIL" if check.required else "WARN"


def print_preflight(title: str, checks: List[PreflightCheck]) -> None:
    section(title)
    for check in checks:
        print(f"  [{_ok_text(check):4}] {check.label}: {check.detail}")


def preflight_failed(checks: List[PreflightCheck]) -> bool:
    return any(check.required and not check.ok for check in checks)


def _path_exists(path: Path) -> str:
    return str(path) if path.exists() else f"missing: {path}"


def _command_available(command: str) -> bool:
    if Path(command).exists():
        return True
    return shutil.which(command) is not None


def detect_psql(restore_folder: Path) -> str:
    embedded = restore_folder / 'postgresql' / 'bin' / 'psql'
    if embedded.exists():
        return str(embedded)
    return 'psql'


def collect_restore_folder_checks(restore_folder: Path) -> List[PreflightCheck]:
    expected = [
        ("Restore folder", restore_folder, True),
        ("EisenVault control script", restore_folder / 'alfresco.sh', False),
        ("Tomcat folder", restore_folder / 'tomcat', False),
        ("Current contentstore folder", restore_folder / 'alf_data' / 'contentstore', False),
        (
            "EisenVault configuration",
            restore_folder / 'tomcat' / 'shared' / 'classes' / 'alfresco-global.properties',
            False,
        ),
    ]
    checks = []
    for label, path, required in expected:
        checks.append(PreflightCheck(label, path.exists(), _path_exists(path), required))
    return checks


def collect_v2_preflight_checks(
    restore_folder: Path,
    backup_source: str,
    pg_host: str,
    pg_port: str,
    pg_user: str,
    pg_password: str,
    pg_database: str,
    staging_parent: Optional[Path] = None,
) -> List[PreflightCheck]:
    checks = collect_restore_folder_checks(restore_folder)

    psql = detect_psql(restore_folder)
    checks.append(
        PreflightCheck(
            "PostgreSQL client",
            _command_available(psql),
            psql,
            True,
        )
    )

    ready, pg_message = is_postgresql_ready(
        restore_folder, pg_host, pg_port, pg_user, pg_password, pg_database
    )
    checks.append(
        PreflightCheck(
            "PostgreSQL connection",
            ready,
            f"{pg_host}:{pg_port} database={pg_database} user={pg_user}; {pg_message}",
            False,
        )
    )

    checks.append(
        PreflightCheck(
            "Tomcat status",
            True,
            "running" if is_tomcat_running() else "not running",
            False,
        )
    )

    staging_parent = staging_parent or Path(os.getenv('TMPDIR', '/tmp'))
    usage_path = staging_parent if staging_parent.exists() else staging_parent.parent
    try:
        usage = shutil.disk_usage(usage_path)
        free_gb = usage.free / (1024 ** 3)
        checks.append(
            PreflightCheck(
                "Staging disk space",
                free_gb >= 5,
                f"{free_gb:.1f} GB free at {usage_path}",
                False,
            )
        )
    except OSError as e:
        checks.append(PreflightCheck("Staging disk space", False, str(e), False))

    checks.append(PreflightCheck("Selected backup source", True, backup_source, True))
    return checks


def print_restore_summary(
    restore_folder: Path,
    mode: str,
    backup_source: str,
    run_id: Optional[str],
    pg_host: str,
    pg_port: str,
    pg_user: str,
    pg_database: str,
    log_file: Optional[Path] = None,
) -> None:
    section(f"{PRODUCT_NAME} Restore Summary")
    print(f"  Restore mode: {mode}")
    print(f"  Restore folder: {restore_folder}")
    print(f"  Backup source: {backup_source}")
    if run_id:
        print(f"  Backup run: {run_id}")
    print(f"  PostgreSQL: {pg_host}:{pg_port} database={pg_database} user={pg_user}")
    print(f"  Contentstore: {restore_folder / 'alf_data' / 'contentstore'}")
    if log_file:
        print(f"  Log file: {log_file}")


def target_confirmation_token(restore_folder: Path) -> str:
    name = restore_folder.name.strip() or "target"
    return f"RESTORE {name}"


def confirm_destructive_restore(restore_folder: Path) -> bool:
    token = target_confirmation_token(restore_folder)
    print("\nThis will replace EisenVault database/contentstore data for:")
    print(f"  {restore_folder}")
    print(f"Type '{token}' to continue.")
    answer = input("Confirm restore: ").strip()
    if answer == token:
        return True
    print("Cancelled.")
    return False


def print_failure_guidance(restore_folder: Path, backup_contentstore: Optional[Path] = None) -> None:
    section("Recovery Guidance")
    print("The restore did not complete. Review the log output above first.")
    print("Useful local checks:")
    print(f"  tail -100 {restore_folder / 'tomcat' / 'logs' / 'catalina.out'}")
    print(f"  tail -100 {restore_folder / 'alf_data' / 'postgresql' / 'postgresql.log'}")
    if backup_contentstore:
        live = restore_folder / 'alf_data' / 'contentstore'
        print("\nPrevious contentstore backup detected:")
        print(f"  {backup_contentstore}")
        print("To manually roll back the contentstore after reviewing the failure:")
        print(f"  sudo rm -rf {live}")
        print(f"  sudo mv {backup_contentstore} {live}")


def run_command_check(label: str, command: List[str], timeout: int = 30) -> PreflightCheck:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return PreflightCheck(label, False, f"command not found: {command[0]}", True)
    except subprocess.TimeoutExpired:
        return PreflightCheck(label, False, "timed out", True)

    detail = (result.stderr or result.stdout or '').strip()
    if not detail:
        detail = f"exit code {result.returncode}"
    return PreflightCheck(label, result.returncode == 0, detail.splitlines()[0], True)


def load_restore_session(path: Path = SESSION_FILE) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_restore_session(data: dict, path: Path = SESSION_FILE) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write('\n')
    tmp.replace(path)


def clear_restore_session(path: Path = SESSION_FILE) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = input(prompt + suffix).strip().lower()
    if not answer:
        return default
    return answer in ('y', 'yes')
