"""V2 backup orchestration."""

import logging
import socket
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from alfresco_backup.utils.lock import FileLock

from .app_config import AppConfig
from .destination_task import DestinationBackupTask
from .email_report import send_run_report
from .maintenance import MaintenanceTask
from .models import DestinationResult, MaintenanceResult, RunContext, RunResult
from .pg_dump import create_shared_pg_dump
from .schedule import is_backup_due, is_maintenance_due

logger = logging.getLogger(__name__)


def _policy_staging(base: Path, policy_name: str) -> Path:
    return base / policy_name


def run_backup(config: AppConfig, force: bool = False) -> RunResult:
    now = datetime.now()
    due_backup = []
    due_maint = []

    for policy in config.enabled_policies():
        if force or is_backup_due(policy.backup_time, now):
            due_backup.append(policy)
        if is_maintenance_due(
            policy.maintenance.enabled,
            policy.maintenance.day_of_week,
            policy.maintenance.time,
            now,
        ):
            due_maint.append(policy)

    run_result = RunResult(
        run_id='',
        status='success',
        started_at=now.isoformat(),
        finished_at='',
    )

    lock_path = config.global_config.staging_dir / 'backup-v2.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with FileLock(str(lock_path)):
            if not due_backup and not due_maint:
                logger.info("No destinations or maintenance due; exiting.")
                run_result.status = 'success'
                run_result.finished_at = datetime.now().isoformat()
                return run_result

            if not due_backup:
                run_result = _run_maintenance_only(config, due_maint, run_result)
                return run_result

            run_id = datetime.now().strftime('%Y%m%d-%H%M-%S') + '-' + uuid.uuid4().hex[:8]
            run_result.run_id = run_id
            staging = config.global_config.staging_dir / run_id
            staging.mkdir(parents=True, exist_ok=True)

            ctx = RunContext(
                run_id=run_id,
                started_at=now,
                hostname=socket.gethostname(),
                staging_dir=staging,
                due_policies=due_backup,
                contentstore_path=config.contentstore_path,
            )

            logger.info(f"Run {run_id}: shared pg_dump for {len(due_backup)} destination(s)")
            pg_dump = create_shared_pg_dump(config, ctx)
            run_result.pg_dump = {
                'sha256': pg_dump.sha256,
                'size_bytes': pg_dump.size_bytes,
            }

            backing_up = {p.name for p in due_backup}
            dest_results = _run_destinations_parallel(config, due_backup, ctx, pg_dump)
            run_result.destinations = dest_results

            success_count = sum(1 for d in dest_results if d.success)
            if success_count == len(dest_results):
                run_result.status = 'success'
            elif success_count > 0:
                run_result.status = 'partial_success'
            else:
                run_result.status = 'failure'

            post_backup_policies = [
                p for p in due_backup
                if _destination_succeeded(dest_results, p.name)
                and not _failed_lock(dest_results, p.name)
            ]
            post_backup_maintenance = _run_maintenance(config, post_backup_policies)
            maintained = {m.policy_name for m in post_backup_maintenance}

            maint_policies = [
                p for p in due_maint
                if p.name not in backing_up
                and p.name not in maintained
                and not _failed_lock(dest_results, p.name)
            ]
            scheduled_maintenance = _run_maintenance(config, maint_policies)
            run_result.maintenance = post_backup_maintenance + scheduled_maintenance

            run_result.finished_at = datetime.now().isoformat()
            send_run_report(config, run_result)

            if run_result.status != 'success':
                for dest in run_result.destinations:
                    if not dest.success:
                        logger.error(
                            f"Destination {dest.policy_name} failed: {dest.error}"
                        )

            if run_result.status == 'failure':
                sys.exit(1)
            if run_result.status == 'partial_success':
                sys.exit(2)
            return run_result

    except RuntimeError as e:
        logger.error(f"Could not acquire lock: {e}")
        sys.exit(1)


def _run_destinations_parallel(config, policies, ctx, pg_dump):
    results = []
    max_workers = min(config.global_config.max_parallel_destinations, len(policies))

    def _task(policy):
        policy_ctx = RunContext(
            run_id=ctx.run_id,
            started_at=ctx.started_at,
            hostname=ctx.hostname,
            staging_dir=_policy_staging(ctx.staging_dir, policy.name),
            contentstore_path=ctx.contentstore_path,
        )
        policy_ctx.staging_dir.mkdir(parents=True, exist_ok=True)
        return DestinationBackupTask(config, policy, policy_ctx).run(pg_dump)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_task, p): p for p in policies}
        for future in as_completed(futures):
            results.append(future.result())
    return results


def _failed_lock(dest_results, policy_name: str) -> bool:
    for d in dest_results:
        if d.policy_name == policy_name and d.lock_contention:
            return True
    return False


def _destination_succeeded(dest_results, policy_name: str) -> bool:
    for d in dest_results:
        if d.policy_name == policy_name:
            return d.success
    return False


def _run_maintenance(config, policies) -> list:
    results = []
    for policy in policies:
        results.append(MaintenanceTask(config, policy).run())
    return results


def _run_maintenance_only(config, policies, run_result: RunResult) -> RunResult:
    run_result.maintenance = _run_maintenance(config, policies)
    run_result.finished_at = datetime.now().isoformat()
    any_fail = any(not m.success for m in run_result.maintenance)
    run_result.status = 'failure' if any_fail else 'success'
    send_run_report(config, run_result)
    if any_fail:
        sys.exit(1)
    return run_result
