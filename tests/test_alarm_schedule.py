import datetime
import unittest
from alarm_schedule import next_trigger_datetime


class AlarmScheduleTests(unittest.TestCase):
    def test_one_time_alarm_moves_to_tomorrow_after_time_passed(self):
        now = datetime.datetime(2026, 10, 19, 10, 0, 0)
        self.assertEqual(next_trigger_datetime({"hour": 9, "minute": 30}, now),
                         datetime.datetime(2026, 10, 20, 9, 30))

    def test_one_time_alarm_can_be_scheduled_for_today(self):
        now = datetime.datetime(2026, 10, 19, 8, 0, 0)
        self.assertEqual(next_trigger_datetime({"hour": 9, "minute": 30}, now),
                         datetime.datetime(2026, 10, 19, 9, 30))

    def test_weekday_index_is_monday_first(self):
        now = datetime.datetime(2026, 10, 19, 10, 0, 0)  # Monday
        alarm = {"hour": 9, "minute": 0,
                 "days": [False, True, False, False, False, False, False]}
        self.assertEqual(next_trigger_datetime(alarm, now),
                         datetime.datetime(2026, 10, 20, 9, 0))

    def test_short_legacy_days_list_is_normalized(self):
        now = datetime.datetime(2026, 10, 19, 8, 0, 0)
        self.assertEqual(next_trigger_datetime({"hour": 9, "minute": 0,
                         "days": [False, True]}, now),
                         datetime.datetime(2026, 10, 20, 9, 0))

    def test_invalid_hour_is_rejected(self):
        with self.assertRaises(ValueError):
            next_trigger_datetime({"hour": 25, "minute": 0},
                                  datetime.datetime(2026, 10, 19))


if __name__ == "__main__":
    unittest.main()
