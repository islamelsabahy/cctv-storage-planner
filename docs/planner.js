/* Mirror of cctvplan/planner.py. Keep both in sync: tests/vectors.json is checked by both. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CctvPlanner = factory();
})(typeof self !== "undefined" ? self : this, function () {
  var BASE_FPS = 25, AUDIO_KBPS = 64, NETWORK_HEADROOM = 1.25, MAX_DISKS = 64;
  var RES_KBPS = { "1mp": 2048, "2mp": 4096, "4mp": 6144, "5mp": 8192, "8mp": 12288 };
  var CODEC_FACTOR = { h264: 1.0, h265: 0.5, h265plus: 0.35 };
  var RAID_MIN = { none: 1, raid0: 1, raid1: 2, raid5: 3, raid6: 4, raid10: 4 };

  function usableFraction(raid, n) {
    if (!(raid in RAID_MIN)) throw new Error("unknown RAID level " + raid);
    if (n < RAID_MIN[raid]) throw new Error(raid + " needs at least " + RAID_MIN[raid] + " disks");
    if (raid === "none" || raid === "raid0") return 1;
    if (raid === "raid1") return 0.5;
    if (raid === "raid10") { if (n % 2) throw new Error("raid10 needs an even number of disks"); return 0.5; }
    if (raid === "raid5") return (n - 1) / n;
    return (n - 2) / n;
  }

  function cameraBitrateKbps(resolution, codec, fps, audio) {
    codec = codec || "h264"; fps = fps == null ? BASE_FPS : fps;
    var res = String(resolution).toLowerCase().trim(), kbps;
    if (/^\d+(\.\d+)?k$/.test(res)) {
      kbps = parseFloat(res);
    } else {
      if (!(res in RES_KBPS)) throw new Error("unknown resolution " + resolution);
      if (!(codec in CODEC_FACTOR)) throw new Error("unknown codec " + codec);
      if (fps <= 0) throw new Error("fps must be positive");
      kbps = RES_KBPS[res] * CODEC_FACTOR[codec] * fps / BASE_FPS;
    }
    return kbps + (audio ? AUDIO_KBPS : 0);
  }

  function dailyGb(kbps, hours, activity) {
    hours = hours == null ? 24 : hours; activity = activity == null ? 1 : activity;
    if (!(hours > 0 && hours <= 24)) throw new Error("hours per day must be between 0 and 24");
    if (!(activity >= 0 && activity <= 1)) throw new Error("activity must be between 0 and 1");
    return kbps * 1000 / 8 * hours * 3600 * activity / 1e9;
  }

  function round(x, d) { var m = Math.pow(10, d); return Math.round((x + Number.EPSILON) * m) / m; }

  function plan(groups, retentionDays, diskTb, raid, reserve, disks) {
    raid = raid || "raid5"; reserve = reserve == null ? 0.10 : reserve;
    if (!groups || !groups.length) throw new Error("at least one camera group is required");
    if (!(retentionDays > 0) || !(diskTb > 0)) throw new Error("retention days and disk size must be positive");
    if (!(reserve >= 0 && reserve < 1)) throw new Error("reserve must be in [0, 1)");
    var cameras = 0, totalKbps = 0, perDay = 0, detail = [];
    groups.forEach(function (g) {
      var count = Math.floor(g.count);
      if (!(count >= 1)) throw new Error("camera count must be at least 1");
      var kbps = cameraBitrateKbps(g.resolution, g.codec, g.fps, g.audio);
      var gb = dailyGb(kbps, g.hours, g.activity);
      cameras += count; totalKbps += count * kbps; perDay += count * gb;
      detail.push({ count: count, resolution: String(g.resolution), audio: !!g.audio, kbps: round(kbps, 1),
        gb_per_camera_day: round(gb, 2), gb_per_day: round(count * gb, 2) });
    });
    var neededGb = perDay * retentionDays, grossTb = neededGb / (1 - reserve) / 1000;
    function cap(n) { return n * diskTb * usableFraction(raid, n); }
    var n;
    if (disks == null) {
      n = RAID_MIN[raid];
      var step = (raid === "raid1" || raid === "raid10") ? 2 : 1;
      if (step === 2 && n % 2) n += 1;
      while (cap(n) < grossTb) {
        n += step;
        if (n > MAX_DISKS) throw new Error("needs more than " + MAX_DISKS + " disks; use bigger disks or fewer cameras");
      }
    } else { n = Math.floor(disks); usableFraction(raid, n); }
    var usableGb = cap(n) * 1000 * (1 - reserve);
    return {
      cameras: cameras, groups: detail,
      total_bitrate_mbps: round(totalKbps / 1000, 2),
      network_mbps_with_headroom: round(totalKbps / 1000 * NETWORK_HEADROOM, 2),
      gb_per_day: round(perDay, 2), required_usable_tb: round(grossTb, 2),
      disks: n, raid: raid, raw_tb: round(n * diskTb, 2), usable_tb_after_raid: round(cap(n), 2),
      retention_days_achieved: perDay === 0 ? null : Math.floor(usableGb / perDay)
    };
  }
  return { plan: plan, cameraBitrateKbps: cameraBitrateKbps, dailyGb: dailyGb, usableFraction: usableFraction,
           RES_KBPS: RES_KBPS, CODEC_FACTOR: CODEC_FACTOR };
});
