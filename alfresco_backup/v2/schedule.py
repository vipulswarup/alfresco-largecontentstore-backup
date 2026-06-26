"""Schedule evaluation for backup and maintenance windows."""

from datetime import datetime, time
from typing import Tuple

VALID_DAYS = {
    'monday', 'tuesday', 'wednesday', 'thursday',
    'friday', 'saturday', 'sunday',
}

DAY_TO_CRON_WEEKDAY = {
    'sunday': '0',
    'monday': '1',
    'tuesday': '2',
    'wednesday': '3',
    'thursday': '4',
    'friday': '5',
    'saturday': '6',
}


def parse_hhmm(value: str) -> time:
    parts = value.strip().split(':')
    if len(parts) != 2:
        raise ValueError(f"Invalid time format (expected HH:MM): {value}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time: {value}")
    return time(hour, minute)


def _within_minute_window(now: datetime, scheduled: time, window_minutes: int = 1) -> bool:
    scheduled_dt = now.replace(
        hour=scheduled.hour, minute=scheduled.minute, second=0, microsecond=0
    )
    delta = abs((now - scheduled_dt).total_seconds())
    return delta <= window_minutes * 60


def is_backup_due(backup_time: str, now: datetime) -> bool:
    """True if local time matches the policy's daily backup_time (1-minute window)."""
    return _within_minute_window(now, parse_hhmm(backup_time))


def is_maintenance_due(
    maintenance_enabled: bool,
    day_of_week: str,
    maintenance_time: str,
    now: datetime,
) -> bool:
    if not maintenance_enabled:
        return False
    day = day_of_week.strip().lower()
    if day not in VALID_DAYS:
        raise ValueError(f"Invalid day_of_week: {day_of_week}")
    if now.strftime('%A').lower() != day:
        return False
    return _within_minute_window(now, parse_hhmm(maintenance_time))


def maintenance_cron_expression(day_of_week: str, maintenance_time: str) -> str:
    """Cron schedule (minute hour dom month dow) for weekly maintenance."""
    day = day_of_week.strip().lower()
    if day not in VALID_DAYS:
        raise ValueError(f"Invalid day_of_week: {day_of_week}")
    scheduled = parse_hhmm(maintenance_time)
    return f"{scheduled.minute} {scheduled.hour} * * {DAY_TO_CRON_WEEKDAY[day]}"


def validate_schedule_fields(backup_time: str, maintenance: dict) -> None:
    parse_hhmm(backup_time)
    if maintenance.get('enabled', True):
        day = maintenance.get('day_of_week', 'sunday')
        if day.lower() not in VALID_DAYS:
            raise ValueError(f"Invalid maintenance day_of_week: {day}")
        parse_hhmm(maintenance.get('time', '03:30'))
