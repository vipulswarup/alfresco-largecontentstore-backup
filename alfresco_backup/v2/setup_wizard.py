"""V2 configuration wizard (invoked from setup.py)."""

import os
import shutil
import subprocess
from pathlib import Path

import yaml

from .app_config import AppConfig, CONFIG_VERSION, POLICIES_FILENAME
from .migration import migrate_legacy_env, needs_migration
from .restic import ResticRepository


def check_restic_installed() -> bool:
    return shutil.which('restic') is not None


def install_restic_ubuntu(use_sudo: bool) -> bool:
    prefix = ['sudo'] if use_sudo else []
    for cmd in [prefix + ['apt-get', 'update'], prefix + ['apt-get', 'install', '-y', 'restic']]:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return False
    return check_restic_installed()


def run_v2_setup_menu() -> None:
    print("\n" + "=" * 80)
    print("  V2 Multi-Destination Backup Configuration")
    print("=" * 80)

    if not check_restic_installed():
        print("restic is not installed.")
        if input("Install restic via apt? [Y/n]: ").strip().lower() not in ('n', 'no'):
            use_sudo = os.geteuid() != 0
            if not install_restic_ubuntu(use_sudo):
                print("Failed to install restic. Install manually and retry.")
                return
        else:
            return

    env_path = Path('.env')
    policies_path = Path(POLICIES_FILENAME)

    if needs_migration(env_path, policies_path):
        created, msg = migrate_legacy_env(env_path, policies_path)
        print(msg)
        if created:
            print("Review backup-policies.yml and set RESTIC_PASSWORD_* / OBJSTORE_* secrets in .env")

    while True:
        print("\nOptions:")
        print("  1. Show current policies")
        print("  2. Validate all destinations")
        print("  3. Initialize restic repositories")
        print("  4. Add filesystem destination")
        print("  5. Add object storage destination")
        print("  6. Exit")
        choice = input("Choice: ").strip()
        if choice == '6':
            break
        if choice == '1':
            _show_policies(policies_path)
        elif choice == '2':
            _validate_all(env_path, policies_path)
        elif choice == '3':
            _init_repos(env_path, policies_path)
        elif choice == '4':
            _add_filesystem_destination(policies_path)
        elif choice == '5':
            _add_object_storage_destination(env_path, policies_path)
        else:
            print("Invalid choice")


def _load_policies(path: Path) -> dict:
    if not path.exists():
        return {
            'config_version': CONFIG_VERSION,
            'global': {
                'staging_dir': '/var/tmp/alfresco-backup',
                'max_parallel_destinations': 2,
                'default_maintenance': {
                    'enabled': True,
                    'day_of_week': 'sunday',
                    'time': '03:30',
                },
            },
            'credential_profiles': [],
            'backup_policies': [],
        }
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def _save_policies(path: Path, doc: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(doc, f, default_flow_style=False, sort_keys=False)
    print(f"Saved {path}")


def _show_policies(path: Path) -> None:
    doc = _load_policies(path)
    print(yaml.dump(doc, default_flow_style=False))


def _validate_all(env_path: Path, policies_path: Path) -> None:
    try:
        config = AppConfig(str(env_path), str(policies_path))
    except Exception as e:
        print(f"Config error: {e}")
        return
    for policy in config.enabled_policies():
        profile = config.get_profile(policy.credential_profile) if policy.credential_profile else None
        repo = ResticRepository(policy, config, profile)
        if policy.destination_type == 'filesystem':
            p = Path(policy.repository_path)
            if not p.parent.exists():
                print(f"  {policy.name}: FAIL parent path missing")
                continue
        check = repo.check()
        if check['success']:
            print(f"  {policy.name}: OK")
        else:
            snaps = repo.snapshots_json()
            if snaps['success'] or 'repository not found' in (check.get('error') or '').lower():
                print(f"  {policy.name}: OK (repo may need init)")
            else:
                print(f"  {policy.name}: FAIL {check.get('error')}")
        if policy.encryption.enabled and not policy.encryption.password_env:
            print(f"  {policy.name}: WARN encryption enabled without password_env")
        if not policy.encryption.enabled:
            print(
                f"  {policy.name}: WARNING repository encryption disabled (insecure-by-choice)"
            )


def _init_repos(env_path: Path, policies_path: Path) -> None:
    config = AppConfig(str(env_path), str(policies_path))
    for policy in config.enabled_policies():
        profile = config.get_profile(policy.credential_profile) if policy.credential_profile else None
        repo = ResticRepository(policy, config, profile)
        r = repo.init()
        if r['success'] or 'already exists' in (r.get('error') or '').lower():
            print(f"  {policy.name}: initialized")
        else:
            print(f"  {policy.name}: {r.get('error')}")


def _add_filesystem_destination(policies_path: Path) -> None:
    doc = _load_policies(policies_path)
    name = input("Policy name: ").strip()
    repo_path = input("Repository path: ").strip()
    retention = input("Retention days [15]: ").strip() or '15'
    backup_time = input("Daily backup time HH:MM [02:00]: ").strip() or '02:00'
    enc = input("Enable encryption? [Y/n]: ").strip().lower() not in ('n', 'no')
    password_env = None
    if enc:
        password_env = input("RESTIC password env var name: ").strip() or f"RESTIC_PASSWORD_{name.upper().replace('-', '_')}"
    else:
        print("WARNING: Unencrypted repository is insecure-by-choice.")

    doc.setdefault('backup_policies', []).append({
        'name': name,
        'enabled': True,
        'destination_type': 'filesystem',
        'repository_path': repo_path,
        'encryption': {'enabled': enc, 'password_env': password_env},
        'backup_time': backup_time,
        'retention_days': int(retention),
        'priority': 10 + len(doc.get('backup_policies', [])),
    })
    _save_policies(policies_path, doc)


def _add_object_storage_destination(env_path: Path, policies_path: Path) -> None:
    doc = _load_policies(policies_path)
    profile_name = input("Credential profile name: ").strip()
    endpoint = input("Endpoint URL: ").strip()
    region = input("Region: ").strip()
    bucket = input("Bucket: ").strip()
    access_env = input("Access key env var: ").strip()
    secret_env = input("Secret key env var: ").strip()

    doc.setdefault('credential_profiles', []).append({
        'name': profile_name,
        'type': 'object_storage',
        'provider': 's3_compatible',
        'endpoint_url': endpoint,
        'region': region,
        'bucket': bucket,
        'access_key_env': access_env,
        'secret_key_env': secret_env,
    })

    name = input("Policy name: ").strip()
    prefix = input("Repository prefix: ").strip()
    retention = input("Retention days [180]: ").strip() or '180'
    backup_time = input("Daily backup time HH:MM [02:30]: ").strip() or '02:30'
    enc = input("Enable encryption? [Y/n]: ").strip().lower() not in ('n', 'no')
    password_env = f"RESTIC_PASSWORD_{name.upper().replace('-', '_')}" if enc else None
    if not enc:
        print("WARNING: Unencrypted repository is insecure-by-choice.")

    doc.setdefault('backup_policies', []).append({
        'name': name,
        'enabled': True,
        'destination_type': 'object_storage',
        'credential_profile': profile_name,
        'repository_prefix': prefix,
        'encryption': {'enabled': enc, 'password_env': password_env},
        'backup_time': backup_time,
        'retention_days': int(retention),
        'priority': 20 + len(doc.get('backup_policies', [])),
    })
    _save_policies(policies_path, doc)
    print(f"Set {access_env}, {secret_env}, and {password_env} in .env")
