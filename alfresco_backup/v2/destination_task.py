"""Backup one destination from a shared RunContext."""

import logging
import shutil
from datetime import datetime
from pathlib import Path

from .app_config import AppConfig
from .metadata import write_run_metadata
from .models import BackupPolicy, DestinationResult, PgDumpInfo, RunContext
from .restic import ResticRepository

logger = logging.getLogger(__name__)


class DestinationBackupTask:
    def __init__(self, config: AppConfig, policy: BackupPolicy, ctx: RunContext):
        self.config = config
        self.policy = policy
        self.ctx = ctx
        profile = config.get_profile(policy.credential_profile) if policy.credential_profile else None
        self.repo = ResticRepository(policy, config, profile)

    def run(self, pg_dump: PgDumpInfo) -> DestinationResult:
        started = datetime.now()
        result = DestinationResult(policy_name=self.policy.name, success=False)

        try:
            if self.policy.destination_type == 'filesystem':
                Path(self.policy.repository_path).mkdir(parents=True, exist_ok=True)

            init_r = self.repo.init()
            if not init_r['success'] and 'already exists' not in (init_r.get('error') or '').lower():
                if not self._repo_accessible():
                    result.error = init_r.get('error', 'repository init failed')
                    result.lock_contention = init_r.get('lock_contention', False)
                    return result

            cs_start = datetime.now()
            backup_started = datetime.now()
            write_run_metadata(
                self.config,
                self.policy,
                self.ctx,
                pg_dump,
                backup_started,
                backup_started,
                cs_start,
                cs_start,
            )
            self._stage_postgres(pg_dump)

            backup_paths = [
                self.ctx.metadata_dir(),
                self.ctx.postgres_dir(),
                self.config.contentstore_path,
            ]
            tags = [
                'app:alfresco-backup',
                f'run:{self.ctx.run_id}',
                f'policy:{self.policy.name}',
                'kind:complete-set',
            ]
            br = self.repo.backup(backup_paths, tags)
            backup_finished = datetime.now()
            cs_end = backup_finished

            if not br['success']:
                result.error = br.get('error', 'restic backup failed')
                result.lock_contention = br.get('lock_contention', False)
                result.duration_seconds = (datetime.now() - started).total_seconds()
                return result

            result.success = True
            result.snapshot_id = br.get('snapshot_id')
            result.bytes_processed = int(br.get('bytes_processed', 0))
            result.duration_seconds = (datetime.now() - started).total_seconds()
            logger.info(
                f"Destination {self.policy.name}: snapshot {result.snapshot_id} "
                f"in {result.duration_seconds:.1f}s"
            )
        except Exception as e:
            result.error = str(e)
            result.duration_seconds = (datetime.now() - started).total_seconds()
            logger.exception(f"Destination {self.policy.name} failed: {e}")

        return result

    def _repo_accessible(self) -> bool:
        check = self.repo.check()
        if check['success']:
            return True
        snaps = self.repo.snapshots_json()
        return snaps['success']

    def _stage_postgres(self, pg_dump: PgDumpInfo) -> None:
        dest_postgres = self.ctx.postgres_dir()
        dest_postgres.mkdir(parents=True, exist_ok=True)
        target = dest_postgres / 'postgres.sql.gz'
        if pg_dump.path.resolve() != target.resolve():
            shutil.copy2(pg_dump.path, target)
