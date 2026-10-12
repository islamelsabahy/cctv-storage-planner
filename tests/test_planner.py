import json
import os
import subprocess
import sys
import unittest

from cctvplan import camera_bitrate_kbps, daily_gb, parse_camera_spec, plan, usable_fraction

ROOT = os.path.join(os.path.dirname(__file__), "..")


class MathTests(unittest.TestCase):
    def test_2mp_h264_25fps_hand_calculation(self):
        # 4096 kbps = 512,000 B/s; x 86,400 s = 44.2368 GB per day
        self.assertEqual(camera_bitrate_kbps("2mp"), 4096)
        self.assertAlmostEqual(daily_gb(4096), 44.2368, places=4)

    def test_h265_halves_and_fps_scales_linearly(self):
        self.assertEqual(camera_bitrate_kbps("4mp", "h265", 25), 3072)
        self.assertEqual(camera_bitrate_kbps("4mp", "h265", 12.5), 1536)

    def test_audio_adds_64_kbps(self):
        self.assertEqual(camera_bitrate_kbps("2mp", audio=True), 4096 + 64)

    def test_measured_bitrate_ignores_codec_and_fps(self):
        self.assertEqual(camera_bitrate_kbps("3000k", "h265", 5), 3000)

    def test_hours_and_activity_scale(self):
        self.assertAlmostEqual(daily_gb(4096, 12), daily_gb(4096) / 2)
        self.assertAlmostEqual(daily_gb(4096, 24, 0.25), daily_gb(4096) / 4)

    def test_bad_inputs(self):
        for call in (lambda: camera_bitrate_kbps("9mp"), lambda: camera_bitrate_kbps("2mp", "vp9"),
                     lambda: camera_bitrate_kbps("2mp", fps=0), lambda: daily_gb(1, 25), lambda: daily_gb(1, 24, 1.5)):
            with self.assertRaises(ValueError):
                call()


class RaidTests(unittest.TestCase):
    def test_fractions(self):
        self.assertEqual(usable_fraction("raid5", 4), 0.75)
        self.assertEqual(usable_fraction("raid6", 6), 4 / 6)
        self.assertEqual(usable_fraction("raid10", 4), 0.5)
        self.assertEqual(usable_fraction("raid0", 3), 1.0)

    def test_minimums_and_parity(self):
        with self.assertRaises(ValueError):
            usable_fraction("raid5", 2)
        with self.assertRaises(ValueError):
            usable_fraction("raid10", 5)
        with self.assertRaises(ValueError):
            usable_fraction("raid7", 4)


class PlanTests(unittest.TestCase):
    def test_single_camera_two_4tb_disks_raid1(self):
        res = plan([{"count": 1, "resolution": "2mp"}], 30, 4, "raid1")
        self.assertAlmostEqual(res["gb_per_day"], 44.24, places=2)
        # 30 days = 1327 GB / 0.9 = 1.47 TB needs one mirrored pair of 4 TB disks
        self.assertEqual(res["disks"], 2)
        self.assertEqual(res["usable_tb_after_raid"], 4.0)
        self.assertEqual(res["retention_days_achieved"], 81)  # 4000 GB x 0.9 / 44.2368

    def test_chosen_disks_actually_hold_the_requested_retention(self):
        res = plan([{"count": 16, "resolution": "4mp", "codec": "h265", "fps": 15}], 30, 8, "raid5")
        self.assertGreaterEqual(res["retention_days_achieved"], 30)
        one_fewer = plan([{"count": 16, "resolution": "4mp", "codec": "h265", "fps": 15}], 30, 8, "raid5",
                         disks=res["disks"] - 1) if res["disks"] > 3 else None
        if one_fewer:
            self.assertLess(one_fewer["retention_days_achieved"], 30)

    def test_raid10_uses_even_disks(self):
        res = plan([{"count": 10, "resolution": "2mp"}], 14, 4, "raid10")
        self.assertEqual(res["disks"] % 2, 0)

    def test_more_cameras_never_need_fewer_disks(self):
        last = 0
        for count in range(1, 60, 5):
            n = plan([{"count": count, "resolution": "4mp"}], 30, 8, "raid5")["disks"]
            self.assertGreaterEqual(n, last)
            last = n

    def test_zero_activity_gives_unbounded_retention(self):
        res = plan([{"count": 3, "resolution": "2mp", "activity": 0}], 30, 4, "raid5")
        self.assertIsNone(res["retention_days_achieved"])

    def test_too_big_raises(self):
        with self.assertRaises(ValueError):
            plan([{"count": 5000, "resolution": "8mp"}], 365, 1, "raid5")

    def test_empty_and_invalid(self):
        for args in (([], 30, 4), ([{"count": 0, "resolution": "2mp"}], 30, 4),
                     ([{"count": 1, "resolution": "2mp"}], 0, 4), ([{"count": 1, "resolution": "2mp"}], 30, -1)):
            with self.assertRaises(ValueError):
                plan(*args)


