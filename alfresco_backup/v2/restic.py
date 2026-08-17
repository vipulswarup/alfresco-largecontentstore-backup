"""Thin wrapper around restic CLI."""

import json
import logging
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .app_config import AppConfig
from .models import BackupPolicy, CredentialProfile

logger = logging.getLogger(__name__)

LOCK_PATTERN = re.compile(r'lock|locked|repository is already locked', re.I)
VERSION_PATTERN = re.compile(r'restic\s+(\d+)\.(\d+)\.(\d+)', re.I)
UNKNOWN_INSECURE_FLAG = re.compile(r'unknown flag: --insecure-no-password', re.I)

# --insecure-no-password exists from restic 0.17.0 (Ubuntu apt often ships older).
INSECURE_NO_PASSWORD_MIN_VERSION = (0, 17, 0)


@lru_cache(maxsize=1)
def get_restic_version() -> Optional[Tuple[int, int, int]]:
    try:
        proc = subprocess.run(
            ['restic', 'version'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        text = (proc.stdout or '') + (proc.stderr or '')
        match = VERSION_PATTERN.search(text)
        if match:
            return int(match.group(1)), int(match.group(2)), int(match.group(3))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def supports_insecure_no_password_flag() -> bool:
    version = get_restic_version()
    if version is None:
        return False
    return version >= INSECURE_NO_PASSWORD_MIN_VERSION


def passwordless_repositories_supported() -> bool:
    return supports_insecure_no_password_flag()


class ResticRepository:
    """Restic operations for one destination repository."""

    def __init__(
        self,
        policy: BackupPolicy,
        config: AppConfig,
        profile: Optional[CredentialProfile] = None,
    ):
        self.policy = policy
        self.config = config
        self.profile = profile
        self.repository = self._repository_url()
        self._env = self._build_env()

    def _repository_url(self) -> str:
        if self.policy.destination_type == 'filesystem':
            return str(Path(self.policy.repository_path).resolve())
        if not self.profile:
            raise ValueError(f"Policy {self.policy.name} requires credential profile")
        prefix = (self.policy.repository_prefix or '').strip('/')
        base = self.profile.endpoint_url.rstrip('/')
        bucket = self.profile.bucket
        if prefix:
            return f"s3:{base}/{bucket}/{prefix}"
        return f"s3:{base}/{bucket}"

    def _build_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env['RESTIC_REPOSITORY'] = self.repository
        if self.policy.encryption.enabled:
            password = self.policy.restic_password({k: os.getenv(k, '') for k in os.environ})
            if password:
                env['RESTIC_PASSWORD'] = password
        else:
            env.pop('RESTIC_PASSWORD', None)

        if self.profile:
            env['AWS_ACCESS_KEY_ID'] = self.profile.access_key(os.environ)
            env['AWS_SECRET_ACCESS_KEY'] = self.profile.secret_key(os.environ)
            env['AWS_DEFAULT_REGION'] = self.profile.region

        # Restic reads this many source files concurrently during one `backup`
        # process. It improves throughput for a single multi-terabyte destination
        # without splitting its data across snapshots or repositories.
        read_concurrency = self.config.global_config.restic_read_concurrency
        env['RESTIC_READ_CONCURRENCY'] = str(read_concurrency)
        return env

    def _base_cmd(self) -> List[str]:
        return ['restic', '-r', self.repository]

    def _extra_password_flags(self, args: List[str]) -> List[str]:
        """Flags for repositories without restic encryption/password."""
        if self.policy.encryption.enabled:
            return []
        if supports_insecure_no_password_flag():
            return ['--insecure-no-password']
        return []

    def _unsupported_passwordless_result(self) -> Dict[str, Any]:
        version = get_restic_version()
        version_text = (
            f"{version[0]}.{version[1]}.{version[2]}"
            if version
            else "unknown"
        )
        return {
            'success': False,
            'stdout': '',
            'stderr': '',
            'error': (
                "This policy has encryption disabled, but installed restic "
                f"{version_text} cannot use passwordless repositories. "
                "Enable repository encryption with RESTIC_PASSWORD_* or upgrade "
                "restic to 0.17+."
            ),
            'lock_contention': False,
        }

    def _run(self, args: List[str], timeout: Optional[int] = 86400) -> Dict[str, Any]:
        if not self.policy.encryption.enabled and not passwordless_repositories_supported():
            return self._unsupported_passwordless_result()

        cmd = self._base_cmd() + args + self._extra_password_flags(args)

        result = {
            'success': False,
            'stdout': '',
            'stderr': '',
            'error': None,
            'lock_contention': False,
        }
        try:
            proc = subprocess.run(
                cmd,
                env=self._env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            result['stdout'] = proc.stdout or ''
            result['stderr'] = proc.stderr or ''
            if proc.returncode == 0:
                result['success'] = True
            else:
                combined = (proc.stderr or '') + (proc.stdout or '')
                result['error'] = combined.strip() or f"restic exited {proc.returncode}"
                if LOCK_PATTERN.search(combined):
                    result['lock_contention'] = True
        except subprocess.TimeoutExpired:
            result['error'] = f"restic timed out after {timeout}s"
        except OverflowError as e:
            result['error'] = f"Invalid restic timeout value {timeout}: {e}"
        except FileNotFoundError:
            result['error'] = 'restic command not found'
        return result

    def init(self) -> Dict[str, Any]:
        return self._run(['init'], timeout=600)

    def check(self) -> Dict[str, Any]:
        return self._run(['check'], timeout=3600)

    def snapshots_json(self) -> Dict[str, Any]:
        r = self._run(['snapshots', '--json'], timeout=600)
        if not r['success']:
            return r
        try:
            r['snapshots'] = json.loads(r['stdout'])
        except json.JSONDecodeError as e:
            r['success'] = False
            r['error'] = f"Invalid snapshots JSON: {e}"
        return r

    def backup(
        self,
        paths: List[Path],
        tags: List[str],
    ) -> Dict[str, Any]:
        args = ['backup', '--json'] + [str(p) for p in paths]
        for tag in tags:
            args.extend(['--tag', tag])
        r = self._run(args, timeout=None)
        if r['success'] and r['stdout']:
            try:
                summary = json.loads(r['stdout'].strip().split('\n')[-1])
                r['summary'] = summary
                r['snapshot_id'] = summary.get('snapshot_id') or summary.get('id')
                r['bytes_processed'] = summary.get('total_bytes_processed', 0)
            except (json.JSONDecodeError, IndexError):
                pass
        return r

    def restore(
        self,
        snapshot_id: str,
        target_dir: Path,
        include_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        args = ['restore', snapshot_id, '--target', str(target_dir)]
        if include_paths:
            for p in include_paths:
                args.extend(['--include', p])
        return self._run(args, timeout=None)

    def forget_prune(self, retention_days: int) -> Dict[str, Any]:
        keep = f"{retention_days}d"
        return self._run(
            [
                'forget',
                '--keep-within', keep,
                '--tag', 'kind:complete-set',
                '--tag', f'policy:{self.policy.name}',
                '--group-by', 'host',
                '--prune',
            ],
            timeout=86400,
        )

    def find_snapshot_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        r = self.snapshots_json()
        if not r.get('success'):
            return []
        matches = []
        for snap in r.get('snapshots', []):
            if tag in snap.get('tags', []):
                matches.append(snap)
        return matches

    def find_by_run_id(self, run_id: str) -> List[Dict[str, Any]]:
        return self.find_snapshot_by_tag(f"run:{run_id}")

    @staticmethod
    def is_lock_error(result: Dict[str, Any]) -> bool:
        return bool(result.get('lock_contention'))
