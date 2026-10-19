"""Kivy-independent momentum helpers for RedAlarm's time wheels."""
from collections import deque
import math


class VelocityTracker:
    """Estimate row velocity from recent samples, reducing single-event jitter."""
    def __init__(self, window_seconds=0.16, max_velocity=36.0, blend=0.72):
        self.window_seconds = max(0.04, float(window_seconds))
        self.max_velocity = abs(float(max_velocity))
        self.blend = min(1.0, max(0.0, float(blend)))
        self.samples = deque()
        self.velocity = 0.0

    def reset(self, timestamp, position):
        self.samples.clear()
        self.samples.append((float(timestamp), float(position)))
        self.velocity = 0.0

    def add(self, timestamp, position):
        timestamp, position = float(timestamp), float(position)
        if self.samples and timestamp < self.samples[-1][0]:
            self.reset(timestamp, position)
            return self.velocity
        self.samples.append((timestamp, position))
        cutoff = timestamp - self.window_seconds
        while len(self.samples) > 2 and self.samples[1][0] < cutoff:
            self.samples.popleft()
        if len(self.samples) < 2:
            return self.velocity
        first_time, first_position = self.samples[0]
        elapsed = timestamp - first_time
        if elapsed < 0.025:
            return self.velocity
        measured = (position - first_position) / elapsed
        measured = max(-self.max_velocity, min(self.max_velocity, measured))
        self.velocity = self.velocity * (1.0 - self.blend) + measured * self.blend
        self.velocity = max(-self.max_velocity, min(self.max_velocity, self.velocity))
        return self.velocity


def advance_fling(position, velocity, dt, friction=2.6, stop_velocity=0.20):
    """Advance one frame; cap frame dt so a UI stall cannot cause a huge jump."""
    dt = min(max(float(dt), 0.0), 0.04)
    velocity = float(velocity)
    position = float(position) + velocity * dt
    velocity *= math.exp(-max(0.0, float(friction)) * dt)
    return position, velocity, abs(velocity) < abs(float(stop_velocity))
