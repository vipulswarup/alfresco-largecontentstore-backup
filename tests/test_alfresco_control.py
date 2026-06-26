"""Tests for Alfresco restore service control helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from alfresco_backup.restore.alfresco_control import (
    confirm_alf_base_dir,
    is_tomcat_running,
    stop_tomcat,
)


def test_confirm_alf_base_dir_keeps_default(tmp_path, monkeypatch):
    monkeypatch.setattr('builtins.input', lambda _: '')
    chosen = confirm_alf_base_dir(tmp_path)
    assert chosen == tmp_path


def test_confirm_alf_base_dir_accepts_override(tmp_path, monkeypatch):
    other = tmp_path / 'alfresco'
    other.mkdir()
    monkeypatch.setattr('builtins.input', lambda _: str(other))
    chosen = confirm_alf_base_dir(tmp_path)
    assert chosen == other


def test_is_tomcat_running_true():
    with patch('alfresco_backup.restore.alfresco_control.subprocess.run') as run:
        run.return_value = MagicMock(returncode=0, stdout='1234\n')
        assert is_tomcat_running() is True


def test_stop_tomcat_when_not_running(tmp_path):
    with patch('alfresco_backup.restore.alfresco_control.is_tomcat_running', return_value=False):
        assert stop_tomcat(tmp_path, 'alfresco') is True
