"""Discover and select restorable complete-set snapshots."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .app_config import AppConfig
from .models import BackupPolicy
from .restic import ResticRepository

logger = logging.getLogger(__name__)


@dataclass
class RestorableSet:
    run_id: str
    snapshot_id: str
    policy_name: str
    priority: int
    time: datetime
    hostname: str = ''


class RestorePlanner:
    def __init__(self, config: AppConfig):
        self.config = config

    def list_complete_sets(self) -> Dict[str, List[RestorableSet]]:
        """Group complete-set snapshots by run_id across all policies (priority order)."""
        by_run: Dict[str, List[RestorableSet]] = {}

        for policy in self.config.policies_by_priority():
            profile = (
                self.config.get_profile(policy.credential_profile)
                if policy.credential_profile
                else None
            )
            repo = ResticRepository(policy, self.config, profile)
            r = repo.snapshots_json()
            if not r.get('success'):
                logger.warning(f"Cannot list snapshots for {policy.name}: {r.get('error')}")
                continue

            for snap in r.get('snapshots', []):
                tags = snap.get('tags', [])
                if 'kind:complete-set' not in tags:
                    continue
                run_id = _tag_value(tags, 'run:')
                if not run_id:
                    continue
                entry = RestorableSet(
                    run_id=run_id,
                    snapshot_id=snap.get('id', snap.get('short_id', '')),
                    policy_name=policy.name,
                    priority=policy.priority,
                    time=_parse_snap_time(snap),
                    hostname=snap.get('hostname', ''),
                )
                by_run.setdefault(run_id, []).append(entry)

        for run_id in by_run:
            by_run[run_id].sort(key=lambda x: x.priority)
        return by_run

    def select_source(self, run_id: str) -> Optional[RestorableSet]:
        """Highest-priority destination with a complete set for exact run_id."""
        groups = self.list_complete_sets()
        candidates = groups.get(run_id, [])
        if candidates:
            return candidates[0]
        return None

    def fallback_sources(self, run_id: str) -> List[RestorableSet]:
        """All destinations for run_id, ordered by priority (for fallback)."""
        return self.list_complete_sets().get(run_id, [])


def _tag_value(tags: List[str], prefix: str) -> Optional[str]:
    for t in tags:
        if t.startswith(prefix):
            return t[len(prefix):]
    return None


def _parse_snap_time(snap: dict) -> datetime:
    t = snap.get('time')
    if isinstance(t, str):
        try:
            return datetime.fromisoformat(t.replace('Z', '+00:00'))
        except ValueError:
            pass
    return datetime.now()
