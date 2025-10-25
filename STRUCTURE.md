# Alfresco Backup System - Project Structure

## Overview

The project has been reorganized into a cleaner modular structure while maintaining backward compatibility through wrapper scripts in the project root.

## Directory Structure

```
alfresco-largecontentstore-backup/
├── alfresco_backup/          # Main package directory
│   ├── __init__.py
│   ├── backup/               # Backup functionality
│   │   ├── __init__.py
│   │   ├── __main__.py       # Main backup orchestrator
│   │   ├── postgres.py       # PostgreSQL backup
│   │   ├── contentstore.py   # Contentstore backup
│   │   ├── retention.py      # Retention policy
│   │   ├── wal.py            # WAL monitoring
│   │   └── email_alert.py    # Email notifications
│   ├── restore/              # Restore functionality
│   │   ├── __init__.py
│   │   └── __main__.py       # Main restore orchestrator
│   └── utils/                # Shared utilities
│       ├── __init__.py
│       ├── config.py         # Configuration management
│       ├── lock.py           # File locking
│       ├── subprocess_utils.py # Process utilities
│       └── wal_config_check.py # WAL configuration validation
├── backup.py                 # Wrapper script (backward compatibility)
├── restore.py                # Wrapper script (backward compatibility)
├── setup.py                  # Setup wizard
├── requirements.txt          # Python dependencies
└── ... (other files)

## Package Organization

### alfresco_backup.backup
Contains all backup-related functionality:
- `__main__.py`: Main backup orchestration logic
- `postgres.py`: PostgreSQL base backup implementation
- `contentstore.py`: Contentstore rsync backup
- `retention.py`: Automated cleanup of old backups
- `wal.py`: WAL archive monitoring
- `email_alert.py`: Failure notification system

### alfresco_backup.restore
Contains all restore functionality:
- `__main__.py`: Main restore orchestrator with interactive UI
- Full system restore (PostgreSQL + Contentstore)
- Point-in-Time Recovery (PITR)
- Progress bars and detailed logging

### alfresco_backup.utils
Shared utilities used by both backup and restore:
- `config.py`: Configuration loader and validator
- `lock.py`: File-based locking for concurrent execution prevention
- `subprocess_utils.py`: Safe subprocess execution with timeouts
- `wal_config_check.py`: PostgreSQL WAL configuration validation

## Usage

### Traditional Method (Backward Compatible)
```bash
python3 backup.py
python3 restore.py
```

### New Method (Direct Package Access)
```bash
python3 -m alfresco_backup.backup
python3 -m alfresco_backup.restore
```

Both methods work identically. The wrapper scripts maintain full backward compatibility.

## Benefits of New Structure

1. **Clear Separation of Concerns**: Backup, restore, and utilities are clearly separated
2. **Better Maintainability**: Easier to locate and modify specific functionality
3. **Import Clarity**: Clear module hierarchy prevents naming conflicts
4. **Extensibility**: Easy to add new features to specific modules
5. **Backward Compatibility**: Existing scripts and cron jobs continue to work

## Migration Notes

- All existing scripts continue to work unchanged
- Imports in other projects should use the new package structure:
  ```python
  from alfresco_backup.utils.config import BackupConfig
  from alfresco_backup.backup.postgres import backup_postgres
  ```
- Cron jobs require no changes
- Setup script remains in root directory

