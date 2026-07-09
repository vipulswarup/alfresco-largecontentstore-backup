"""Load and validate .env + backup-policies.yml for v2."""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from dotenv import load_dotenv

from .models import (
    BackupPolicy,
    CredentialProfile,
    EncryptionConfig,
    GlobalConfig,
    MaintenanceConfig,
)
from .schedule import validate_schedule_fields


POLICIES_FILENAME = 'backup-policies.yml'
CONFIG_VERSION = 1
ENV_VAR_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
SOURCE_DIR_VARS = ('EISENVAULT_SOURCE_DIR', 'ALF_SOURCE_DIR', 'ALF_BASE_DIR')
RESTORE_DIR_VARS = (
    'EISENVAULT_RESTORE_DIR',
    'ALF_RESTORE_DIR',
    'EISENVAULT_SOURCE_DIR',
    'ALF_SOURCE_DIR',
    'ALF_BASE_DIR',
)


def _validate_env_var_name(value: str, context: str) -> None:
    if not value or not ENV_VAR_PATTERN.match(value):
        raise ValueError(
            f"{context}: invalid environment variable name '{value}'. "
            "Use letters, numbers, and underscores only, and do not start with a number."
        )


def _first_env(names) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return ''


class AppConfig:
    """Resolved v2 configuration from .env and backup-policies.yml."""

    def __init__(
        self,
        env_file: str = '.env',
        policies_file: Optional[str] = None,
        mode: str = 'backup',
    ):
        if mode not in ('backup', 'restore'):
            raise ValueError("mode must be 'backup' or 'restore'")
        self.env_file = Path(env_file)
        self.policies_file = Path(policies_file or POLICIES_FILENAME)
        self.mode = mode
        self._env: Dict[str, str] = {}
        self.global_config: Optional[GlobalConfig] = None
        self.credential_profiles: List[CredentialProfile] = []
        self.backup_policies: List[BackupPolicy] = []
        self.config_version: int = CONFIG_VERSION
        self._load()

    def _load(self) -> None:
        if not self.env_file.exists():
            raise FileNotFoundError(f"Environment file not found: {self.env_file}")
        if not self.policies_file.exists():
            raise FileNotFoundError(
                f"Policy file not found: {self.policies_file}. "
                "Run setup.py to create or migrate configuration."
            )

        load_dotenv(self.env_file, override=True)
        self._env = {k: v for k, v in os.environ.items() if v is not None}

        with open(self.policies_file, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f) or {}

        self.config_version = int(raw.get('config_version', CONFIG_VERSION))
        self._parse_global(raw.get('global', {}))
        self._parse_credential_profiles(raw.get('credential_profiles', []))
        self._parse_backup_policies(raw.get('backup_policies', []))
        self._validate_unique_destinations()
        self._validate_env_secrets()
        self._validate_paths()

    def _parse_global(self, data: dict) -> None:
        staging = Path(data.get('staging_dir', '/var/tmp/alfresco-backup'))
        max_parallel = int(data.get('max_parallel_destinations', 2))
        if max_parallel < 1:
            raise ValueError('max_parallel_destinations must be >= 1')
        dm = data.get('default_maintenance', {})
        self.global_config = GlobalConfig(
            staging_dir=staging,
            max_parallel_destinations=max_parallel,
            default_maintenance=MaintenanceConfig(
                enabled=bool(dm.get('enabled', True)),
                day_of_week=str(dm.get('day_of_week', 'sunday')).lower(),
                time=str(dm.get('time', '03:30')),
            ),
        )

    def _parse_credential_profiles(self, profiles: list) -> None:
        names = set()
        for p in profiles:
            name = p['name']
            if name in names:
                raise ValueError(f"Duplicate credential profile: {name}")
            names.add(name)
            if p.get('type') != 'object_storage':
                raise ValueError(f"Profile {name}: only object_storage type supported")
            _validate_env_var_name(p['access_key_env'], f"Profile {name} access_key_env")
            _validate_env_var_name(p['secret_key_env'], f"Profile {name} secret_key_env")
            self.credential_profiles.append(
                CredentialProfile(
                    name=name,
                    type=p['type'],
                    provider=p.get('provider', 's3_compatible'),
                    endpoint_url=p['endpoint_url'].rstrip('/'),
                    region=p['region'],
                    bucket=p['bucket'],
                    access_key_env=p['access_key_env'],
                    secret_key_env=p['secret_key_env'],
                )
            )

    def _parse_backup_policies(self, policies: list) -> None:
        names = set()
        profile_names = {p.name for p in self.credential_profiles}
        for p in policies:
            name = p['name']
            if name in names:
                raise ValueError(f"Duplicate backup policy: {name}")
            names.add(name)
            dest = p['destination_type']
            if dest not in ('filesystem', 'object_storage'):
                raise ValueError(f"Policy {name}: invalid destination_type {dest}")

            enc = p.get('encryption', {})
            encryption = EncryptionConfig(
                enabled=bool(enc.get('enabled', True)),
                password_env=enc.get('password_env'),
            )
            maint = p.get('maintenance') or {}
            if not maint and self.global_config:
                dm = self.global_config.default_maintenance
                maintenance = MaintenanceConfig(dm.enabled, dm.day_of_week, dm.time)
            else:
                maintenance = MaintenanceConfig(
                    enabled=bool(maint.get('enabled', True)),
                    day_of_week=str(maint.get('day_of_week', 'sunday')).lower(),
                    time=str(maint.get('time', '03:30')),
                )

            validate_schedule_fields(p['backup_time'], {
                'enabled': maintenance.enabled,
                'day_of_week': maintenance.day_of_week,
                'time': maintenance.time,
            })

            cred = p.get('credential_profile')
            if dest == 'object_storage':
                if not cred or cred not in profile_names:
                    raise ValueError(
                        f"Policy {name}: object_storage requires valid credential_profile"
                    )
            if dest == 'filesystem' and not p.get('repository_path'):
                raise ValueError(f"Policy {name}: filesystem requires repository_path")

            self.backup_policies.append(
                BackupPolicy(
                    name=name,
                    enabled=bool(p.get('enabled', True)),
                    destination_type=dest,
                    repository_path=p.get('repository_path'),
                    credential_profile=cred,
                    repository_prefix=p.get('repository_prefix'),
                    encryption=encryption,
                    backup_time=p['backup_time'],
                    retention_days=int(p['retention_days']),
                    maintenance=maintenance,
                    priority=int(p.get('priority', 100)),
                )
            )

    def _validate_unique_destinations(self) -> None:
        filesystem_repos: Dict[str, List[str]] = {}
        for policy in self.backup_policies:
            if (
                not policy.enabled
                or policy.destination_type != 'filesystem'
                or not policy.repository_path
            ):
                continue
            repo_key = str(Path(policy.repository_path).expanduser())
            filesystem_repos.setdefault(repo_key, []).append(policy.name)

        duplicates = [
            (repo, names)
            for repo, names in filesystem_repos.items()
            if len(names) > 1
        ]
        if duplicates:
            details = '; '.join(
                f"{', '.join(names)} use {repo}"
                for repo, names in duplicates
            )
            raise ValueError(
                "Duplicate enabled filesystem destinations in backup-policies.yml: "
                f"{details}. Remove or disable duplicates before running backup."
            )

    def _validate_env_secrets(self) -> None:
        required = ['PGHOST', 'PGPORT', 'PGUSER', 'PGPASSWORD']
        missing = [v for v in required if not os.getenv(v)]
        if self.mode == 'backup' and not _first_env(SOURCE_DIR_VARS):
            missing.append('EISENVAULT_SOURCE_DIR or ALF_BASE_DIR')
        if self.mode == 'restore' and not _first_env(RESTORE_DIR_VARS):
            missing.append('EISENVAULT_RESTORE_DIR or ALF_BASE_DIR')
        if missing:
            print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
            sys.exit(1)

        for profile in self.credential_profiles:
            for var in (profile.access_key_env, profile.secret_key_env):
                if not os.getenv(var):
                    raise ValueError(f"Missing secret env var for profile {profile.name}: {var}")

        for policy in self.backup_policies:
            if policy.encryption.enabled and not policy.encryption.password_env:
                raise ValueError(
                    f"Policy {policy.name}: encryption enabled requires password_env"
                )
            if policy.encryption.enabled:
                _validate_env_var_name(
                    policy.encryption.password_env,
                    f"Policy {policy.name} password_env",
                )
                if not os.getenv(policy.encryption.password_env):
                    raise ValueError(
                        f"Policy {policy.name}: missing {policy.encryption.password_env}"
                    )

    def _validate_paths(self) -> None:
        source_value = _first_env(SOURCE_DIR_VARS)
        restore_value = _first_env(RESTORE_DIR_VARS)
        source_base = Path(source_value) if source_value else None
        restore_base = Path(restore_value) if restore_value else None

        if self.mode == 'backup':
            if source_base is None:
                raise ValueError('EISENVAULT_SOURCE_DIR or ALF_BASE_DIR is required for backup')
            if not source_base.exists():
                raise ValueError(f"EISENVAULT_SOURCE_DIR does not exist: {source_base}")
            cs = source_base / 'alf_data' / 'contentstore'
            if not cs.exists():
                raise ValueError(f"Source contentstore does not exist: {cs}")
        else:
            if restore_base is None:
                raise ValueError('EISENVAULT_RESTORE_DIR or ALF_BASE_DIR is required for restore')
            if not restore_base.exists():
                raise ValueError(f"EISENVAULT_RESTORE_DIR does not exist: {restore_base}")

        for policy in self.backup_policies:
            if policy.destination_type == 'filesystem' and policy.repository_path:
                parent = Path(policy.repository_path).parent
                if not parent.exists():
                    raise ValueError(
                        f"Policy {policy.name}: parent of repository_path does not exist: {parent}"
                    )

    def get_profile(self, name: str) -> Optional[CredentialProfile]:
        for p in self.credential_profiles:
            if p.name == name:
                return p
        return None

    def enabled_policies(self) -> List[BackupPolicy]:
        return [p for p in self.backup_policies if p.enabled]

    def policies_by_priority(self) -> List[BackupPolicy]:
        return sorted(self.enabled_policies(), key=lambda p: p.priority)

    @property
    def pghost(self) -> str:
        return os.getenv('PGHOST', 'localhost')

    @property
    def pgport(self) -> str:
        return os.getenv('PGPORT', '5432')

    @property
    def pguser(self) -> str:
        return os.getenv('PGUSER', 'alfresco')

    @property
    def pgpassword(self) -> str:
        return os.getenv('PGPASSWORD', '')

    @property
    def pgdatabase(self) -> str:
        return os.getenv('PGDATABASE', 'postgres')

    @property
    def alf_base_dir(self) -> Path:
        return self.source_alf_base_dir

    @property
    def source_alf_base_dir(self) -> Path:
        return Path(_first_env(SOURCE_DIR_VARS))

    @property
    def restore_alf_base_dir(self) -> Path:
        return Path(_first_env(RESTORE_DIR_VARS))

    @property
    def contentstore_path(self) -> Path:
        return self.source_alf_base_dir / 'alf_data' / 'contentstore'

    @property
    def restore_contentstore_path(self) -> Path:
        return self.restore_alf_base_dir / 'alf_data' / 'contentstore'

    @property
    def customer_name(self) -> str:
        return os.getenv('CUSTOMER_NAME', '').strip()

    @property
    def email_enabled(self) -> bool:
        required = ['SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', 'ALERT_EMAIL', 'ALERT_FROM']
        return all(os.getenv(v) for v in required) and self.email_alert_mode != 'none'

    @property
    def email_alert_mode(self) -> str:
        mode = os.getenv('EMAIL_ALERT_MODE', 'failure_only').lower()
        if mode not in ('both', 'failure_only', 'none'):
            return 'failure_only'
        return mode

    @property
    def smtp_host(self) -> str:
        return os.getenv('SMTP_HOST', '')

    @property
    def smtp_port(self) -> int:
        return int(os.getenv('SMTP_PORT', '587'))

    @property
    def smtp_user(self) -> str:
        return os.getenv('SMTP_USER', '')

    @property
    def smtp_password(self) -> str:
        return os.getenv('SMTP_PASSWORD', '')

    @property
    def alert_email(self) -> str:
        return os.getenv('ALERT_EMAIL', '')

    @property
    def alert_from(self) -> str:
        return os.getenv('ALERT_FROM', '')

    def env_get(self, key: str) -> str:
        return os.getenv(key, '')
