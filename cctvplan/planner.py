"""Planning maths. The same formulas are mirrored in docs/planner.js and checked
against the shared vectors in tests/vectors.json.

Defaults are deliberately conservative planning figures (H.264 at 25 fps, medium
quality). Real bitrates depend on scene, lighting, and camera settings: measure
your own cameras and pass a measured bitrate (for example ``3000k``) when you can.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

BASE_FPS = 25
AUDIO_KBPS = 64
DEFAULT_RESERVE = 0.10          # free space kept for the file system and overwrite margin
NETWORK_HEADROOM = 1.25

# kbps per stream at 25 fps, H.264
RES_KBPS: Dict[str, int] = {"1mp": 2048, "2mp": 4096, "4mp": 6144, "5mp": 8192, "8mp": 12288}
# bitrate relative to H.264
CODEC_FACTOR: Dict[str, float] = {"h264": 1.0, "h265": 0.5, "h265plus": 0.35}
RAID_MIN_DISKS: Dict[str, int] = {"none": 1, "raid0": 1, "raid1": 2, "raid5": 3, "raid6": 4, "raid10": 4}
MAX_DISKS = 64


def usable_fraction(raid: str, n: int) -> float:
    """Share of raw capacity that holds data for ``n`` disks."""
    if raid not in RAID_MIN_DISKS:
        raise ValueError(f"unknown RAID level {raid!r} (use one of {', '.join(RAID_MIN_DISKS)})")
    if n < RAID_MIN_DISKS[raid]:
        raise ValueError(f"{raid} needs at least {RAID_MIN_DISKS[raid]} disks")
    if raid in ("none", "raid0"):
        return 1.0
    if raid == "raid1":
        return 0.5
    if raid == "raid10":
        if n % 2:
            raise ValueError("raid10 needs an even number of disks")
        return 0.5
    if raid == "raid5":
        return (n - 1) / n
    return (n - 2) / n  # raid6


def camera_bitrate_kbps(resolution: str, codec: str = "h264", fps: float = BASE_FPS,
                        audio: bool = False) -> float:
    """Estimated stream bitrate in kbps.

    ``resolution`` is a table key such as ``"4mp"`` or a measured bitrate such as
    ``"3000k"``; a measured bitrate is used as given (codec and fps are ignored).
    """
    res = str(resolution).lower().strip()
    if res.endswith("k") and res[:-1].replace(".", "", 1).isdigit():
        kbps = float(res[:-1])
    else:
        if res not in RES_KBPS:
            raise ValueError(f"unknown resolution {resolution!r} (use {', '.join(RES_KBPS)} or a bitrate like 3000k)")
        if codec not in CODEC_FACTOR:
            raise ValueError(f"unknown codec {codec!r} (use {', '.join(CODEC_FACTOR)})")
        if fps <= 0:
            raise ValueError("fps must be positive")
        kbps = RES_KBPS[res] * CODEC_FACTOR[codec] * fps / BASE_FPS
    return kbps + (AUDIO_KBPS if audio else 0)


def daily_gb(kbps: float, hours: float = 24, activity: float = 1.0) -> float:
    """Decimal gigabytes written per day by one stream."""
    if not 0 < hours <= 24:
        raise ValueError("hours per day must be between 0 and 24")
    if not 0 <= activity <= 1:
        raise ValueError("activity must be between 0 and 1")
    return kbps * 1000 / 8 * hours * 3600 * activity / 1e9


def parse_camera_spec(spec: str) -> dict:
    """Parse ``COUNTxRES:CODEC:FPS[:HOURS[:ACTIVITY]]``, e.g. ``16x4mp:h265:15:24:0.4``."""
    try:
        head, *rest = spec.split(":")
        count_s, res = head.lower().split("x", 1)
        group = {"count": int(count_s), "resolution": res}
        keys = ("codec", "fps", "hours", "activity")
        for key, val in zip(keys, rest):
            group[key] = val if key == "codec" else float(val)
        if len(rest) > len(keys):
            raise ValueError
        return group
    except (ValueError, TypeError):
        raise ValueError(f"bad camera spec {spec!r}; expected COUNTxRES:CODEC:FPS[:HOURS[:ACTIVITY]]") from None


def plan(groups: List[dict], retention_days: float, disk_tb: float, raid: str = "raid5",
         reserve: float = DEFAULT_RESERVE, disks: Optional[int] = None) -> dict:
    """Size storage for camera groups.

    Each group: ``count``, ``resolution``, optional ``codec`` (h264), ``fps`` (25),
    ``hours`` (24), ``activity`` (1.0), ``audio`` (False).
    If ``disks`` is given the result reports the retention that many disks can hold;
    otherwise the smallest disk count meeting ``retention_days`` is computed.
    """
    if not groups:
        raise ValueError("at least one camera group is required")
    if retention_days <= 0 or disk_tb <= 0:
        raise ValueError("retention days and disk size must be positive")
    if not 0 <= reserve < 1:
        raise ValueError("reserve must be in [0, 1)")

    cameras, total_kbps, per_day = 0, 0.0, 0.0
    detail = []
    for g in groups:
        count = int(g["count"])
        if count < 1:
            raise ValueError("camera count must be at least 1")
        kbps = camera_bitrate_kbps(g["resolution"], g.get("codec", "h264"), g.get("fps", BASE_FPS), g.get("audio", False))
        gb = daily_gb(kbps, g.get("hours", 24), g.get("activity", 1.0))
        cameras += count
        total_kbps += count * kbps
        per_day += count * gb
        detail.append({"count": count, "resolution": str(g["resolution"]), "kbps": round(kbps, 1),
                       "gb_per_camera_day": round(gb, 2), "gb_per_day": round(count * gb, 2)})

    needed_gb = per_day * retention_days
    gross_tb = needed_gb / (1 - reserve) / 1000

    def capacity_tb(n: int) -> float:
        return n * disk_tb * usable_fraction(raid, n)

    if disks is None:
        n = RAID_MIN_DISKS[raid]
        step = 2 if raid in ("raid1", "raid10") else 1
        if raid in ("raid1", "raid10") and n % 2:
            n += 1
        while capacity_tb(n) < gross_tb:
            n += step
            if n > MAX_DISKS:
                raise ValueError(f"needs more than {MAX_DISKS} disks of {disk_tb} TB; use bigger disks or fewer cameras")
    else:
        n = int(disks)
        usable_fraction(raid, n)  # validates count for this RAID level

    usable_gb = capacity_tb(n) * 1000 * (1 - reserve)
    retention = None if per_day == 0 else math.floor(usable_gb / per_day)
    return {
        "cameras": cameras,
        "groups": detail,
        "total_bitrate_mbps": round(total_kbps / 1000, 2),
        "network_mbps_with_headroom": round(total_kbps / 1000 * NETWORK_HEADROOM, 2),
        "gb_per_day": round(per_day, 2),
        "required_usable_tb": round(gross_tb, 2),
        "disks": n,
        "raid": raid,
        "raw_tb": round(n * disk_tb, 2),
        "usable_tb_after_raid": round(capacity_tb(n), 2),
        "retention_days_achieved": retention,
    }
