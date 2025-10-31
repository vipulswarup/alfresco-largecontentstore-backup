# Maintenance & Security Guide

This guide summarises day-two operations: ongoing maintenance tasks, recommended monitoring, and security considerations for the Alfresco Backup System.

## Current Configuration Snapshot

- **Backup schedule:** Daily at 02:00 (cron recommended)
- **Retention:** `RETENTION_DAYS` (default 30) applied to PostgreSQL, contentstore, and WAL archives
- **Storage layout:**
  - `BACKUP_DIR/postgres/base-YYYY-MM-DD_HH-MM-SS/`
  - `BACKUP_DIR/contentstore/contentstore-YYYY-MM-DD_HH-MM-SS/`
  - `BACKUP_DIR/pg_wal/`
- **Logs:**
  - `BACKUP_DIR/backup-YYYY-MM-DD.log`
  - `/var/log/alfresco-backup/cron-YYYY-MM-DD.log`
- **Alerts:** SMTP credentials in `.env` trigger failure-only notifications

## Routine Maintenance

| Cadence | Task |
| --- | --- |
| Daily | Review cron logs, confirm new PostgreSQL/contentstore directories were created, check disk usage (`df -h`). |
| Weekly | Inspect backup logs for warnings, spot-check WAL archive growth, validate email alerts. |
| Monthly | Perform a manual backup run, test restore steps on non-production (partial or full), rotate SMTP credentials if policy requires. |
| Quarterly | Conduct a full disaster-recovery drill, update this documentation with lessons learned, verify cron ownership, confirm WAL archive retention matches policy. |
| Annually | Reassess retention periods and off-site replication strategy, review backup volume sizing, update contact lists and escalation paths. |

## Monitoring & Metrics

- **Success rate:** >99% of scheduled backups complete without error.
- **Backup duration:** Track PostgreSQL and contentstore durations from the log file; investigate significant increases.
- **Disk utilisation:** Keep backup volume below 80% capacity.
- **Email delivery:** Send a synthetic failure alert quarterly to confirm SMTP configuration.
- **Restore readiness:** Document successful restore drills, target recovery time (RTO < 2 hours) and recovery point (RPO < 24 hours).

## Security Checklist

- `.env` permissions set to `600`; never commit secrets to version control.
- Backup directories owned by the Alfresco service account; restrict access to trusted users (`chmod 750` or tighter as policy dictates).
- SMTP credentials stored securely and rotated periodically.
- WAL archive directory (`BACKUP_DIR/pg_wal`) writable only by PostgreSQL and the operational user.
- Regular OS patching (`sudo apt-get update && sudo apt-get upgrade`) on the backup host.
- Consider encrypting off-site copies if backups are replicated externally.

## Off-Site Replication (Optional)

- Use `rsync`, `rclone`, or object storage (e.g., S3) with server-side encryption.
- Schedule replication after the daily backup completes to avoid contention.
- Track replication success separately from local backup success.

## Post-Deployment Verification

After deploying changes or updates to Alfresco or this backup toolchain:

1. Run a manual backup and inspect the log for warnings.
2. Confirm WAL files continue to arrive in `BACKUP_DIR/pg_wal`.
3. Execute a short restore test (database-only or contentstore-only) in a non-production environment.
4. Update operational runbooks with any new steps or observations.

## Contact & Escalation Template

Maintain a current list alongside this guide:

```
Database Administrator: ___________________________
System Administrator: _____________________________
Alfresco Owner: __________________________________
Backup On-Call: __________________________________
```

Review and refresh this list whenever team memberships change.
