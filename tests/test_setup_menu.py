"""Tests for interactive setup destination flows."""

from pathlib import Path

from alfresco_backup.v2 import setup_menu


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
