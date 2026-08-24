"""On-demand full vs incremental backup size report."""

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
        "Full size is the source scanned for that snapshot.",
        "Incremental is new data added to the repository in that run.",
        "Contentstore and Solr indexes are listed separately when both were backed up.",
        "Older snapshots without recorded incremental size show n/a.",
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
        snapshots = [
            snap for snap in snapshots
            if KIND_COMPLETE in (snap.get('tags') or [])
            or KIND_SOLR in (snap.get('tags') or [])
        ]
        if not snapshots:
            lines.append("  No snapshots found.")
            lines.append("")
            continue

        snapshots = sorted(snapshots, key=_snapshot_sort_key, reverse=True)
        for snap in snapshots:
            lines.extend(_snapshot_lines(repo, snap))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _snapshot_lines(repo: ResticRepository, snap: Dict[str, Any]) -> List[str]:
    tags = snap.get('tags') or []
    snap_id = snap.get('short_id') or snap.get('id') or ''
    full_id = snap.get('id') or snap_id
    processed, added, solr_bytes = _snapshot_sizes(repo, tags, full_id)
    run_id = _tag_value(tags, 'run:')

    lines = [
        f"  Snapshot: {snap_id}",
        f"  Time: {_format_snap_time(snap)}",
    ]
    if run_id:
        lines.append(f"  Run: {run_id}")
    if KIND_SOLR in tags:
        lines.append("  Component: Solr indexes")
    else:
        lines.append("  Component: Contentstore")
    lines.append(f"  Processed: {_format_optional_size(processed)}")
    lines.append(f"  Backed up this run: {_format_optional_size(added)}")
    if solr_bytes is not None and KIND_SOLR not in tags:
        lines.append(f"  Solr indexes (legacy): {_format_optional_size(solr_bytes)}")
    lines.append("")
    return lines


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


def _tag_value(tags: List[str], prefix: str) -> Optional[str]:
    for tag in tags:
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None


def _snapshot_sort_key(snap: Dict[str, Any]):
    return snap.get('time') or ''


def _format_snap_time(snap: Dict[str, Any]) -> str:
    raw = snap.get('time')
    if not isinstance(raw, str):
        return ''
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return parsed.strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return raw
