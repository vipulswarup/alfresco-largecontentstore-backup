"""V2 configuration wizard (invoked from setup.py)."""

import os
import getpass
import re
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
        _ensure_policy_passwords(env_path, policies_path)
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
    from .restic import get_restic_version, passwordless_repositories_supported

    version = get_restic_version()
    if version:
        print(f"  restic version: {version[0]}.{version[1]}.{version[2]}")
    if not passwordless_repositories_supported():
        print(
            "  Note: restic < 0.17 cannot create passwordless repositories. "
            "Destinations must enable encryption or restic must be upgraded."
        )

    _ensure_policy_passwords(env_path, policies_path)
    config = AppConfig(str(env_path), str(policies_path))
    for policy in config.enabled_policies():
        profile = config.get_profile(policy.credential_profile) if policy.credential_profile else None
        repo = ResticRepository(policy, config, profile)
        r = repo.init()
        err = (r.get('error') or '').lower()
        if r['success'] or 'already exists' in err or 'already initialized' in err:
            print(f"  {policy.name}: OK")
        else:
            print(f"  {policy.name}: FAILED")
            print(f"    {r.get('error', 'unknown error')}")


def _add_filesystem_destination(policies_path: Path, name: str = None) -> None:
    doc = _load_policies(policies_path)
    if not name:
        name = input("Policy name: ").strip()
    repo_path = input("Repository path: ").strip()
    retention = input("Retention days [15]: ").strip() or '15'
    backup_time = input("Daily backup time HH:MM [02:00]: ").strip() or '02:00'
    enc = _ask_encryption_enabled()
    password_env = None
    if enc:
        password_env = _restic_password_env_name(name)
        print(f"Restic password will be stored in .env as: {password_env}")
        _ensure_env_secret(
            Path('.env'),
            password_env,
            f"Enter restic repository password for policy '{name}'",
        )
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


def _add_object_storage_destination(env_path: Path, policies_path: Path, name: str = None) -> None:
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

    if not name:
        name = input("Policy name: ").strip()
    prefix = input("Repository prefix: ").strip()
    retention = input("Retention days [180]: ").strip() or '180'
    backup_time = input("Daily backup time HH:MM [02:30]: ").strip() or '02:30'
    enc = _ask_encryption_enabled()
    password_env = _restic_password_env_name(name) if enc else None
    if enc:
        print(f"Restic password will be stored in .env as: {password_env}")
        _ensure_env_secret(
            env_path,
            password_env,
            f"Enter restic repository password for policy '{name}'",
        )
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


def _restic_password_env_name(policy_name: str) -> str:
    suffix = re.sub(r'[^A-Za-z0-9]+', '_', policy_name).strip('_').upper()
    if not suffix:
        suffix = 'POLICY'
    return f"RESTIC_PASSWORD_{suffix}"


def _normalize_env_key(key: str) -> str:
    return re.sub(r'[^A-Za-z0-9]+', '', key).upper()


def _read_env_assignments(env_path: Path) -> dict:
    values = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def _append_env_value(env_path: Path, key: str, value: str) -> None:
    content = env_path.read_text(encoding='utf-8') if env_path.exists() else ''
    if content and not content.endswith('\n'):
        content += '\n'
    content += f"\n# Added by setup to satisfy backup-policies.yml\n{key}={value}\n"
    env_path.write_text(content, encoding='utf-8')
    os.chmod(env_path, 0o600)


def _ensure_policy_passwords(env_path: Path, policies_path: Path) -> None:
    """Ensure every encrypted policy has a usable RESTIC_PASSWORD_* env var."""
    doc = _load_policies(policies_path)
    policies = doc.get('backup_policies', [])
    changed = False

    for policy in policies:
        enc = policy.setdefault('encryption', {})
        if not enc.get('enabled', True):
            continue

        name = policy.get('name', '').strip()
        password_env = enc.get('password_env')
        if not password_env:
            password_env = _restic_password_env_name(name)
            enc['password_env'] = password_env
            changed = True
            print(f"Policy {name}: using restic password env var {password_env}")

        values = _read_env_assignments(env_path)
        if values.get(password_env):
            continue

        normalized_target = _normalize_env_key(password_env)
        compatible = [
            (key, value)
            for key, value in values.items()
            if key.startswith('RESTIC_PASSWORD_')
            and value
            and _normalize_env_key(key) == normalized_target
        ]
        if compatible:
            source_key, source_value = compatible[0]
            _append_env_value(env_path, password_env, source_value)
            print(
                f"Policy {name}: added {password_env} as an alias of existing {source_key}"
            )
            continue

        _ensure_env_secret(
            env_path,
            password_env,
            f"Enter restic repository password for existing policy '{name}'",
        )

    if changed:
        _save_policies(policies_path, doc)


def _ask_encryption_enabled() -> bool:
    from .restic import get_restic_version, passwordless_repositories_supported

    if not passwordless_repositories_supported():
        version = get_restic_version()
        version_text = (
            f"{version[0]}.{version[1]}.{version[2]}"
            if version
            else "unknown"
        )
        print(
            f"Installed restic {version_text} requires a repository password. "
            "Encryption will be enabled."
        )
        return True
    return input("Enable encryption? [Y/n]: ").strip().lower() not in ('n', 'no')


def _ensure_env_secret(env_path: Path, key: str, prompt: str) -> None:
    if not key:
        return
    content = env_path.read_text(encoding='utf-8') if env_path.exists() else ''
    for line in content.splitlines():
        if line.startswith(f"{key}=") and line.split('=', 1)[1]:
            return

    while True:
        value = getpass.getpass(f"{prompt}: ").strip()
        if value:
            break
        print("Password cannot be empty.")

    lines = []
    replaced = False
    for line in content.splitlines():
        if line.startswith(f"{key}="):
            lines.append(f"{key}={value}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        if lines and lines[-1] != '':
            lines.append('')
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding='utf-8')
    os.chmod(env_path, 0o600)
