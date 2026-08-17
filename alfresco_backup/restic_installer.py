"""Install the supported restic release when a distro package is unavailable."""

import bz2
import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from urllib.request import Request, urlopen


# Pinning a known release makes setup reproducible. The official release binary is
# statically built and therefore works on older supported Linux distributions too.
RESTIC_VERSION = '0.19.1'
RESTIC_LINUX_AMD64_SHA256 = (
    'f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c'
)
RESTIC_INSTALL_PATH = Path('/usr/local/bin/restic')


def linux_amd64_asset() -> Optional[Tuple[str, str]]:
    """Return the pinned asset for 64-bit Intel/AMD Linux, if applicable."""
    if platform.system() != 'Linux':
        return None
    if platform.machine().lower() not in ('amd64', 'x86_64'):
        return None
    filename = 'restic_{}_linux_amd64.bz2'.format(RESTIC_VERSION)
    return filename, RESTIC_LINUX_AMD64_SHA256


def _download(url: str, destination: Path) -> None:
    request = Request(url, headers={'User-Agent': 'alfresco-backup-setup'})
    with urlopen(request, timeout=60) as response, destination.open('wb') as output:
        shutil.copyfileobj(response, output)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def install_restic_release(use_sudo: bool) -> Tuple[bool, str]:
    """Download, verify, and install restic's official Linux AMD64 binary."""
    asset = linux_amd64_asset()
    if asset is None:
        return False, (
            'Automatic restic installation supports Linux x86_64/amd64 only. '
            'Download the matching release from https://restic.net/ manually.'
        )

    filename, expected_sha256 = asset
    url = 'https://github.com/restic/restic/releases/download/v{}/{}'.format(
        RESTIC_VERSION, filename
    )
    try:
        with tempfile.TemporaryDirectory(prefix='alfresco-restic-') as temp_dir:
            archive = Path(temp_dir) / filename
            binary = Path(temp_dir) / 'restic'
            _download(url, archive)
            actual_sha256 = _sha256(archive)
            if actual_sha256 != expected_sha256:
                return False, (
                    'Downloaded restic checksum did not match the pinned official '
                    'release checksum; installation aborted.'
                )
            with bz2.open(str(archive), 'rb') as compressed, binary.open('wb') as output:
                shutil.copyfileobj(compressed, output)
            os.chmod(str(binary), 0o755)

            command = ['install', '-m', '0755', str(binary), str(RESTIC_INSTALL_PATH)]
            if use_sudo:
                command.insert(0, 'sudo')
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                return False, 'Could not install restic to {}: {}'.format(
                    RESTIC_INSTALL_PATH, detail or 'unknown error'
                )
    except Exception as exc:
        return False, 'Could not download the official restic release: {}'.format(exc)

    version = subprocess.run(
        [str(RESTIC_INSTALL_PATH), 'version'], capture_output=True, text=True, check=False
    )
    if version.returncode != 0:
        return False, 'restic was installed but could not be executed: {}'.format(
            version.stderr.strip() or version.stdout.strip() or 'unknown error'
        )
    return True, 'Installed restic {} to {}'.format(RESTIC_VERSION, RESTIC_INSTALL_PATH)