class SpecAndCliTests(unittest.TestCase):
    def test_parse_spec(self):
        self.assertEqual(parse_camera_spec("16x4mp:h265:15"),
                         {"count": 16, "resolution": "4mp", "codec": "h265", "fps": 15.0})
        self.assertEqual(parse_camera_spec("4x3000k")["resolution"], "3000k")
        self.assertEqual(parse_camera_spec("2x2mp:h264:25:12:0.5")["activity"], 0.5)
        self.assertTrue(parse_camera_spec("8x2mp:h265:15:audio")["audio"])
        self.assertEqual(parse_camera_spec("8x2mp:h265:15:12:0.5:AUDIO")["hours"], 12.0)
        self.assertNotIn("audio", parse_camera_spec("8x2mp:h265:15"))

    def test_bad_spec(self):
        for bad in ("16", "x4mp", "a x b", "1x2mp:h264:25:24:1:9"):
            with self.assertRaises(ValueError):
                parse_camera_spec(bad)

    def test_cli(self):
        env = dict(os.environ, PYTHONPATH=ROOT)
        ok = subprocess.run([sys.executable, "-m", "cctvplan", "--camera", "8x2mp:h265:15", "--days", "30", "--json"],
                            cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["cameras"], 8)
        bad = subprocess.run([sys.executable, "-m", "cctvplan", "--camera", "zzz", "--days", "30"],
                             cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)


class MixedFleetTests(unittest.TestCase):
    def test_audio_group_costs_exactly_64_kbps_per_camera_more(self):
        res = plan([{"count": 10, "resolution": "2mp", "codec": "h265", "fps": 15},
                    {"count": 6, "resolution": "2mp", "codec": "h265", "fps": 15, "audio": True}], 30, 8, "raid5")
        plain, with_audio = res["groups"]
        self.assertFalse(plain["audio"])
        self.assertTrue(with_audio["audio"])
        self.assertAlmostEqual(with_audio["kbps"] - plain["kbps"], 64, places=1)

    def test_totals_equal_sum_of_groups(self):
        res = plan([{"count": 10, "resolution": "2mp"}, {"count": 6, "resolution": "4mp", "audio": True},
                    {"count": 2, "resolution": "8mp"}], 30, 8, "raid5")
        self.assertEqual(res["cameras"], 18)
        self.assertAlmostEqual(res["gb_per_day"], sum(g["gb_per_day"] for g in res["groups"]), delta=0.02)

    def test_cli_mixed_groups_with_audio(self):
        env = dict(os.environ, PYTHONPATH=ROOT)
        out = subprocess.run([sys.executable, "-m", "cctvplan", "--camera", "10x2mp:h265:15", "--camera", "6x2mp:h265:15:audio",
                              "--camera", "8x4mp:h265:15", "--days", "30"], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("+audio", out.stdout)
        self.assertIn("Cameras: 24", out.stdout)


class SharedVectorTests(unittest.TestCase):
    def test_vectors_reproduce(self):
        with open(os.path.join(ROOT, "tests", "vectors.json"), encoding="utf-8") as fh:
            vectors = json.load(fh)
        self.assertGreaterEqual(len(vectors), 10)
        for v in vectors:
            c = v["input"]
            got = plan(c["groups"], c["days"], c["disk_tb"], c["raid"], c.get("reserve", 0.10), c.get("disks"))
            self.assertEqual(json.loads(json.dumps(got)), v["expected"], c["name"])


if __name__ == "__main__":
    unittest.main()
