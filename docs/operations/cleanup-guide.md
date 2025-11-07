# Backup Cleanup Tool - Usage Guide

## Overview

The `cleanup_backups.py` script provides an interactive way to remove old or failed backup attempts with **multithreaded parallel deletion** for faster cleanup of large backups.

## Features

- **Multithreaded Deletion**: Uses 5 threads by default for 3-5× faster cleanup
- **Progress Tracking**: Shows real-time progress with ETA
- **Safe Operation**: Prevents deletion of current backup (symlinked by `last`)
- **Interactive Mode**: Choose what to delete
- **Error Handling**: Continues even if some chunks fail to delete

## Usage

### Basic Usage

```bash
cd /path/to/alfresco-largecontentstore-backup
python3 cleanup_backups.py /mnt/data6tb/backup
```

### Workflow

1. **Analysis Phase**: Script scans all backups and calculates sizes
2. **Summary Display**: Shows all backups with status, age, and size
3. **Choose Action**:
   - Option 1: Remove all old/failed backups (keep only CURRENT)
   - Option 2: Select specific backups to remove
   - Option 3: Exit without changes
4. **Deletion Method**: Choose parallel (fast) or serial (slower) deletion
5. **Thread Count**: For parallel, choose number of threads (default 5)
6. **Confirmation**: Type "yes" to confirm deletion

### Example Session

```
================================================================================
Alfresco Backup Cleanup Tool
================================================================================

Analyzing backups in: /mnt/data6tb/backup

Current successful backup (symlinked by 'last'): contentstore-2025-11-06_02-06-09

Calculating size of contentstore-2025-11-04_17-20-57...
Calculating size of contentstore-2025-11-05_02-06-09...
Calculating size of contentstore-2025-11-06_02-06-09...
Calculating size of contentstore-2025-11-06_10-54-21...
Calculating size of contentstore-2025-11-06_11-13-30...

================================================================================
BACKUP SUMMARY
================================================================================

1. contentstore-2025-11-04_17-20-57
   Status: old/failed
   Age: 2.5 days
   Size: 659.0 GB

2. contentstore-2025-11-05_02-06-09
   Status: old/failed
   Age: 1.4 days
   Size: 418.0 GB

3. contentstore-2025-11-06_02-06-09
   Status: CURRENT
   Age: 0.5 days
   Size: 1600.0 GB

4. contentstore-2025-11-06_10-54-21
   Status: old/failed
   Age: 0.2 days
   Size: 42.0 GB

5. contentstore-2025-11-06_11-13-30
   Status: old/failed
   Age: 0.1 days
   Size: 3100.0 GB

Total disk usage: 5819.0 GB
Available disk space: 748.0 GB
Total disk capacity: 6000.0 GB

================================================================================
CLEANUP OPTIONS
================================================================================

1. Remove all old/failed backups (keep only CURRENT)
2. Remove specific backups (interactive)
3. Exit without changes

Enter your choice (1-3): 1

Use parallel deletion for faster cleanup? (Y/n): y
Number of threads (default 5, recommended 3-8): 5

This will remove 4 backup(s):
  - contentstore-2025-11-04_17-20-57 (659.0 GB)
  - contentstore-2025-11-05_02-06-09 (418.0 GB)
  - contentstore-2025-11-06_10-54-21 (42.0 GB)
  - contentstore-2025-11-06_11-13-30 (3100.0 GB)

Total space to free: 4219.0 GB

Are you sure? This cannot be undone! (yes/no): yes

[1/4] Removing contentstore-2025-11-04_17-20-57 (659.0 GB)...

  Analyzing directory structure for parallel deletion...
  Found 147 chunks to process with 5 threads
  Starting parallel deletion...
Progress: 147/147 (100.0%) | Failed: 0 | Elapsed: 2m 15s | ETA: 0m 0s
  ✓ Removed successfully

[2/4] Removing contentstore-2025-11-05_02-06-09 (418.0 GB)...
  ...

================================================================================
Cleanup complete! Removed 4/4 backups in 8m 43s
================================================================================
```

## How Multithreaded Deletion Works

### Chunk-Based Parallelization

