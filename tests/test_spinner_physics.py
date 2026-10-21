import unittest
from spinner_physics import VelocityTracker, advance_fling


class SpinnerPhysicsTests(unittest.TestCase):
    def test_tracker_detects_fast_swipe_and_caps_velocity(self):
        tracker = VelocityTracker(max_velocity=32.0)
        tracker.reset(0.0, 0.0)
        tracker.add(0.04, 1.5)
        velocity = tracker.add(0.08, 3.0)
        self.assertGreater(velocity, 10.0)
        self.assertLessEqual(abs(velocity), 32.0)

    def test_fling_coasts_multiple_rows_then_stops(self):
        position, velocity, stopped = 0.0, 28.0, False
        steps = 0
        while not stopped and steps < 500:
            position, velocity, stopped = advance_fling(position, velocity, 1 / 60)
            steps += 1
        self.assertTrue(stopped)
        self.assertGreater(position, 5.0)
        self.assertLess(position, 12.0)
        self.assertLess(abs(velocity), 0.22)

    def test_ui_stall_is_clamped_to_one_small_step(self):
        new_position, _, _ = advance_fling(4.0, 30.0, 1.5)
        self.assertLessEqual(new_position, 5.21)

    def test_reverse_swipe_preserves_negative_velocity(self):
        tracker = VelocityTracker()
        tracker.reset(0.0, 5.0)
        tracker.add(0.04, 4.0)
        velocity = tracker.add(0.08, 2.5)
        self.assertLess(velocity, 0.0)

    def test_small_motion_does_not_invent_large_velocity(self):
        tracker = VelocityTracker()
        tracker.reset(0.0, 0.0)
        velocity = tracker.add(0.1, 0.1)
        self.assertLess(abs(velocity), 2.0)


if __name__ == "__main__":
    unittest.main()
