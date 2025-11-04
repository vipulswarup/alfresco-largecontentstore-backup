# Architecture Overview

This project provides a production-grade backup and restore system for Alfresco’s content repository and embedded PostgreSQL instance. The Python package `alfresco_backup` is organised to keep backup, restore, and shared utilities isolated while retaining simple wrapper scripts for backward compatibility.

## Package Layout

```
alfresco-largecontentstore-backup/
├── alfresco_backup/
│   ├── backup/
│   ├── restore/
│   └── utils/
├── backup.py
└── restore.py
```

### `alfresco_backup.backup`
- `__main__.py`: Orchestrates the full backup run (configuration, locking, logging, step execution, email alerts).
- `postgres.py`: Executes `pg_dump` to create compressed SQL dump files (preferring embedded Alfresco binaries).
- `contentstore.py`: Snapshots the contentstore via `rsync` with optional hardlink optimisation.
- `retention.py`: Applies time-based retention policy to PostgreSQL SQL dumps and contentstore snapshots.
- `email_alert.py`: Sends failure notifications when any backup step fails.

### `alfresco_backup.restore`
- `__main__.py`: Interactive restore runner covering full system restores and component-level recovery with progress feedback.

### `alfresco_backup.utils`
- `config.py`: Loads `.env` configuration values and enforces required settings.
- `lock.py`: Provides a file-based guard to prevent concurrent backup executions.
- `subprocess_utils.py`: Offers a consistent interface for long-running shell commands plus safe filesystem helpers.

## Entry Points

- `backup.py`: Thin wrapper that forwards execution to `alfresco_backup.backup.__main__.main()` to maintain legacy CLI usage.
- `restore.py`: Wrapper for `alfresco_backup.restore.__main__.main()` for the interactive restore workflow.

These wrappers ensure existing cron jobs or scripts that invoke the root-level files continue to function after the package refactor.

## Backup Control Flow

1. Load configuration and create the daily log file.
2. Acquire the process lock to prevent concurrent executions.
3. Run PostgreSQL SQL dump, contentstore snapshot, and retention policy in sequence.
4. Summarise outcomes, release the lock, and emit alerts when needed.

## Restore Responsibilities

The restore runner collects configuration interactively, validates selected backups, stops Alfresco safely, backs up current data, and restores PostgreSQL from SQL dumps and contentstore from snapshots. The system supports full system restores and component-level recovery (PostgreSQL-only or contentstore-only).

## Extension Guidelines

- Keep operational logic inside the existing package namespaces to preserve module boundaries.
- Surface new end-user flows via `__main__.py` or dedicated CLI wrappers instead of modifying the root scripts directly.
- Reuse shared helpers from `alfresco_backup.utils` to maintain consistent logging, locking, and subprocess behaviour.


