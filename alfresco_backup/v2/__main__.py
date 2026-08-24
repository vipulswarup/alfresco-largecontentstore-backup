#!/usr/bin/env python3
"""Restic-based Alfresco backup (single or multiple destinations)."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from .app_config import AppConfig, POLICIES_FILENAME
from .migration import migrate_legacy_env, needs_migration
from .orchestrator import run_backup
from .size_report import generate_size_report


def setup_logging(staging_dir: Path) -> None:
    log_dir = staging_dir / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"backup-{datetime.now().strftime('%Y-%m-%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _load_config() -> AppConfig:
    env_path = Path('.env')
    policies_path = Path(POLICIES_FILENAME)

    if not env_path.exists():
        print("ERROR: .env not found. Run: python3 setup.py")
        sys.exit(1)

    if needs_migration(env_path, policies_path):
        created, msg = migrate_legacy_env(env_path, policies_path)
        print(msg)
        if not created:
            sys.exit(1)

    if not policies_path.exists():
        print(
            "ERROR: backup-policies.yml not found. "
            "Run setup.py and choose single or multiple destination setup."
        )
        sys.exit(1)

    from .setup_wizard import _ensure_policy_passwords
    _ensure_policy_passwords(env_path, policies_path)

    try:
        return AppConfig(str(env_path), str(policies_path))
    except Exception as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


def main(force_all_destinations: bool = False) -> None:
    size_report = False
    force = force_all_destinations
    if not force_all_destinations:
        parser = argparse.ArgumentParser(
            description='Alfresco restic backup',
        )
        parser.add_argument(
            '--size-report',
            action='store_true',
            help='Print full vs incremental backup sizes for each destination snapshot',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Run all enabled destinations regardless of schedule',
        )
        args = parser.parse_args()
        size_report = args.size_report
        force = args.force

    config = _load_config()
    setup_logging(config.global_config.staging_dir)

    if size_report:
        logging.info("Generating backup size report")
        print(generate_size_report(config), end='')
        return

    logging.info("=" * 70)
    logging.info("Alfresco backup started (restic)")
    logging.info("=" * 70)

    run_backup(config, force=force)


if __name__ == '__main__':
    main()
