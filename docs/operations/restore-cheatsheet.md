# Restore Quick Reference

Use this cheatsheet for common restore scenarios. For context, prerequisites, and troubleshooting, see `restore-runbook.md`.

## Environment Setup

```bash
BACKUP_DIR=/mnt/backups/alfresco
ALF_BASE_DIR=/opt/eisenvault_installations/alfresco-home
ALFRESCO_USER=evadm
RESTORE_DATE=2025-10-21_14-31-23  # Replace with desired backup timestamp
```

## Full System Restore (PostgreSQL + Contentstore)

```bash
cd $ALF_BASE_DIR && ./alfresco.sh stop

# Use automated restore script (recommended)
cd /path/to/alfresco-largecontentstore-backup
source venv/bin/activate
python restore.py
# Select option 1 (Full system restore)

# Or restore manually:
gunzip -c $BACKUP_DIR/postgres/postgres-$RESTORE_DATE.sql.gz | \
  psql -h localhost -U alfresco -d postgres

sudo mkdir -p $ALF_BASE_DIR/alf_data/contentstore
sudo rsync -av --delete \
    $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/ \
    $ALF_BASE_DIR/alf_data/contentstore/
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/contentstore

cd $ALF_BASE_DIR && ./alfresco.sh start
```

## PostgreSQL Only

```bash
cd $ALF_BASE_DIR && ./alfresco.sh stop

# Use automated restore script (recommended)
cd /path/to/alfresco-largecontentstore-backup
source venv/bin/activate
python restore.py
# Select option 3 (PostgreSQL only)

# Or restore manually:
gunzip -c $BACKUP_DIR/postgres/postgres-$RESTORE_DATE.sql.gz | \
  psql -h localhost -U alfresco -d postgres

cd $ALF_BASE_DIR && ./alfresco.sh start
```

## Contentstore Only

```bash
cd $ALF_BASE_DIR && ./alfresco.sh stop
sudo mv $ALF_BASE_DIR/alf_data/contentstore{,.backup.$(date +%Y%m%d-%H%M%S)}

sudo mkdir -p $ALF_BASE_DIR/alf_data/contentstore
sudo rsync -av --delete \
    $BACKUP_DIR/contentstore/contentstore-$RESTORE_DATE/ \
    $ALF_BASE_DIR/alf_data/contentstore/
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/contentstore

cd $ALF_BASE_DIR && ./alfresco.sh start
```

## Point-in-Time Recovery (PITR)

**Not supported.** SQL dump backups provide snapshot recovery only. To restore to a specific time, select the backup closest to your desired recovery point and restore normally. See `restore-runbook.md` for details.

## Verification Snippets

```bash
# Database health
psql -h localhost -U alfresco -d alfresco -c "SELECT COUNT(*) FROM alf_node;"

# Contentstore file count
find $ALF_BASE_DIR/alf_data/contentstore -type f | wc -l

# Application logs
tail -100 $ALF_BASE_DIR/tomcat/logs/catalina.out | grep -i error
```

## Emergency Rollback

```bash
BACKUP_SUFFIX=$(ls -1dt $ALF_BASE_DIR/alf_data/postgresql/data.backup.* | head -1 | sed 's/.*backup\.//')

sudo rm -rf $ALF_BASE_DIR/alf_data/postgresql/data
sudo mv $ALF_BASE_DIR/alf_data/postgresql/data.backup.$BACKUP_SUFFIX \
        $ALF_BASE_DIR/alf_data/postgresql/data

sudo rm -rf $ALF_BASE_DIR/alf_data/contentstore
sudo mv $ALF_BASE_DIR/alf_data/contentstore.backup.$BACKUP_SUFFIX \
        $ALF_BASE_DIR/alf_data/contentstore

cd $ALF_BASE_DIR && ./alfresco.sh start
```

Refer to the runbook for additional verification steps, troubleshooting advice, and restore testing schedules.
