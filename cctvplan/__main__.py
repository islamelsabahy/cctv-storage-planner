import argparse
import json
import sys

from .planner import RAID_MIN_DISKS, parse_camera_spec, plan


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="cctvplan",
        description="Estimate CCTV storage, disks and network load.",
        epilog="Camera spec: COUNTxRES:CODEC:FPS[:HOURS[:ACTIVITY]][:audio] e.g. 16x4mp:h265:15, 8x2mp:h265:15:audio, or 4x3000k (measured bitrate). Repeat --camera for each type.",
    )
    p.add_argument("--camera", action="append", required=True, metavar="SPEC", help="repeat for each camera group")
    p.add_argument("--days", type=float, required=True, help="retention in days")
    p.add_argument("--disk-tb", type=float, default=8.0, help="size of one disk in TB (decimal, default 8)")
    p.add_argument("--raid", choices=sorted(RAID_MIN_DISKS), default="raid5")
    p.add_argument("--disks", type=int, help="fix the disk count and report the retention it gives")
    p.add_argument("--reserve", type=float, default=0.10, help="free-space reserve fraction (default 0.10)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        groups = [parse_camera_spec(s) for s in a.camera]
        res = plan(groups, a.days, a.disk_tb, a.raid, a.reserve, a.disks)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    print(f"Cameras: {res['cameras']}   Stream total: {res['total_bitrate_mbps']} Mbps "
          f"(plan the network for ~{res['network_mbps_with_headroom']} Mbps)")
    for g in res["groups"]:
        tag = " +audio" if g.get("audio") else ""
        print(f"  {g['count']} x {g['resolution']}{tag}: {g['kbps']} kbps each, {g['gb_per_camera_day']} GB/day each, {g['gb_per_day']} GB/day total")
    print(f"Writes per day: {res['gb_per_day']} GB")
    print(f"Need {res['required_usable_tb']} TB usable for {a.days:g} days (incl. {a.reserve:.0%} reserve)")
    print(f"=> {res['disks']} x {a.disk_tb:g} TB disks in {res['raid'].upper()}: {res['raw_tb']} TB raw, "
          f"{res['usable_tb_after_raid']} TB after RAID, holds {res['retention_days_achieved']} days")
    print("Planning estimate: measure real bitrates before buying.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
