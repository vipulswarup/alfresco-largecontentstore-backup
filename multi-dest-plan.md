# Multi-Destination Alfresco Backup v2 Plan

## Summary

Replace the current single-destination model with a policy-driven multi-destination system that uses **`restic` as the single backup engine** for both `filesystem` and `object_storage` destinations. Keep PostgreSQL backups as one shared `pg_dump` per run, then store that dump together with the live contentstore in **one restic snapshot per destination per run**. Treat each destination as an **independent repository** with its own retention, schedule, maintenance, and credentials.

This is a **new backup path**, not an extension of the current S3/versioning branch. Legacy restore remains separate and untouched except for being clearly labeled as legacy.

## Key Changes

### 1. Configuration and setup

Implement a new config model with:
- `.env` for secrets and host-level settings
- `backup-policies.yml` for destinations, schedules, retention, priority, and maintenance

`setup.py` must become the only supported config editor and must:
- detect existing single-destination `.env`
- migrate it into one default backup policy on first run
- install missing dependencies on Ubuntu (`restic`, `rclone` only if still needed elsewhere, existing Python deps)
- create/edit/delete destinations
- create/edit credential profiles
- validate filesystem paths
- validate object storage repo connectivity
- validate restic repo initialization/access
- optionally enable repository encryption per destination

Use two policy backend types only:
- `filesystem`
- `object_storage`

Use separate credential profiles so multiple object-storage targets can coexist.

### 2. New policy and env interfaces

Use this YAML shape as the v1 contract:

```yaml
global:
  staging_dir: /var/tmp/alfresco-backup
  max_parallel_destinations: 2
  default_maintenance:
    enabled: true
    day_of_week: sunday
    time: "03:30"

credential_profiles:
  - name: do-spaces-prod
    type: object_storage
    provider: s3_compatible
    endpoint_url: https://blr1.digitaloceanspaces.com
    region: blr1
    bucket: eisenvault-backups
    access_key_env: OBJSTORE_DO_SPACES_PROD_ACCESS_KEY
    secret_key_env: OBJSTORE_DO_SPACES_PROD_SECRET_KEY

backup_policies:
  - name: nas-15-days
    enabled: true
    destination_type: filesystem
    repository_path: /mnt/nas/alfresco-restic
    encryption:
      enabled: false
      password_env: null
    backup_time: "02:00"
    retention_days: 15
    maintenance:
      enabled: true
      day_of_week: sunday
      time: "03:30"
    priority: 10

  - name: s3-180-days
    enabled: true
    destination_type: object_storage
    credential_profile: do-spaces-prod
    repository_prefix: customer-a/alfresco/restic
    encryption:
      enabled: true
      password_env: RESTIC_PASSWORD_S3_180
    backup_time: "02:30"
    retention_days: 180
    maintenance:
      enabled: true
      day_of_week: sunday
      time: "05:00"
    priority: 20
```

`.env` must hold:
- existing PostgreSQL and SMTP settings
- per-profile object storage secrets
- optional restic passwords
- no retention/policy values

### 3. Internal Python design

Add a new v2 subsystem with these concrete responsibilities:

- `AppConfig`
  - loads `.env` + `backup-policies.yml`
  - validates global settings, schedules, priorities, staging dir, and profile references

- `BackupPolicy`
  - resolved policy object with destination config, schedule, retention, maintenance, priority

- `CredentialProfile`
  - resolved secret-backed object-storage profile

- `RunContext`
  - one logical run
  - fields: `run_id`, `started_at`, `hostname`, `staging_dir`, shared `pg_dump` path, due policies

- `ResticRepository`
  - wraps all restic CLI interactions
  - init/check/snapshots/backup/restore/forget/prune/find-by-tag

- `DestinationBackupTask`
  - performs one destination backup from a shared `RunContext`

- `MaintenanceTask`
  - performs repo `forget --keep-within` equivalent and `prune` on its own schedule
  - must not run while that destination is actively backing up

- `RestorePlanner`
  - finds candidate backup sets by exact `run_id`
  - applies destination priority for fallback
  - assembles a complete restore source

- `IntegrityRepairer`
  - after restore, queries restored DB for referenced content URLs
  - maps URLs to standard Alfresco contentstore paths
  - checks file existence
  - repairs missing paths from fallback snapshots/destinations
  - blocks Alfresco startup until verification passes

### 4. Backup execution flow

Replace the current linear single-destination backup orchestration with:

1. Load config
2. Determine which destinations are due now based on local server time
3. Determine which maintenance tasks are due now
4. Acquire one global run lock
5. If no backup destinations are due:
   - optionally run due maintenance tasks
   - exit successfully
6. Create one `run_id`
7. Create shared staging workspace
8. Generate one PostgreSQL dump into staging
   - stream directly to `gzip`; do not write a full uncompressed temp file first
   - compute checksum and size
9. Launch due destination backups concurrently with `max_parallel_destinations`
10. For each destination:
    - ensure repo exists and is accessible
    - create a staged metadata directory containing:
      - `metadata/run.json`
      - `metadata/policy.json`
      - `postgres/postgres.sql.gz`
    - run one restic backup over:
      - staged metadata dir
      - staged postgres dir
      - live contentstore path
    - tag snapshot with:
      - `app:alfresco-backup`
      - `run:<run_id>`
      - `policy:<policy_name>`
      - `kind:complete-set`
    - record snapshot ID, duration, bytes processed, success/failure
11. Mark destination result `success` only if that destination wrote a complete snapshot containing both DB artifact and contentstore
12. Report overall run as:
    - `success` if all due destinations succeeded
    - `partial_success` if at least one succeeded and at least one failed
    - `failure` if all due destinations failed
