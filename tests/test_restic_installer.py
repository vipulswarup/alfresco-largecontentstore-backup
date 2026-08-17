"""Tests for the standalone restic installer selection logic."""

from alfresco_backup import restic_installer


def test_linux_amd64_asset_is_pinned(monkeypatch):
    monkeypatch.setattr(restic_installer.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(restic_installer.platform, 'machine', lambda: 'x86_64')

    filename, checksum = restic_installer.linux_amd64_asset()

    assert filename == 'restic_0.19.1_linux_amd64.bz2'
    assert len(checksum) == 64


def test_linux_amd64_asset_rejects_unsupported_architecture(monkeypatch):
    monkeypatch.setattr(restic_installer.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(restic_installer.platform, 'machine', lambda: 'aarch64')

    assert restic_installer.linux_amd64_asset() is None
