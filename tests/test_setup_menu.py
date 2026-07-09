"""Tests for interactive setup destination flows."""

from pathlib import Path

from alfresco_backup.v2 import setup_menu
from alfresco_backup.v2.setup_wizard import _ensure_policy_passwords


def test_multiple_destinations_reuses_entered_policy_name(tmp_path, monkeypatch):
    policies_path = tmp_path / 'backup-policies.yml'
    env_path = tmp_path / '.env'
    env_path.write_text('')
    calls = []

    monkeypatch.setattr(setup_menu, '_init_repos', lambda *_args: None)

    def fake_add_filesystem(path, name=None):
        calls.append((path, name))

    monkeypatch.setattr(setup_menu, '_add_filesystem_destination', fake_add_filesystem)
    answers = iter(['bak-1week-new', '1', ''])
    monkeypatch.setattr('builtins.input', lambda _prompt='': next(answers))

    setup_menu.create_multiple_destinations_policy(policies_path, env_path)

    assert calls == [(policies_path, 'bak-1week-new')]


def test_policy_password_alias_is_added_for_compatible_env_name(tmp_path):
    env_path = tmp_path / '.env'
    policies_path = tmp_path / 'backup-policies.yml'
    env_path.write_text('RESTIC_PASSWORD_BAK_1WEEK=secret\n')
    policies_path.write_text("""
config_version: 1
global: {}
credential_profiles: []
backup_policies:
  - name: bak1week
    enabled: true
    destination_type: filesystem
    repository_path: /mnt/bak-1week
    encryption:
      enabled: true
      password_env: RESTIC_PASSWORD_BAK1WEEK
    backup_time: "02:00"
    retention_days: 7
    priority: 10
""")

    _ensure_policy_passwords(env_path, policies_path)

    content = env_path.read_text()
    assert 'RESTIC_PASSWORD_BAK_1WEEK=secret' in content
    assert 'RESTIC_PASSWORD_BAK1WEEK=secret' in content
