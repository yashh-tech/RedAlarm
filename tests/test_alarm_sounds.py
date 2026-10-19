import hashlib
import os
import tempfile
import unittest
import wave
from alarm_sounds import default_builtin_ringtone, ensure_builtin_ringtones


class BuiltinRingtoneTests(unittest.TestCase):
    def test_generates_five_distinct_playable_waves(self):
        with tempfile.TemporaryDirectory() as cache:
            tones = ensure_builtin_ringtones(cache)
            self.assertEqual(len(tones), 5)
            self.assertEqual([tone["id"] for tone in tones],
                             ["classic", "double", "digital", "chime", "rise"])
            hashes = set()
            for tone in tones:
                self.assertTrue(os.path.isfile(tone["path"]))
                with wave.open(tone["path"], "rb") as audio:
                    self.assertEqual(audio.getnchannels(), 1)
                    self.assertEqual(audio.getsampwidth(), 2)
                    self.assertEqual(audio.getframerate(), 22050)
                    self.assertGreater(audio.getnframes(), 1000)
                with open(tone["path"], "rb") as audio:
                    hashes.add(hashlib.sha256(audio.read()).hexdigest())
            self.assertEqual(len(hashes), 5)

    def test_ringtone_files_are_reused(self):
        with tempfile.TemporaryDirectory() as cache:
            first = ensure_builtin_ringtones(cache)
            second = ensure_builtin_ringtones(cache)
            self.assertEqual([x["path"] for x in first], [x["path"] for x in second])
            self.assertEqual([os.path.getsize(x["path"]) for x in first],
                             [os.path.getsize(x["path"]) for x in second])

    def test_default_is_classic_beep(self):
        with tempfile.TemporaryDirectory() as cache:
            tone = default_builtin_ringtone(cache)
            self.assertEqual(tone["id"], "classic")
            self.assertTrue(os.path.exists(tone["path"]))


if __name__ == "__main__":
    unittest.main()
