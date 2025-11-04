# Setup & Installation

This guide walks through every step required to deploy the Alfresco Backup System. Follow it sequentially or jump to the section that matches your deployment approach.

## Requirements

- Python 3.7+
- PostgreSQL client tools (`pg_dump`, `psql`)
- `rsync`
- `gzip` (standard on most Linux systems)
- Sufficient disk space for database SQL dumps and contentstore snapshots

The automated setup wizard verifies each requirement and explains how to resolve missing dependencies.

## Automated Setup (Recommended)

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/alfresco-largecontentstore-backup.git
cd alfresco-largecontentstore-backup

# Run the setup wizard (sudo recommended for directory ownership fixes)
sudo python3 setup.py
```

The wizard performs the following:

1. Confirms required binaries (`python3`, `pg_dump`, `psql`, `rsync`, `gzip`, `sudo`).
2. Builds the `.env` file interactively.
3. Creates `BACKUP_DIR` and subdirectories (`postgres/`, `contentstore/`) with correct ownership.
4. Creates a dedicated Python virtual environment and installs dependencies.
5. Offers to create a cron job and runs a final verification pass.

If any step encounters issues, the wizard surfaces actionable remediation instructions and highlights what should be completed manually.

## Manual Installation

Use the manual workflow when you prefer explicit control over each step or when the target environment restricts interactive scripts.

### 1. System Preparation

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv postgresql-client rsync gzip
```

### 2. Repository & Virtual Environment

```bash
cd /opt
sudo mkdir -p alfresco-largecontentstore-backup
sudo chown $USER:$USER alfresco-largecontentstore-backup
git clone https://github.com/YOUR_USERNAME/alfresco-largecontentstore-backup.git
cd alfresco-largecontentstore-backup

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Backup Storage

```bash
sudo mkdir -p /mnt/backups/alfresco
sudo chown -R $USER:$USER /mnt/backups/alfresco
sudo chmod 755 /mnt/backups/alfresco
```

### 4. Environment Configuration

Create `.env` based on `env.example` and populate site-specific parameters:

```bash
cat > .env <<'EOF'
# Database Configuration
PGHOST=localhost
PGPORT=5432
PGUSER=alfresco
PGPASSWORD=your_db_password_here
PGDATABASE=postgres
PGSUPERUSER=postgres

# Paths
BACKUP_DIR=/mnt/backups/alfresco
ALF_BASE_DIR=/opt/alfresco

# Retention Policy
RETENTION_DAYS=7

# Email Alerts (optional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=backups@yourcompany.com
SMTP_PASSWORD=your_email_password_here
ALERT_EMAIL=ops-team@yourcompany.com
ALERT_FROM=backups@yourcompany.com
EOF

chmod 600 .env
```

### 5. Permissions & Binaries

```bash
chmod +x backup.py restore.py
```

## PostgreSQL Connection

The backup system uses `pg_dump` to create SQL dumps, which requires standard database connectivity. No special PostgreSQL configuration is needed beyond normal database access.

Ensure:
1. The backup user specified in `PGUSER` has connect privileges to the database.
2. `PGPASSWORD` is correctly set in the `.env` file.
3. PostgreSQL is accessible from the backup host (typically `localhost` for embedded Alfresco PostgreSQL).

The system will automatically use embedded PostgreSQL binaries if available (e.g., `ALF_BASE_DIR/postgresql/bin/pg_dump`), otherwise it falls back to system-installed tools.

## Environment Variable Reference

| Variable | Description |
| --- | --- |
| `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` | Connection parameters for Alfresco's PostgreSQL instance. |
| `BACKUP_DIR` | Root directory for storing backups (`postgres/`, `contentstore/`). |
| `ALF_BASE_DIR` | Alfresco installation directory containing scripts and data. |
| `RETENTION_DAYS` | Number of days to retain backups before cleanup (default: 7). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | SMTP credentials for failure notifications (optional). |
| `ALERT_EMAIL`, `ALERT_FROM` | Notification recipient and sender addresses. |

## Post-Installation Checklist

- Activate the virtual environment and run `python backup.py --help` to confirm dependencies.
- Verify the cron log directory (if scheduled) is writable by the Alfresco user.
- Run a test backup (`python backup.py`) and verify SQL dump files are created in `BACKUP_DIR/postgres/`.
- Confirm backup files have reasonable sizes (not empty or suspiciously small).
- Review `../operations/backup-guide.md` to schedule backups and monitor results.
