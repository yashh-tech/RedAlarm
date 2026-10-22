"""Pure-Python wall-clock alarm scheduling helpers (no Kivy or Android imports)."""
import datetime


def next_trigger_datetime(alarm, now=None):
    """Return the next local-wall-clock occurrence strictly after now.

    days is a Monday-first seven-boolean list. Missing or short legacy lists
    are normalized rather than raising and preventing other alarms from arming.
    """
    now = now or datetime.datetime.now()
    hour = int(alarm.get("hour", 7))
    minute = int(alarm.get("minute", 0))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Alarm hour/minute is outside the valid range")
    raw_days = alarm.get("days") or []
    days = [bool(raw_days[i]) if i < len(raw_days) else False for i in range(7)]
    if not any(days):
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += datetime.timedelta(days=1)
        return candidate
    for add in range(0, 8):
        day = now + datetime.timedelta(days=add)
        if days[day.weekday()]:
            candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > now:
                return candidate
    return now + datetime.timedelta(days=7)
