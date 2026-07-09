"""Post-restore content integrity verification and repair."""

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .app_config import AppConfig
from .models import BackupPolicy
from .restore_planner import RestorePlanner, RestorableSet
from .restic import ResticRepository

logger = logging.getLogger(__name__)


@dataclass
class IntegrityReport:
    passed: bool
    missing_paths: List[str] = field(default_factory=list)
    repaired_paths: List[str] = field(default_factory=list)
    unresolved_paths: List[str] = field(default_factory=list)
    sources_searched: List[str] = field(default_factory=list)


def content_url_to_path(content_url: str, contentstore_root: Path) -> Optional[Path]:
    """
    Map standard Alfresco store URL to filesystem path.
    store://2024/01/15/10/30/uuid.bin -> contentstore/2024/01/15/10/30/uuid.bin
    """
    prefix = 'store://'
    if not content_url or not content_url.startswith(prefix):
        return None
    rel = content_url[len(prefix):]
    return contentstore_root / rel


def query_content_urls(config: AppConfig) -> List[str]:
    """Query alf_content_url from restored database."""
    env = {'PGPASSWORD': config.pgpassword, 'PATH': os.environ.get('PATH', '')}
    sql = "SELECT content_url FROM alf_content_url WHERE content_url IS NOT NULL;"
    cmd = [
        'psql',
        '-h', config.pghost,
        '-p', config.pgport,
        '-U', config.pguser,
        '-d', config.pgdatabase,
        '-t', '-A',
        '-c', sql,
    ]
    embedded_psql = config.restore_alf_base_dir / 'postgresql' / 'bin' / 'psql'
    if embedded_psql.exists():
        cmd[0] = str(embedded_psql)

    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"psql query failed: {proc.stderr}")
    urls = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return urls


class IntegrityRepairer:
    def __init__(self, config: AppConfig, staged_contentstore: Path):
        self.config = config
        self.staged_contentstore = staged_contentstore
        self.planner = RestorePlanner(config)

    def verify(self) -> Tuple[bool, List[str]]:
        missing = []
        for url in query_content_urls(self.config):
            path = content_url_to_path(url, self.staged_contentstore)
            if path and not path.exists():
                missing.append(str(path))
        return len(missing) == 0, missing

    def repair(
        self,
        run_id: str,
        missing_paths: List[str],
    ) -> IntegrityReport:
        report = IntegrityReport(passed=False, missing_paths=list(missing_paths))

        rel_paths = [
            str(Path(p).relative_to(self.staged_contentstore))
            for p in missing_paths
            if Path(p).is_absolute()
        ]
        if not rel_paths:
            rel_paths = [str(Path(p)) for p in missing_paths]

        repaired: Set[str] = set()

        for source in self._repair_sources(run_id):
            report.sources_searched.append(
                f"{source.policy_name}:{source.snapshot_id}"
            )
            if self._restore_paths_from_snapshot(source, rel_paths, repaired):
                report.repaired_paths.extend(sorted(repaired))

        still_missing = []
        for rp in rel_paths:
            full = self.staged_contentstore / rp
            if not full.exists():
                still_missing.append(str(full))

        report.unresolved_paths = still_missing
        report.passed = len(still_missing) == 0
        return report

    def _repair_sources(self, run_id: str) -> List[RestorableSet]:
        sources = []
        same_run = self.planner.fallback_sources(run_id)
        sources.extend(same_run)

        all_sets = self.planner.list_complete_sets()
        other_runs = sorted(
            ((rid, sets[0]) for rid, sets in all_sets.items() if rid != run_id),
            key=lambda x: x[1].time,
            reverse=True,
        )
        for _rid, primary in other_runs:
            for s in self.planner.fallback_sources(_rid):
                if s not in sources:
                    sources.append(s)
        return sources

    def _restore_paths_from_snapshot(
        self,
        source: RestorableSet,
        rel_paths: List[str],
        repaired: Set[str],
    ) -> bool:
        policy = self._policy_by_name(source.policy_name)
        if not policy:
            return False
        profile = (
            self.config.get_profile(policy.credential_profile)
            if policy.credential_profile
            else None
        )
        repo = ResticRepository(policy, self.config, profile)
        include = [f"*/alf_data/contentstore/{rp}" for rp in rel_paths if rp not in repaired]
        if not include:
            return False
        tmp = self.staged_contentstore.parent / f"repair-{source.policy_name}"
        tmp.mkdir(parents=True, exist_ok=True)
        r = repo.restore(source.snapshot_id, tmp, include_paths=include)
        if not r['success']:
            logger.warning(f"Partial restore failed from {source.policy_name}: {r.get('error')}")
            return False
        for rp in rel_paths:
            if rp in repaired:
                continue
            candidates = list(tmp.rglob(Path(rp).name))
            for c in candidates:
                if c.name == Path(rp).name:
                    dest = self.staged_contentstore / rp
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(c.read_bytes())
                    repaired.add(rp)
                    break
        return bool(repaired)

    def _policy_by_name(self, name: str) -> Optional[BackupPolicy]:
        for p in self.config.backup_policies:
            if p.name == name:
                return p
        return None
