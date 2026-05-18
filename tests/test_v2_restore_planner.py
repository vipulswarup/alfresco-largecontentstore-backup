"""Tests for restore planner fallback ordering."""

from alfresco_backup.v2.restore_planner import RestorableSet


def test_fallback_order_by_priority():
    sets = [
        RestorableSet('run-1', 'snap-b', 'low', 20, __import__('datetime').datetime.now()),
        RestorableSet('run-1', 'snap-a', 'high', 10, __import__('datetime').datetime.now()),
    ]
    sets.sort(key=lambda x: x.priority)
    assert sets[0].policy_name == 'high'
    assert sets[1].policy_name == 'low'
