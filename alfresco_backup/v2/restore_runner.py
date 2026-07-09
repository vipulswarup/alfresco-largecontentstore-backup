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
    ensure_postgresql_ready,
    start_tomcat,
    stop_tomcat,
)
from alfresco_backup.restore.restore_ux import (
    PRODUCT_NAME,
    ask_yes_no,
    clear_restore_session,
    collect_v2_preflight_checks,
    confirm_destructive_restore,
    load_restore_session,
    preflight_failed,
    print_failure_guidance,
    print_preflight,
    print_restore_plan,
    print_restore_summary,
    save_restore_session,
)

logger = logging.getLogger(__name__)


def run_v2_restore_interactive(config: AppConfig, alf_base: Path = None, dry_run: bool = False) -> int:
    alfresco_user = os.getenv('ALFRESCO_USER', os.getenv('USER', 'alfresco'))
    if alf_base is None:
        alf_base = confirm_alf_base_dir(config.restore_alf_base_dir)
    os.environ['EISENVAULT_RESTORE_DIR'] = str(alf_base)

    print_restore_plan([
        "Confirm the EisenVault restore folder.",
        "Select a complete backup run.",
        "Validate backup source, restore folder, database connection, and staging space.",
        "Stop Tomcat while keeping PostgreSQL available.",
        "Stage the selected backup snapshot.",
        "Restore PostgreSQL from the staged dump.",
        "Verify contentstore integrity and repair from fallback destinations if possible.",
        "Move the current contentstore aside and install the restored contentstore.",
        "Clear Solr indexes so EisenVault can rebuild search data.",
        "Start Tomcat.",
    ])

    planner = RestorePlanner(config)
    groups = planner.list_complete_sets()

    if not groups:
        print("No complete EisenVault backup sets found in configured destinations.")
        return 1

    print("\n" + "=" * 80)
    print("  EisenVault Complete Backup Restore")
    print("=" * 80)
    print("\nConfigured destinations (by priority):")
    for p in config.policies_by_priority():
        print(f"  - {p.name} (priority {p.priority}, {p.destination_type})")

    runs = sorted(groups.keys(), key=lambda r: max(s.time for s in groups[r]), reverse=True)
    session = load_restore_session()
    resume_session = False
    run_id = None
    if session and session.get('workflow') == 'v2-complete-restore':
        session_run = session.get('run_id')
        if session_run in groups:
            last_step = session.get('last_completed_step', 'selection')
            print("\nPrevious restore session found:")
            print(f"  Run: {session_run}")
            if session.get('source'):
                print(f"  Source: {session['source']}")
            if session.get('staging'):
                print(f"  Staging: {session['staging']}")
            print(f"  Last completed step: {last_step}")
            if last_step in ('selection', 'snapshot_staged'):
                resume_session = ask_yes_no("Resume this restore selection?", default=True)
                if resume_session:
                    run_id = session_run
            else:
                print("This session reached a data-changing step.")
                print("Review the recovery guidance and select the restore run again if you want to proceed.")
                print_failure_guidance(
                    alf_base,
                    Path(session['contentstore_backup']) if session.get('contentstore_backup') else None,
                )

    print("\nRestorable complete sets (by run_id):")
    for i, listed_run_id in enumerate(runs[:20], 1):
        sets = groups[listed_run_id]
        primary = sets[0]
        print(
            f"  {i}. {listed_run_id}  @ {primary.time.strftime('%Y-%m-%d %H:%M')} "
            f"via {primary.policy_name}"
        )

    if not run_id:
        max_choice = min(len(runs), 20)
        while True:
            choice = input(f"\nSelect run (1-{max_choice}): ").strip()
            try:
                idx = int(choice) - 1
                if 0 <= idx < max_choice:
                    run_id = runs[idx]
                    break
            except ValueError:
                pass
            print(f"Please enter a number between 1 and {max_choice}.")

    source = planner.select_source(run_id)
    if not source:
        print(f"No complete set found for run_id {run_id}")
        return 1

    print(f"\nPrimary source: {source.policy_name} snapshot {source.snapshot_id}")
    backup_source = f"{source.policy_name} snapshot {source.snapshot_id}"
    session_data = {
        'workflow': 'v2-complete-restore',
        'run_id': run_id,
        'source': backup_source,
        'restore_folder': str(alf_base),
        'last_completed_step': 'selection',
    }
    print_restore_summary(
        alf_base,
        "Complete backup restore",
        backup_source,
        run_id,
        config.pghost,
        config.pgport,
        config.pguser,
        config.pgdatabase,
    )
    checks = collect_v2_preflight_checks(
        alf_base,
        backup_source,
        config.pghost,
        config.pgport,
        config.pguser,
        config.pgpassword,
        config.pgdatabase,
    )
    print_preflight("Preflight Checks", checks)
    if preflight_failed(checks):
        print("\nRequired preflight checks failed. Fix the failed item(s) and run restore again.")
        return 1
    if dry_run:
        print("\nDry run complete. No services were stopped and no data was changed.")
        return 0
    if not confirm_destructive_restore(alf_base):
        clear_restore_session()
        return 0
    save_restore_session(session_data)

    if not stop_tomcat(alf_base, alfresco_user):
        print("ERROR: Could not stop Tomcat. EisenVault restore cannot continue safely.")
        print_failure_guidance(alf_base)
        return 1

    if not ensure_postgresql_ready(
        alf_base,
        alfresco_user,
        config.pghost,
        config.pgport,
        config.pguser,
        config.pgpassword,
        config.pgdatabase,
    ):
        print("ERROR: PostgreSQL is required for database restore.")
        print_failure_guidance(alf_base)
        return 1

    if stop_tomcat(alf_base, alfresco_user) is False:
        print("ERROR: Could not keep Tomcat stopped after starting PostgreSQL.")
        print_failure_guidance(alf_base)
        return 1

    staging = None
    reuse_staged_snapshot = False
    if resume_session and session:
        session_staging = session.get('staging')
        if session_staging:
            candidate = Path(session_staging)
            if (
                candidate.exists()
                and session.get('last_completed_step') == 'snapshot_staged'
                and (candidate / 'postgres').exists()
            ):
                staging = candidate
                reuse_staged_snapshot = True
                print(f"Reusing staged snapshot from previous session: {staging}")
    if staging is None:
        staging = Path(tempfile.mkdtemp(prefix='alfresco-v2-restore-'))
    logger.info(f"Staging restore at {staging}")
    backup_cs = None
    session_data['staging'] = str(staging)

    if not reuse_staged_snapshot:
        restored = _restore_with_fallback(config, planner, run_id, staging)
        if not restored:
            print(f"ERROR: Could not restore snapshot {run_id} from any configured destination.")
            shutil.rmtree(staging, ignore_errors=True)
            session_data.pop('staging', None)
            print_failure_guidance(alf_base)
            save_restore_session(session_data)
            return 1
        session_data['last_completed_step'] = 'snapshot_staged'
        save_restore_session(session_data)

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
        save_restore_session(session_data)
        print_failure_guidance(alf_base)
        return 1

    print("\nRestoring PostgreSQL from staged dump...")
    if not _restore_postgres(config, pg_gz):
        session_data['last_completed_step'] = 'postgres_restore_failed'
        save_restore_session(session_data)
        print_failure_guidance(alf_base)
        return 1
    session_data['last_completed_step'] = 'postgres_restored'
    save_restore_session(session_data)

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
            print(f"\n{PRODUCT_NAME} startup blocked.")
            session_data['last_completed_step'] = 'integrity_failed'
            session_data['last_error'] = (
                f"Content integrity verification failed: "
                f"{len(report.unresolved_paths)} unresolved content file(s)."
            )
            session_data['unresolved_content_count'] = len(report.unresolved_paths)
            session_data['unresolved_content_examples'] = report.unresolved_paths[:20]
            session_data['sources_searched'] = report.sources_searched
            save_restore_session(session_data)
            print_failure_guidance(alf_base)
            return 1

    live_cs = config.restore_contentstore_path
    backup_cs = live_cs.parent / f"contentstore.pre-restore-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    if backup_cs.exists():
        print(f"ERROR: Contentstore backup path already exists: {backup_cs}")
        session_data['last_completed_step'] = 'contentstore_backup_path_conflict'
        save_restore_session(session_data)
        print_failure_guidance(alf_base, backup_cs)
        return 1
    if live_cs.exists():
        print(f"Moving current contentstore to {backup_cs}")
        live_cs.rename(backup_cs)
        session_data['contentstore_backup'] = str(backup_cs)
        session_data['last_completed_step'] = 'contentstore_moved'
        save_restore_session(session_data)
        if live_cs.exists() or not backup_cs.exists():
            print("ERROR: Could not verify current contentstore was moved safely.")
            print_failure_guidance(alf_base, backup_cs)
            return 1

    print(f"Installing restored contentstore to {live_cs}")
    shutil.copytree(cs_staged, live_cs)
    _chown_recursive(live_cs, alfresco_user)
    session_data['last_completed_step'] = 'contentstore_installed'
    save_restore_session(session_data)

    print("\nDatabase and contentstore restore completed.")
    print("Solr4 indexes should be cleared after a restore to avoid search errors.")
    clear_indexes = input("Clear Solr4 indexes now? [Y/n]: ").strip().lower()
    if clear_indexes != 'n':
        if not clear_solr_indexes(alf_base, alfresco_user):
            print("ERROR: Failed to clear Solr indexes.")
            session_data['last_completed_step'] = 'solr_clear_failed'
            save_restore_session(session_data)
            print_failure_guidance(alf_base, backup_cs)
            return 1
    else:
        print("Skipping Solr index clearing.")

    if not start_tomcat(alf_base, alfresco_user):
        print("ERROR: Failed to start Tomcat.")
        session_data['last_completed_step'] = 'tomcat_start_failed'
        save_restore_session(session_data)
        print_failure_guidance(alf_base, backup_cs)
        return 1

    print(f"\n{PRODUCT_NAME} restore completed successfully.")
    shutil.rmtree(staging, ignore_errors=True)
    clear_restore_session()
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
    embedded = config.restore_alf_base_dir / 'postgresql' / 'bin' / 'psql'
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
