"""Migrate legacy single-destination .env to backup-policies.yml."""

import os
from pathlib import Path
from typing import Optional, Tuple

import yaml
from dotenv import dotenv_values

from .app_config import CONFIG_VERSION, POLICIES_FILENAME


def has_legacy_single_destination(env_path: Path) -> bool:
    """True if .env exists with legacy BACKUP_DIR or S3_BUCKET but no policies file."""
    if not env_path.exists():
        return False
    values = dotenv_values(env_path)
    has_dest = bool(values.get('BACKUP_DIR') or values.get('S3_BUCKET'))
    return has_dest


def needs_migration(env_path: Path, policies_path: Path) -> bool:
    return has_legacy_single_destination(env_path) and not policies_path.exists()


def migrate_legacy_env(
    env_path: Path = Path('.env'),
    policies_path: Path = Path(POLICIES_FILENAME),
) -> Tuple[bool, str]:
    """
    Create backup-policies.yml from legacy .env.
    Returns (created, message).
    """
    if policies_path.exists():
        return False, f"{policies_path} already exists"
    if not env_path.exists():
        return False, f"{env_path} not found"

    values = dotenv_values(env_path)
    s3_bucket = values.get('S3_BUCKET', '').strip()
    backup_dir = values.get('BACKUP_DIR', '').strip()
    retention = int(values.get('RETENTION_DAYS', '7') or '7')
    legacy_base = values.get('ALF_BASE_DIR', '').strip()
    if legacy_base:
        _append_env_if_missing(env_path, 'EISENVAULT_SOURCE_DIR', legacy_base)
        _append_env_if_missing(env_path, 'EISENVAULT_RESTORE_DIR', legacy_base)

    global_section = {
        'staging_dir': '/var/tmp/alfresco-backup',
        'max_parallel_destinations': 2,
        'restic_read_concurrency': 4,
        'default_maintenance': {
            'enabled': True,
            'day_of_week': 'sunday',
            'time': '03:30',
        },
    }

    credential_profiles = []
    backup_policies = []

    if s3_bucket:
        profile_name = 'migrated-s3'
        access_env = 'OBJSTORE_MIGRATED_ACCESS_KEY'
        secret_env = 'OBJSTORE_MIGRATED_SECRET_KEY'
        region = values.get('S3_REGION', 'us-east-1')
        endpoint = values.get('S3_ENDPOINT_URL', f"https://s3.{region}.amazonaws.com")

        credential_profiles.append({
            'name': profile_name,
            'type': 'object_storage',
            'provider': 's3_compatible',
            'endpoint_url': endpoint,
            'region': region,
            'bucket': s3_bucket,
            'access_key_env': access_env,
            'secret_key_env': secret_env,
        })

        _append_env_if_missing(env_path, access_env, values.get('AWS_ACCESS_KEY_ID', ''))
        _append_env_if_missing(env_path, secret_env, values.get('AWS_SECRET_ACCESS_KEY', ''))

        backup_policies.append({
            'name': 'migrated-default',
            'enabled': True,
            'destination_type': 'object_storage',
            'credential_profile': profile_name,
            'repository_prefix': 'alfresco/restic',
            'encryption': {'enabled': True, 'password_env': 'RESTIC_PASSWORD_MIGRATED'},
            'backup_time': '02:00',
            'retention_days': retention,
            'maintenance': {
                'enabled': True,
                'day_of_week': 'sunday',
                'time': '03:30',
            },
            'priority': 10,
        })
        _append_env_if_missing(env_path, 'RESTIC_PASSWORD_MIGRATED', '')

    elif backup_dir:
        repo_path = str(Path(backup_dir) / 'restic')
        backup_policies.append({
            'name': 'migrated-default',
            'enabled': True,
            'destination_type': 'filesystem',
            'repository_path': repo_path,
            'encryption': {'enabled': False, 'password_env': None},
            'backup_time': '02:00',
            'retention_days': retention,
            'maintenance': {
                'enabled': True,
                'day_of_week': 'sunday',
                'time': '03:30',
            },
            'priority': 10,
        })

    doc = {
        'config_version': CONFIG_VERSION,
        'migrated_from_legacy': True,
        'global': global_section,
        'credential_profiles': credential_profiles,
        'backup_policies': backup_policies,
    }

    if not backup_policies:
        return False, "No BACKUP_DIR or S3_BUCKET in .env to migrate"

    with open(policies_path, 'w', encoding='utf-8') as f:
        yaml.dump(doc, f, default_flow_style=False, sort_keys=False)

    return True, f"Created {policies_path} with policy 'migrated-default'"


def _append_env_if_missing(env_path: Path, key: str, value: str) -> None:
    if not value:
        return
    content = env_path.read_text(encoding='utf-8')
    if f"{key}=" in content:
        return
    with open(env_path, 'a', encoding='utf-8') as f:
        f.write(f"\n# Added by v2 migration\n{key}={value}\n")
