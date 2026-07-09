"""Tests for user-facing restore workflow helpers."""

from pathlib import Path

from alfresco_backup.restore.restore_ux import (
    PreflightCheck,
    clear_restore_session,
    confirm_destructive_restore,
    install_output_tee,
    preflight_failed,
    save_restore_session,
    load_restore_session,
    target_confirmation_token,
)


def test_target_confirmation_token_uses_restore_folder_name():
    assert target_confirmation_token(Path('/opt/eisenvault/customer-a')) == 'RESTORE customer-a'


def test_confirm_destructive_restore_requires_target_name(tmp_path, monkeypatch):
    monkeypatch.setattr('builtins.input', lambda _: f'RESTORE {tmp_path.name}')
    assert confirm_destructive_restore(tmp_path) is True


def test_preflight_failed_only_counts_required_failures():
    checks = [
        PreflightCheck('warning', False, 'missing', required=False),
        PreflightCheck('required', True, 'ok', required=True),
    ]
    assert preflight_failed(checks) is False

    checks.append(PreflightCheck('required fail', False, 'missing', required=True))
    assert preflight_failed(checks) is True


def test_restore_session_roundtrip(tmp_path):
    session_path = tmp_path / '.restore-session.json'
    data = {
        'workflow': 'v2-complete-restore',
        'run_id': 'run-1',
        'last_completed_step': 'snapshot_staged',
    }
    save_restore_session(data, session_path)
    assert load_restore_session(session_path) == data
    clear_restore_session(session_path)
    assert load_restore_session(session_path) is None


def test_install_output_tee_appends_stdout(tmp_path, monkeypatch):
    import sys
    import io

    log_file = tmp_path / 'restore.log'
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    fake_stdout = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', fake_stdout)
    handle = install_output_tee(log_file)
    try:
        print('visible in both places')
        sys.stdout.flush()
    finally:
        handle.close()
        monkeypatch.setattr(sys, 'stdout', original_stdout)
        monkeypatch.setattr(sys, 'stderr', original_stderr)

    assert 'visible in both places' in fake_stdout.getvalue()
    assert 'visible in both places' in log_file.read_text(encoding='utf-8')
