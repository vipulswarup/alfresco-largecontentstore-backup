#!/usr/bin/env python3
"""Restic-based Alfresco backup (single or multiple destinations)."""

import logging
import sys
from datetime import datetime
from pathlib import Path

from .app_config import AppConfig, POLICIES_FILENAME
from .migration import migrate_legacy_env, needs_migration
from .orchestrator import run_backup


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


def main(force_all_destinations: bool = False) -> None:
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

    config = AppConfig(str(env_path), str(policies_path))
    setup_logging(config.global_config.staging_dir)

    logging.info("=" * 70)
    logging.info("Alfresco backup started (restic)")
    logging.info("=" * 70)

    run_backup(config, force=force_all_destinations)


if __name__ == '__main__':
    main()
