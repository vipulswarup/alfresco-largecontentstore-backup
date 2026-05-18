#!/usr/bin/env python3
"""V2 multi-destination backup entry point."""

import logging
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

from .app_config import AppConfig, POLICIES_FILENAME
from .migration import migrate_legacy_env, needs_migration
from .orchestrator import run_backup


def setup_logging(staging_dir: Path) -> None:
    log_dir = staging_dir / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"backup-v2-{datetime.now().strftime('%Y-%m-%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    parser = ArgumentParser(description='Alfresco v2 multi-destination backup')
    parser.add_argument('env_file', nargs='?', default='.env')
    parser.add_argument('--policies', default=POLICIES_FILENAME)
    parser.add_argument('--force', action='store_true', help='Run all enabled destinations now')
    parser.add_argument('--migrate-only', action='store_true')
    args = parser.parse_args()

    env_path = Path(args.env_file)
    policies_path = Path(args.policies)

    if needs_migration(env_path, policies_path):
        created, msg = migrate_legacy_env(env_path, policies_path)
        print(msg)
        if not created:
            sys.exit(1)

    if args.migrate_only:
        sys.exit(0)

    config = AppConfig(str(env_path), str(policies_path))
    setup_logging(config.global_config.staging_dir)

    logging.info("=" * 70)
    logging.info("Alfresco backup v2 started")
    logging.info("=" * 70)

    run_backup(config, force=args.force)


if __name__ == '__main__':
    main()
