"""CCTV storage and bandwidth planner (planning estimates, not vendor guarantees)."""
from .planner import (
    CODEC_FACTOR,
    RES_KBPS,
    camera_bitrate_kbps,
    daily_gb,
    parse_camera_spec,
    plan,
    usable_fraction,
)

__all__ = ["CODEC_FACTOR", "RES_KBPS", "camera_bitrate_kbps", "daily_gb", "parse_camera_spec", "plan", "usable_fraction"]
__version__ = "0.1.0"