13. Run due maintenance tasks only for destinations not currently backing up and not already failed due to lock/access issues
14. Send one consolidated email with per-destination status

### 5. Snapshot metadata contract

Every destination snapshot must contain `metadata/run.json` with:

```json
{
  "schema_version": 1,
  "run_id": "uuid-or-timestamp-id",
  "host_id": "hostname",
  "policy_name": "s3-180-days",
  "destination_type": "object_storage",
  "backup_started_at": "ISO-8601",
  "backup_finished_at": "ISO-8601",
  "pg_dump": {
    "filename": "postgres.sql.gz",
    "sha256": "hex",
    "size_bytes": 123,
    "started_at": "ISO-8601",
    "finished_at": "ISO-8601"
  },
  "contentstore": {
    "source_path": "/opt/alfresco/alf_data/contentstore",
    "started_at": "ISO-8601",
    "finished_at": "ISO-8601"
  }
}
```

This metadata is the source of truth for:
- restore listing
- completeness checks
- exact `run_id` matching
- fallback selection
- audit/reporting

### 6. Retention and maintenance

Do not implement custom object garbage collection.

Use restic-native retention and cleanup:
- age-based deletion only
- per destination: expire snapshots older than `retention_days`
- maintenance schedule separate from backup schedule
- default maintenance: weekly
- maintenance never blocks the backup result of a successful run

Use repository locking and surface lock contention clearly in reports.

### 7. Restore flow

Build a new restore workflow for v2 complete-set restores only.

Flow:
1. Show configured destinations ordered by `priority`
2. Discover restorable sets by reading snapshots tagged with `kind:complete-set`
3. Group by `run_id`
4. When user selects a target set:
   - require exact `run_id` match first
   - choose highest-priority destination containing a complete set
   - if missing/incomplete, try lower-priority destinations with the same `run_id`
5. Restore into staging paths, not in-place:
   - staged DB artifact
   - staged contentstore
6. Restore DB from staged `postgres.sql.gz`
7. Restore contentstore snapshot into staging
8. Run mandatory integrity verification before startup
9. If DB-referenced content is missing:
   - first search other destinations for same `run_id`
   - then nearest earlier snapshots by priority
   - then nearest later snapshots by priority
   - restore only missing content paths
   - re-run verification
10. Only after verification passes:
    - swap staged contentstore into place
    - set ownership
    - start Alfresco
11. If verification still fails:
    - abort startup
    - emit a report of unresolved missing paths and searched sources

Restore assumptions locked in:
- full restore only in v1
- staging restore is always available
- standard Alfresco content path mapping only
- no PostgreSQL WAL/PITR
- DB restores only to completed daily dump timestamp

### 8. Compatibility and migration

Keep legacy restore as a separate explicit path:
- `restore.py` menu must offer `Legacy restore` and `V2 multi-destination restore`
- do not mix legacy backup discovery with v2 snapshot discovery

Migration steps:
- detect current `.env`
- create `backup-policies.yml` with one migrated default policy
- preserve `.env` secrets
- mark migrated config version in YAML
- continue to support current backup path only until v2 is complete, then deprecate

## Interfaces and command behavior

Implement restic operations through a thin CLI wrapper. Required operations:
- `init`
- `snapshots --json`
- `backup`
- `restore`
- `find` or equivalent path lookup
- `forget --keep-within`
- `prune`
- `check` for validation/troubleshooting entrypoints

Per-destination repository mapping:
- `filesystem`: local restic repo at `repository_path`
- `object_storage`: restic S3-compatible repo assembled from profile + prefix

Encryption behavior:
- `encryption.enabled: true` requires `password_env`
- `encryption.enabled: false` uses restic no-password mode and must show a strong warning in setup and docs
- this is allowed but treated as insecure-by-choice

## Test Plan

### Unit tests
- config parsing and validation for policy/profile references
- schedule due/not-due evaluation in local timezone
- migration from single-destination `.env` to default policy
- exact `run_id` grouping and fallback ordering
- integrity path mapping from standard Alfresco `content_url`
- missing-content repair selection order

### Integration tests
- one filesystem destination, successful end-to-end backup
- one object-storage destination against S3-compatible test target
- two due destinations with shared `pg_dump` and concurrent execution
- partial success: one destination succeeds, one fails
- maintenance due while backup also due on another destination
- restore exact `run_id` from primary destination
- restore fallback to lower-priority destination with same `run_id`
- restore with missing content repaired from adjacent snapshot
- setup auto-installs missing restic on Ubuntu
- setup validates bad credentials, bad path, bad repo password

### Acceptance scenarios
- `15-day NAS + 180-day object storage`
- `7-day local + 30-day NAS`
- restore complete set from selected destination
- restore complete set with automatic fallback
- email/report clearly shows per-destination backup and maintenance outcomes
- old legacy restore path remains available and isolated

## Assumptions and defaults

- Backup engine: **restic**
- One Alfresco host writes to each repository
- One shared `pg_dump` per run
- One restic snapshot per destination per run
- Each destination is an independent repository
- Destinations have fixed daily backup times in server local timezone
- Missed runs are skipped, not backfilled
- Maintenance is separate and defaults to weekly
- Full restore only in v1; no component-only restore modes
- Legacy restore remains separate
- Optional encryption is supported; default should be **enabled** for new destinations unless the operator explicitly disables it
- Overall run can be `success`, `partial_success`, or `failure`
- A destination backup set is valid only if both DB artifact and contentstore are present in the same snapshot
