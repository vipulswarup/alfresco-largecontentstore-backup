# Disk Space Management for Large Contentstores

## Understanding How rsync Backups Use Disk Space

### How It Works

The backup system uses `rsync` with `--link-dest` for space-efficient incremental backups:

1. **First Backup**: Creates a full copy of the contentstore (e.g., 4.9TB)
2. **Subsequent Backups**: 
   - Files that haven't changed are hardlinked to the previous backup (uses almost no space)
   - Files that changed or are new are copied (uses real disk space)
   - Files deleted from source are removed from new backup

**Example:**
- Source contentstore: 4.9TB
- First backup: 4.9TB on disk
- Second backup (if only 10GB changed): ~10GB additional disk space (most files hardlinked)
- Third backup (if 50GB changed): ~50GB additional disk space

### The Problem with Failed Backups

When a backup fails midway through:
- rsync has already written partial data (potentially hundreds of GB)
- These incomplete files remain on disk
- The `last` symlink doesn't point to this failed backup
- Retention policy doesn't clean it up (it's too recent)
- **Each failed attempt accumulates more partial data**

**Your situation:**
```
659G    contentstore-2025-11-04  (full backup, successful)
418G    contentstore-2025-11-05  (incremental, successful)
1.6T    contentstore-2025-11-06  (large changes, successful)
42G     contentstore-2025-11-06  (partial, failed?)
3.1T    contentstore-2025-11-06  (partial, FAILED - ran out of space)
---
5.7T    total (filled your 6TB disk)
```

## Immediate Actions Required

### 1. Clean Up Failed Backups

Use the new cleanup script:

```bash
cd /path/to/alfresco-largecontentstore-backup
python3 cleanup_backups.py /mnt/data6tb/backup
```

This will:
- Show all backups with sizes and ages
- Identify which backup is current (the `last` symlink target)
- Let you remove old/failed backups interactively

Or manually:

```bash
cd /mnt/data6tb/backup/contentstore

# Check which backup is current
ls -lah last
# Output: last -> contentstore-2025-11-06_02-06-09

# Remove failed/partial backups (NOT the one symlinked by 'last')
rm -rf contentstore-2025-11-06_10-54-21  # 42G partial
rm -rf contentstore-2025-11-06_11-13-30  # 3.1T partial (FAILED)

# Remove older successful backups to free more space
rm -rf contentstore-2025-11-04_17-20-57  # 659G
rm -rf contentstore-2025-11-05_02-06-09  # 418G

# Keep only: contentstore-2025-11-06_02-06-09 (1.6T)
```

### 2. Adjust Retention Policy

For a 4.9TB contentstore on a 6TB disk, you can realistically keep only 1 backup:

Update `.env`:
```bash
RETENTION_DAYS=1  # Keep only yesterday's backup
```

### 3. Check Disk Space

```bash
df -h /mnt/data6tb
du -hd 1 /mnt/data6tb/backup/contentstore
```

## Long-term Solutions

### A. Automatic Cleanup (Now Implemented)

The backup system now automatically:
1. Detects failed backups before starting a new one
2. Removes recent failed attempts (< 12 hours old) that aren't the current `last` backup
3. Checks disk space and warns if insufficient

### B. Disk Space Recommendations

For a contentstore of size `S`, your backup disk should be:

**Minimum:** `S × 1.5` (keeps 1 full backup + some room for changes)
- Your case: 4.9TB × 1.5 = **7.4TB minimum**

**Recommended:** `S × 2.5` (keeps 2-3 full backups comfortably)
- Your case: 4.9TB × 2.5 = **12TB recommended**

**Your current setup:**
- Source: 4.9TB
- Backup disk: 6TB
- **Problem:** Only 1.1TB buffer (22% overhead)

### C. Options Moving Forward

**Option 1: Get a Larger Backup Disk**
- Recommended: 10-12TB disk
- Allows keeping 2-3 days of backups safely

**Option 2: Keep Only 1 Backup (Current Setup)**
- Set `RETENTION_DAYS=1`
- Risk: If backup fails, you lose your safety net
- Requires manual monitoring

**Option 3: Incremental Changes Only**
- Modify retention to keep 1 full backup + several recent incrementals
- More complex but more space-efficient

**Option 4: Offsite Backup**
- Primary backup: 1 day retention on 6TB disk
- Secondary backup: Sync to larger remote storage daily
- Best of both worlds but requires additional infrastructure

### D. Increase Backup Timeout

For large contentstores, increase the timeout in `.env`:

```bash
CONTENTSTORE_TIMEOUT_HOURS=48  # or 72 for very large contentstores
```

## Monitoring

### Check Backup Status

```bash
# View recent backup logs
tail -n 100 /var/log/alfresco-backup/cron-$(date +%Y-%m-%d).log

# Check disk space
df -h /mnt/data6tb

# Check backup sizes
du -hd 1 /mnt/data6tb/backup/contentstore

# Check which backup is current
ls -lah /mnt/data6tb/backup/contentstore/last
```

### Set Up Disk Space Alerts

Add a monitoring script to cron:

```bash
#!/bin/bash
# Check if backup disk is > 90% full
usage=$(df /mnt/data6tb | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$usage" -gt 90 ]; then
    echo "WARNING: Backup disk is ${usage}% full" | mail -s "Backup Disk Space Alert" ops@example.com
fi
```

## Troubleshooting

### Backup Keeps Failing with "No Space Left"

1. Check disk space: `df -h /mnt/data6tb`
2. List backup sizes: `du -hd 1 /mnt/data6tb/backup/contentstore`
3. Remove old backups manually or use `cleanup_backups.py`
4. Reduce `RETENTION_DAYS` in `.env`

### How to Verify Hardlinks Are Working

```bash
# Check inode counts - if hardlinks are working, inode count should be similar
# between backups but disk usage should be much lower for second backup

cd /mnt/data6tb/backup/contentstore

# Actual disk usage (du)
du -sh contentstore-2025-11-06_02-06-09
# Output: 1.6T

# File sizes if no hardlinks (sum of all file sizes)
du -sh --apparent-size contentstore-2025-11-06_02-06-09
# Output: 4.9T (source size) if it's the first full backup

# Check number of hardlinks for a file
ls -lah contentstore-2025-11-06_02-06-09/2023/1/1/0/0/*.bin | head -5
# The number after permissions is the link count (should be >1 if hardlinked)
```

### Force Cleanup of All Backups

**WARNING: This deletes all backups!**

```bash
cd /mnt/data6tb/backup/contentstore
rm -rf contentstore-*
rm -f last

# Next backup will be a full backup
```

## Best Practices

1. **Monitor disk space daily** - Don't wait for backups to fail
2. **Keep retention policy realistic** - Match it to available disk space
3. **Test restore periodically** - Ensure backups are actually usable
4. **Have a secondary backup** - Don't rely on a single 6TB disk for 4.9TB data
5. **Clean up failed backups promptly** - Use `cleanup_backups.py` after failures
6. **Increase timeout for large contentstores** - Set `CONTENTSTORE_TIMEOUT_HOURS` appropriately

