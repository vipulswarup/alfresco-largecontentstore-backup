"""Data models for v2 backup and restore."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class EncryptionConfig:
    enabled: bool
    password_env: Optional[str]


@dataclass
class MaintenanceConfig:
    enabled: bool
    day_of_week: str
    time: str


@dataclass
class CredentialProfile:
    name: str
    type: str
    provider: str
    endpoint_url: str
    region: str
    bucket: str
    access_key_env: str
    secret_key_env: str

    def access_key(self, env: Dict[str, str]) -> str:
        return env.get(self.access_key_env, '')

    def secret_key(self, env: Dict[str, str]) -> str:
        return env.get(self.secret_key_env, '')


@dataclass
class BackupPolicy:
    name: str
    enabled: bool
    destination_type: str
    repository_path: Optional[str]
    credential_profile: Optional[str]
    repository_prefix: Optional[str]
    encryption: EncryptionConfig
    backup_time: str
    retention_days: int
    maintenance: MaintenanceConfig
    priority: int

    def restic_password(self, env: Dict[str, str]) -> Optional[str]:
        if not self.encryption.enabled:
            return None
        if not self.encryption.password_env:
            return None
        return env.get(self.encryption.password_env)


@dataclass
class GlobalConfig:
    staging_dir: Path
    max_parallel_destinations: int
    restic_read_concurrency: int
    default_maintenance: MaintenanceConfig


@dataclass
class PgDumpInfo:
    path: Path
    sha256: str
    size_bytes: int
    started_at: str
    finished_at: str


@dataclass
class RunContext:
    run_id: str
    started_at: datetime
    hostname: str
    staging_dir: Path
    pg_dump: Optional[PgDumpInfo] = None
    due_policies: List[BackupPolicy] = field(default_factory=list)
    contentstore_path: Optional[Path] = None

    def metadata_dir(self) -> Path:
        return self.staging_dir / 'metadata'

    def postgres_dir(self) -> Path:
        return self.staging_dir / 'postgres'


@dataclass
class DestinationResult:
    policy_name: str
    success: bool
    snapshot_id: Optional[str] = None
    duration_seconds: float = 0.0
    bytes_processed: int = 0
    bytes_added: int = 0
    solr_bytes_processed: int = 0
    solr_bytes_added: int = 0
    error: Optional[str] = None
    lock_contention: bool = False


@dataclass
class MaintenanceResult:
    policy_name: str
    success: bool
    error: Optional[str] = None
    lock_contention: bool = False


@dataclass
class RunResult:
    run_id: str
    status: str
    started_at: str
    finished_at: str
    destinations: List[DestinationResult] = field(default_factory=list)
    maintenance: List[MaintenanceResult] = field(default_factory=list)
    pg_dump: Optional[Dict[str, Any]] = None
