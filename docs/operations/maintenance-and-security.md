# Maintenance & Security Guide

This guide summarises day-two operations: ongoing maintenance tasks, recommended monitoring, and security considerations for the Alfresco Backup System.

## Current Configuration Snapshot

- **Backup schedule:** Daily at 02:00 (cron recommended)
- **Retention:** `RETENTION_DAYS` (default 7) applied to PostgreSQL SQL dumps and contentstore snapshots
- **Storage layout:**
  - `BACKUP_DIR/postgres/postgres-YYYY-MM-DD_HH-MM-SS.sql.gz`
  - `BACKUP_DIR/contentstore/contentstore-YYYY-MM-DD_HH-MM-SS/`
- **Logs:**
  - `BACKUP_DIR/backup-YYYY-MM-DD.log`
  - `/var/log/alfresco-backup/cron-YYYY-MM-DD.log`
- **Alerts:** SMTP credentials in `.env` trigger failure-only notifications

## Routine Maintenance

| Cadence | Task |
| --- | --- |
| Daily | Review cron logs, confirm new PostgreSQL SQL dump and contentstore directories were created, check disk usage (`df -h`). |
| Weekly | Inspect backup logs for warnings, validate email alerts, verify backup file sizes are reasonable. |
| Monthly | Perform a manual backup run, test restore steps on non-production (partial or full), rotate SMTP credentials if policy requires. |
| Quarterly | Conduct a full disaster-recovery drill, update this documentation with lessons learned, verify cron ownership, confirm retention policy matches requirements. |
| Annually | Reassess retention periods and off-site replication strategy, review backup volume sizing, update contact lists and escalation paths. |

## Monitoring & Metrics

- **Success rate:** >99% of scheduled backups complete without error.
- **Backup duration:** Track PostgreSQL SQL dump and contentstore durations from the log file; investigate significant increases.
- **Disk utilisation:** Keep backup volume below 80% capacity. Monitor SQL dump file sizes for anomalies.
- **Email delivery:** Send a synthetic failure alert quarterly to confirm SMTP configuration.
- **Restore readiness:** Document successful restore drills, target recovery time (RTO < 2 hours) and recovery point (RPO < 24 hours, determined by backup frequency).

## Security Checklist

- `.env` permissions set to `600`; never commit secrets to version control.
- Backup directories owned by the Alfresco service account; restrict access to trusted users (`chmod 750` or tighter as policy dictates).
- SMTP credentials stored securely and rotated periodically.
- Regular OS patching (`sudo apt-get update && sudo apt-get upgrade`) on the backup host.
- Consider encrypting off-site copies if backups are replicated externally.
- SQL dump files contain sensitive data; ensure proper access controls on backup storage.

## Off-Site Replication (Optional)

- Use `rsync`, `rclone`, or object storage (e.g., S3) with server-side encryption.
- Schedule replication after the daily backup completes to avoid contention.
- Track replication success separately from local backup success.

## Post-Deployment Verification

After deploying changes or updates to Alfresco or this backup toolchain:

1. Run a manual backup and inspect the log for warnings.
2. Verify SQL dump files are created successfully and have reasonable sizes.
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
