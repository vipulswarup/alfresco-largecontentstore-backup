"""Interactive v2 complete-set restore workflow."""

import gzip
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .app_config import AppConfig
from .integrity import IntegrityRepairer
from .restore_planner import RestorePlanner, RestorableSet
from alfresco_backup.restore.alfresco_control import (
    clear_solr_indexes,
    confirm_alf_base_dir,
    start_tomcat,
    stop_tomcat,
)

logger = logging.getLogger(__name__)


def run_v2_restore_interactive(config: AppConfig) -> int:
    alfresco_user = os.getenv('ALFRESCO_USER', os.getenv('USER', 'alfresco'))
    alf_base = confirm_alf_base_dir(config.alf_base_dir)

    planner = RestorePlanner(config)
    groups = planner.list_complete_sets()

    if not groups:
        print("No v2 complete-set backups found in configured destinations.")
        return 1

    print("\n" + "=" * 80)
    print("  V2 Multi-Destination Restore")
    print("=" * 80)
    print("\nConfigured destinations (by priority):")
    for p in config.policies_by_priority():
        print(f"  - {p.name} (priority {p.priority}, {p.destination_type})")

    runs = sorted(groups.keys(), key=lambda r: max(s.time for s in groups[r]), reverse=True)
    print("\nRestorable complete sets (by run_id):")
    for i, run_id in enumerate(runs[:20], 1):
        sets = groups[run_id]
        primary = sets[0]
        print(
            f"  {i}. {run_id}  @ {primary.time.strftime('%Y-%m-%d %H:%M')} "
            f"via {primary.policy_name}"
        )

    choice = input(f"\nSelect run (1-{min(len(runs), 20)}): ").strip()
    try:
        idx = int(choice) - 1
        run_id = runs[idx]
    except (ValueError, IndexError):
        print("Invalid selection")
        return 1

    source = planner.select_source(run_id)
    if not source:
        print(f"No complete set found for run_id {run_id}")
        return 1

    print(f"\nPrimary source: {source.policy_name} snapshot {source.snapshot_id}")
    confirm = input("Type 'RESTORE' to continue: ").strip()
    if confirm != 'RESTORE':
        print("Cancelled.")
        return 0

    if not stop_tomcat(alf_base, alfresco_user):
        print("ERROR: Could not stop Tomcat. Aborting restore.")
        return 1

    staging = Path(tempfile.mkdtemp(prefix='alfresco-v2-restore-'))
    logger.info(f"Staging restore at {staging}")

    restored = _restore_with_fallback(config, planner, run_id, staging)
    if not restored:
        shutil.rmtree(staging, ignore_errors=True)
        return 1

    pg_gz = staging / 'postgres' / 'postgres.sql.gz'
    if not pg_gz.exists():
        pg_candidates = list(staging.rglob('postgres.sql.gz'))
        if pg_candidates:
            pg_gz = pg_candidates[0]

    cs_staged = staging / 'contentstore'
    if not cs_staged.exists():
        cs_candidates = list(staging.rglob('contentstore'))
        if cs_candidates:
            cs_staged = cs_candidates[0]

    if not pg_gz.exists() or not cs_staged.exists():
        print("Restore incomplete: missing postgres dump or contentstore in snapshot")
        return 1

    print("\nRestoring PostgreSQL from staged dump...")
    if not _restore_postgres(config, pg_gz):
        return 1

    print("Verifying content integrity...")
    repairer = IntegrityRepairer(config, cs_staged)
    ok, missing = repairer.verify()
    if not ok:
        print(f"Missing {len(missing)} content file(s); attempting repair...")
        report = repairer.repair(run_id, missing)
        ok = report.passed
        if not ok:
            print("\nIntegrity verification FAILED. Unresolved paths:")
            for p in report.unresolved_paths[:50]:
                print(f"  {p}")
            print("\nSources searched:")
            for s in report.sources_searched:
                print(f"  {s}")
            print("\nAlfresco startup blocked.")
            return 1

    live_cs = config.contentstore_path
    backup_cs = live_cs.parent / f"contentstore.pre-restore-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    if live_cs.exists():
        print(f"Moving current contentstore to {backup_cs}")
        live_cs.rename(backup_cs)

    print(f"Installing restored contentstore to {live_cs}")
    shutil.copytree(cs_staged, live_cs)
    _chown_recursive(live_cs, alfresco_user)

    print("\nDatabase and contentstore restore completed.")
    print("Solr4 indexes should be cleared after a restore to avoid search errors.")
    clear_indexes = input("Clear Solr4 indexes now? [Y/n]: ").strip().lower()
    if clear_indexes != 'n':
        if not clear_solr_indexes(alf_base, alfresco_user):
            print("ERROR: Failed to clear Solr indexes.")
            shutil.rmtree(staging, ignore_errors=True)
            return 1
    else:
        print("Skipping Solr index clearing.")

    if not start_tomcat(alf_base, alfresco_user):
        print("ERROR: Failed to start Tomcat.")
        shutil.rmtree(staging, ignore_errors=True)
        return 1

    print("\nV2 restore completed successfully.")
    shutil.rmtree(staging, ignore_errors=True)
    return 0


def _restore_with_fallback(
    config: AppConfig,
    planner: RestorePlanner,
    run_id: str,
    staging: Path,
) -> bool:
    candidates = planner.fallback_sources(run_id)
    for source in candidates:
        print(f"Restoring from {source.policy_name}...")
        if _restore_snapshot(config, source, staging):
            meta = staging / 'metadata' / 'run.json'
            if not meta.exists():
                metas = list(staging.rglob('run.json'))
                if metas:
                    meta = metas[0]
            if meta.exists():
                import json
                with open(meta) as f:
                    data = json.load(f)
                if data.get('run_id') == run_id:
                    return True
            return True
    return False


def _restore_snapshot(config: AppConfig, source: RestorableSet, staging: Path) -> bool:
    policy = None
    for p in config.backup_policies:
        if p.name == source.policy_name:
            policy = p
            break
    if not policy:
        return False
    profile = (
        config.get_profile(policy.credential_profile)
        if policy.credential_profile
        else None
    )
    from .restic import ResticRepository
    repo = ResticRepository(policy, config, profile)
    r = repo.restore(source.snapshot_id, staging)
    return r.get('success', False)


def _restore_postgres(config: AppConfig, pg_gz: Path) -> bool:
    env = {'PGPASSWORD': config.pgpassword, 'PATH': os.environ.get('PATH', '')}
    psql = 'psql'
    embedded = config.alf_base_dir / 'postgresql' / 'bin' / 'psql'
    if embedded.exists():
        psql = str(embedded)

    try:
        with gzip.open(pg_gz, 'rb') as f_in:
            proc = subprocess.Popen(
                [psql, '-h', config.pghost, '-p', config.pgport,
                 '-U', config.pguser, '-d', config.pgdatabase],
                stdin=subprocess.PIPE,
                env=env,
            )
            while True:
                chunk = f_in.read(1024 * 1024)
                if not chunk:
                    break
                proc.stdin.write(chunk)
            proc.stdin.close()
            proc.wait(timeout=86400)
            return proc.returncode == 0
    except Exception as e:
        logger.error(f"PostgreSQL restore failed: {e}")
        return False


def _chown_recursive(path: Path, user: str) -> None:
    try:
        import pwd
        uid = pwd.getpwnam(user).pw_uid
        for root, dirs, files in os.walk(path):
            os.chown(root, uid, -1)
            for name in files:
                os.chown(os.path.join(root, name), uid, -1)
    except (ImportError, KeyError, PermissionError) as e:
        logger.warning(f"Could not set ownership to {user}: {e}")
