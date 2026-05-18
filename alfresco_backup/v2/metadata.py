"""Snapshot metadata (run.json) for v2 backups."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .app_config import AppConfig
from .models import BackupPolicy, PgDumpInfo, RunContext

SCHEMA_VERSION = 1


def write_run_metadata(
    config: AppConfig,
    policy: BackupPolicy,
    ctx: RunContext,
    pg_dump: PgDumpInfo,
    backup_started: datetime,
    backup_finished: datetime,
    contentstore_started: datetime,
    contentstore_finished: datetime,
) -> Path:
    meta_dir = ctx.metadata_dir()
    meta_dir.mkdir(parents=True, exist_ok=True)

    doc: Dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'run_id': ctx.run_id,
        'host_id': ctx.hostname,
        'policy_name': policy.name,
        'destination_type': policy.destination_type,
        'backup_started_at': backup_started.isoformat(),
        'backup_finished_at': backup_finished.isoformat(),
        'pg_dump': {
            'filename': pg_dump.path.name,
            'sha256': pg_dump.sha256,
            'size_bytes': pg_dump.size_bytes,
            'started_at': pg_dump.started_at,
            'finished_at': pg_dump.finished_at,
        },
        'contentstore': {
            'source_path': str(config.contentstore_path),
            'started_at': contentstore_started.isoformat(),
            'finished_at': contentstore_finished.isoformat(),
        },
    }

    policy_path = meta_dir / 'policy.json'
    with open(policy_path, 'w', encoding='utf-8') as f:
        json.dump({
            'name': policy.name,
            'destination_type': policy.destination_type,
            'retention_days': policy.retention_days,
            'priority': policy.priority,
        }, f, indent=2)

    run_path = meta_dir / 'run.json'
    with open(run_path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=2)
    return run_path


def load_run_json_from_snapshot_tree(base: Path) -> Dict[str, Any]:
    path = base / 'metadata' / 'run.json'
    if not path.exists():
        raise FileNotFoundError(f"run.json not found under {base}")
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