1. **Pre-scan**: Script walks directory tree to depth 2-3 (month/day level)
2. **Chunking**: Collects subdirectories as "chunks" for parallel processing
3. **Distribution**: 5 threads pull chunks from queue and delete them
4. **Progress**: Real-time updates showing completion percentage and ETA

### Example for Contentstore Structure

```
contentstore-2025-11-06/
  ├── 2023/
  │   ├── 01/ → Thread 1
  │   ├── 02/ → Thread 2
  │   ├── 03/ → Thread 3
  │   ├── 04/ → Thread 4
  │   └── 05/ → Thread 5
  ├── 2024/
  │   ├── 01/ → Thread 1 (reused)
  │   ├── 02/ → Thread 2 (reused)
  │   └── ...
```

### Adaptive Depth Selection

- **Few top-level dirs**: Uses depth 1 (year level)
- **Many months**: Uses depth 2 (month level)
- **Massive backup**: Uses depth 3 (day level)
- **Always ensures**: Enough chunks (10-20×) for good thread utilization

## Performance

### Expected Speedup

- **Single-threaded**: ~1-3 hours for 3TB
- **5 threads**: ~15-40 minutes (3-5× faster)
- **8 threads**: ~12-30 minutes (4-6× faster on fast disks)

### Optimal Thread Count

- **HDD**: 3-5 threads (more won't help due to seek times)
- **SSD**: 5-8 threads (can handle more parallel I/O)
- **NFS/Network**: 3-5 threads (network latency is bottleneck)
- **RAID**: 5-8 threads (benefits from parallel I/O)

## Options

### Serial Deletion (Slower but Simpler)

When prompted "Use parallel deletion for faster cleanup?", answer `n`:

```
Use parallel deletion for faster cleanup? (Y/n): n
```

This uses simple `shutil.rmtree()` without threads. Slower but:
- Lower memory usage
- Simpler error messages
- Better for very slow disks

### Custom Thread Count

```
Number of threads (default 5, recommended 3-8): 8
```

Valid range: 1-16 threads

**Don't go too high**: More threads don't always help. Diminishing returns after 8 threads on most systems.

## Safety Features

1. **Current Backup Protection**: Cannot delete the backup pointed to by `last` symlink
2. **Confirmation Required**: Must type "yes" to proceed
3. **Error Isolation**: If one chunk fails, others continue
4. **Progress Tracking**: See what's happening in real-time
5. **Summary Report**: Shows what was deleted and any errors

## Troubleshooting

### "Insufficient chunks for parallelization"

This means the backup has very few subdirectories. Script automatically falls back to single-threaded deletion. This is normal for:
- Very small backups
- Backups with flat directory structure
- First backup of a new contentstore

### Partial Failures

If some chunks fail to delete:

```
  ✗ Failed with errors:
    - /path/to/chunk1: Permission denied
    - /path/to/chunk2: Device or resource busy
```

**Solutions**:
- Check file permissions
- Ensure no processes are accessing the files
- Run with `sudo` if needed
- Try serial deletion (might handle some edge cases better)

### Script Hangs or Seems Stuck

The script might appear stuck during:
1. **Size calculation** (walking millions of files) - be patient
2. **Chunk collection** (walking directory tree) - usually < 1 minute
3. **Large chunk deletion** (one thread deleting huge directory) - check progress bar

**Progress bar shows**: Individual chunk completion, not file-level progress

### Out of Memory

If script crashes with memory error:
- Reduce thread count to 3
- Use serial deletion instead
- Close other programs

## Best Practices

1. **Run during off-hours**: Deletion is I/O-intensive
2. **Check disk space first**: `df -h`
3. **Don't interrupt**: If you must, Ctrl+C cleanly exits
4. **Verify after**: Check `du -hd 1 /backup/contentstore`
5. **Test restore**: After cleanup, verify you can still restore from remaining backup

## Integration with Automatic Cleanup

The main backup system now automatically cleans up recent failed attempts (< 12 hours old).

Use this manual tool for:
- Cleaning up very old backups
- Recovering from disk space emergencies
- Selective removal of specific backups
- When automatic cleanup isn't aggressive enough

