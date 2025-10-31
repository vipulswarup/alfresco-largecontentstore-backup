# Setup & Installation

This guide walks through every step required to deploy the Alfresco Backup System, from prerequisites to WAL configuration. Follow it sequentially or jump to the section that matches your deployment approach.

## Requirements

- Python 3.7+
- PostgreSQL client tools (`pg_basebackup`)
- `rsync`
- Sufficient disk space for database and contentstore snapshots

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

1. Confirms required binaries (`python3`, `pg_basebackup`, `rsync`, `sudo`).
2. Builds the `.env` file interactively.
3. Creates `BACKUP_DIR` and subdirectories with correct ownership.
4. Configures WAL archive permissions and updates `postgresql.conf` / `pg_hba.conf` with PostgreSQL 9.4–compatible settings.
5. Restarts Alfresco and grants replication privileges to the backup user.
6. Creates a dedicated Python virtual environment and installs dependencies.
7. Offers to create a cron job and runs a final verification pass.

If any step encounters issues, the wizard surfaces actionable remediation instructions and highlights what should be completed manually.

## Manual Installation

Use the manual workflow when you prefer explicit control over each step or when the target environment restricts interactive scripts.

### 1. System Preparation

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv postgresql-client rsync
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
RETENTION_DAYS=30

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

## PostgreSQL WAL Configuration

Point-in-time recovery and base backups require WAL archiving. The setup wizard automates the configuration for Alfresco’s embedded PostgreSQL 9.4, but the steps can be performed manually:

1. Locate `postgresql.conf` (typically under `ALF_BASE_DIR/postgresql/` or `ALF_BASE_DIR/alf_data/postgresql/`).
2. Ensure the following settings are present:

   ```conf
   wal_level = hot_standby
   archive_mode = on
   archive_command = 'test ! -f /mnt/backups/alfresco/pg_wal/%f && cp %p /mnt/backups/alfresco/pg_wal/%f'
   max_wal_senders = 3
   wal_keep_segments = 64
   ```

3. Update `pg_hba.conf` to allow replication connections from the backup user over local socket and loopback interfaces.
4. Create the WAL archive directory (`BACKUP_DIR/pg_wal`) and set ownership to both the PostgreSQL service user and the operational user (e.g., `postgres:evadm`).
5. Restart Alfresco/PostgreSQL and grant the replication privilege:

   ```bash
   psql -h localhost -U PGSUPERUSER -d postgres -c "ALTER USER PGUSER REPLICATION;"
   ```

## Environment Variable Reference

| Variable | Description |
| --- | --- |
| `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` | Connection parameters for Alfresco’s PostgreSQL instance. |
| `PGSUPERUSER` | PostgreSQL role with privileges to grant replication (defaults to `postgres`). |
| `BACKUP_DIR` | Root directory for storing backups (`postgres/`, `contentstore/`, `pg_wal/`). |
| `ALF_BASE_DIR` | Alfresco installation directory containing scripts and data. |
| `RETENTION_DAYS` | Number of days to retain backups before cleanup. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | SMTP credentials for failure notifications (optional). |
| `ALERT_EMAIL`, `ALERT_FROM` | Notification recipient and sender addresses. |

## Post-Installation Checklist

- Activate the virtual environment and run `python backup.py --help` to confirm dependencies.
- Verify the cron log directory (if scheduled) is writable by the Alfresco user.
- Confirm that WAL files appear in `BACKUP_DIR/pg_wal` after forcing a WAL switch (`SELECT pg_switch_xlog();` on PostgreSQL 9.4).
- Review `../operations/backup-guide.md` to schedule backups and monitor results.
