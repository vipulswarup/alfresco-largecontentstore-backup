# Alfresco Backup System

Python-based backup and restore tooling for Alfresco deployments, including PostgreSQL base backups, contentstore snapshots, retention, and PITR readiness.

## Feature Highlights

- PostgreSQL base backups via `pg_basebackup` with WAL validation for PITR
- Contentstore snapshots using `rsync` and hardlinks for space efficiency
- Automated retention, logging, locking, and failure email alerts
- Interactive restore workflow covering full, partial, and point-in-time recovery
- Backward-compatible wrapper scripts for existing cron jobs and tooling

## Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/alfresco-largecontentstore-backup.git
cd alfresco-largecontentstore-backup
sudo python3 setup.py   # Runs the guided installer
```

After installation, schedule the backup script or run it manually:

```bash
python backup.py
```

## Documentation Map

- [Setup & Installation](docs/setup/installation.md)
- [Backup Operations Guide](docs/operations/backup-guide.md)
- [Restore Runbook](docs/operations/restore-runbook.md)
- [Restore Quick Reference](docs/operations/restore-cheatsheet.md)
- [Maintenance & Security Guide](docs/operations/maintenance-and-security.md)
- [Architecture Overview](docs/architecture.md)

Each document covers a mutually exclusive topic; read them in combination for complete coverage.

## Project Structure

- `alfresco_backup/` — Python package containing backup, restore, and utility modules
- `backup.py`, `restore.py` — Legacy entry points that forward to the package orchestrators
- `docs/` — Consolidated documentation set (see map above)
- `setup.py` — Interactive wizard for first-time installations

## Contributing

Issues and improvements are welcome. Please keep changes modular, retain backward compatibility with wrapper scripts, and update the documentation map as needed.

## License

Released under the MIT License. See [`LICENSE`](LICENSE) for details.

