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

sudo mv $ALF_BASE_DIR/alf_data/postgresql/data{,.backup.$(date +%Y%m%d-%H%M%S)}
sudo mv $ALF_BASE_DIR/alf_data/contentstore{,.backup.$(date +%Y%m%d-%H%M%S)}

sudo mkdir -p $ALF_BASE_DIR/alf_data/postgresql/data
sudo tar -xzf $BACKUP_DIR/postgres/base-$RESTORE_DATE/base.tar.gz \
    -C $ALF_BASE_DIR/alf_data/postgresql/data
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/postgresql/data
sudo chmod 700 $ALF_BASE_DIR/alf_data/postgresql/data

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
sudo mv $ALF_BASE_DIR/alf_data/postgresql/data{,.backup.$(date +%Y%m%d-%H%M%S)}

sudo mkdir -p $ALF_BASE_DIR/alf_data/postgresql/data
sudo tar -xzf $BACKUP_DIR/postgres/base-$RESTORE_DATE/base.tar.gz \
    -C $ALF_BASE_DIR/alf_data/postgresql/data
sudo chown -R $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/postgresql/data
sudo chmod 700 $ALF_BASE_DIR/alf_data/postgresql/data

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

```bash
RECOVERY_TIME="2025-10-21 14:30:00"
cd $ALF_BASE_DIR && ./alfresco.sh stop

sudo mv $ALF_BASE_DIR/alf_data/postgresql/data{,.backup.$(date +%Y%m%d-%H%M%S)}

sudo mkdir -p $ALF_BASE_DIR/alf_data/postgresql/data
sudo tar -xzf $BACKUP_DIR/postgres/base-$RESTORE_DATE/base.tar.gz \
    -C $ALF_BASE_DIR/alf_data/postgresql/data

cat > /tmp/recovery.conf <<EOF
restore_command = 'cp $BACKUP_DIR/pg_wal/%f %p'
recovery_target_time = '$RECOVERY_TIME'
recovery_target_action = 'promote'
recovery_target_timeline = 'latest'
EOF

sudo mv /tmp/recovery.conf $ALF_BASE_DIR/alf_data/postgresql/data/recovery.conf
sudo chown $ALFRESCO_USER:$ALFRESCO_USER $ALF_BASE_DIR/alf_data/postgresql/data/recovery.conf
sudo chmod 600 $ALF_BASE_DIR/alf_data/postgresql/data/recovery.conf

cd $ALF_BASE_DIR && ./alfresco.sh start postgres
```

After PostgreSQL reaches the target state, restore the matching contentstore snapshot and start Alfresco (`./alfresco.sh start`).

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
