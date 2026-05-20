"""Tests for restic version compatibility."""

from alfresco_backup.v2.restic import (
    INSECURE_NO_PASSWORD_MIN_VERSION,
    supports_insecure_no_password_flag,
)


def test_insecure_flag_threshold():
    assert INSECURE_NO_PASSWORD_MIN_VERSION == (0, 17, 0)
    # Without mocking restic binary, just ensure function is callable.
    _ = supports_insecure_no_password_flag()
