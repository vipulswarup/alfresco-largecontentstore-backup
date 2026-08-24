"""On-demand full vs incremental backup size report."""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .app_config import AppConfig
from .email_report import _format_size
from .restic import ResticRepository

SIZE_TAG_PROCESSED = 'bytes-processed:'
SIZE_TAG_ADDED = 'bytes-added:'
SIZE_TAG_SOLR = 'solr-bytes:'
KIND_COMPLETE = 'kind:complete-set'
KIND_SOLR = 'kind:solr-indexes'


def parse_size_tag(tags: List[str], prefix: str) -> Optional[int]:
    for tag in tags:
        if tag.startswith(prefix):
            try:
                return int(tag[len(prefix):])
            except ValueError:
                return None
    return None


def generate_size_report(config: AppConfig) -> str:
    lines = [
        "Backup size report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Full backup is the first snapshot retained for each destination.",
        "Incremental sizes are new data added on later backup dates.",
        "",
    ]
    policies = config.enabled_policies()
    if not policies:
        lines.append("No enabled backup destinations.")
        return "\n".join(lines)

    for policy in policies:
        profile = (
            config.get_profile(policy.credential_profile)
            if policy.credential_profile
            else None
        )
        repo = ResticRepository(policy, config, profile)
        lines.append("=" * 72)
        lines.append(f"Policy: {policy.name} ({policy.destination_type})")
        lines.append("=" * 72)

        listed = repo.snapshots_json()
        if not listed.get('success'):
            lines.append(f"  Error listing snapshots: {listed.get('error') or 'unknown error'}")
            lines.append("")
            continue

        snapshots = listed.get('snapshots') or []
        if not snapshots:
            lines.append("  No snapshots found.")
            lines.append("")
            continue

        lines.extend(_policy_summary_lines(repo, snapshots))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _policy_summary_lines(repo: ResticRepository, snapshots: List[Dict[str, Any]]) -> List[str]:
    records = []
    for snap in snapshots:
        tags = snap.get('tags') or []
        snap_id = snap.get('id') or snap.get('short_id') or ''
        processed, added, solr_bytes = _snapshot_sizes(repo, tags, snap_id)
        if processed is None and solr_bytes is not None and KIND_SOLR not in tags:
            processed = solr_bytes
        records.append({
            'when': _parse_snap_datetime(snap),
            'kind': 'solr' if KIND_SOLR in tags else 'contentstore',
            'processed': processed,
            'added': added,
        })

    contentstore = sorted(
        [r for r in records if r['kind'] == 'contentstore'],
        key=lambda r: r['when'],
    )
    solr = sorted(
        [r for r in records if r['kind'] == 'solr'],
        key=lambda r: r['when'],
    )

    full_date = None
    if contentstore:
        full_date = contentstore[0]['when']
    elif solr:
        full_date = solr[0]['when']

    lines = ["", "Last full backup"]
    lines.append(f"  Date: {_format_datetime(full_date) if full_date else 'n/a'}")
    if contentstore:
        lines.append(f"  Contentstore: {_full_size_text(contentstore[0])}")
    else:
        lines.append("  Contentstore: n/a")
    if solr:
        lines.append(f"  Solr indexes: {_full_size_text(solr[0])}")

    incrementals_by_date = defaultdict(lambda: {'contentstore': [], 'solr': []})
    for kind, items in (('contentstore', contentstore), ('solr', solr)):
        for item in items[1:]:
            incrementals_by_date[_format_date(item['when'])][kind].append(item['added'])

    lines.append("")
    lines.append("Incremental backups")
    if not incrementals_by_date:
        lines.append("  None yet.")
        return lines

    for day in sorted(incrementals_by_date.keys(), reverse=True):
        lines.append(f"  {day}")
        amounts = incrementals_by_date[day]
        for key, label in (('contentstore', 'Contentstore'), ('solr', 'Solr indexes')):
            values = amounts[key]
            if not values:
                continue
            total = None
            for value in values:
                total = _sum_optional(total, value)
            lines.append(f"    {label}: {_format_optional_size(total)}")
    return lines


def _full_size_text(record: Dict[str, Any]) -> str:
    size = record['processed']
    if size is None:
        size = record['added']
    return _format_optional_size(size)


def _sum_optional(left: Optional[int], right: Optional[int]) -> Optional[int]:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _snapshot_sizes(
    repo: ResticRepository,
    tags: List[str],
    snapshot_id: str,
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    processed = parse_size_tag(tags, SIZE_TAG_PROCESSED)
    added = parse_size_tag(tags, SIZE_TAG_ADDED)
    solr_bytes = parse_size_tag(tags, SIZE_TAG_SOLR)
    if processed is None and snapshot_id:
        stats = repo.stats_json(snapshot_id)
        if stats.get('success'):
            processed = int((stats.get('stats') or {}).get('total_size', 0) or 0)
    return processed, added, solr_bytes


def _format_optional_size(size_bytes: Optional[int]) -> str:
    if size_bytes is None:
        return 'n/a'
    return _format_size(size_bytes)


def _parse_snap_datetime(snap: Dict[str, Any]) -> datetime:
    raw = snap.get('time')
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            pass
    return datetime.now()


def _format_datetime(value: datetime) -> str:
    return value.strftime('%Y-%m-%d %H:%M:%S')


def _format_date(value: datetime) -> str:
    return value.strftime('%Y-%m-%d')
