#!/usr/bin/env python3
"""Generalized A-roll + B-roll auto-stitcher for the TH tool.

Parametrized port of the VALIDATED `Talking Head/builds/ScriptD_238563/stitch_aroll_broll.py`
(user-approved 2026-07-02). Locked techniques carried over:
  (a) hook pacing — a B-roll product-flash cutaway ~3s in, NOT after the full first A-roll
  (b) zero-drift compositing — B-roll overlaid on an UNTOUCHED base via overlay+setpts+enable,
      never by re-cutting the A-roll into concat segments (that drifts ~135ms)
Plus: de-silence bridges sub-MIN_KEEP islands (kills 5-frame stutter flashes).

Colour-grading REMOVED Rev 2.9 (2026-07-10, user): the per-clip threshold-gated grade added in
Rev 2.8 still wasn't right on the next real run — the Kling clips it DID grade came out looking
worse, "changing the overall vibe of the video" versus the ungraded Seedance baseline. Every clip
is now left exactly as Higgsfield rendered it. If a future run needs colour-matching again, treat
it as a fresh design (do not resurrect `derive_grades` verbatim — see git history if needed).

API:  stitch(cuts, brolls, out_path, work_dir, log)
  cuts   = ordered list of A-roll cut paths, each carrying its own VO slice
  brolls = list of dicts {path, kind} — kind matches th_pipeline.SHOWCASE_SHOTS' sc["key"]
           (sets the validated in-point for that shot type)
"""
import re
import subprocess
from pathlib import Path

FFMPEG = str(Path.home() / ".local/bin/ffmpeg")
FFPROBE = str(Path.home() / ".local/bin/ffprobe")
W, H, FPS = 1080, 1920, 24

SILENCE_DB, SILENCE_MIN = -30, 0.30
KEEP_PAD, MIN_KEEP = 0.10, 0.50

# in-points per B-roll shot type (keys match th_pipeline.SHOWCASE_SHOTS' sc["key"] values
# directly — the old rotate/povrotate/closer aliasing was only needed by the old plan_windows'
# named-slot logic, removed 2026-07-10). RETUNED 2026-07-10 (user, watching the actual stitched
# clips): every Kling B-roll opens on a ~2s static hold before any movement starts (a Kling
# model behavior, not a prompt issue), so an in-point earlier than that just replays dead air.
# Uniform 2.0s until proven otherwise per-kind; flagged provisional now that B-roll durations
# are shrinking to 5-7s (see th_pipeline.SHOWCASE_SHOTS) — re-validate per-kind once real 5-7s
# clips are in hand (a shorter clip may start moving sooner or later than a 10s one did).
BROLL_IN = {"wearpose": 2.0, "catwalk": 2.0, "pov_temple": 2.0, "pov_front": 2.0}
HOOK_FLASH_AT = 3.0
# Rotation cadence — user 2026-07-10: "the clip needs to change every 3 sec ... we had all the
# clips" (the old plan only ever placed 2 windows and left half the generated B-roll unused).
WINDOW_DUR, WINDOW_SPACING = 2.0, 3.0


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(str(c) for c in cmd)}\n{r.stderr[-900:]}")
    return r


def probe_dur(p):
    return float(subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                                 "-of", "default=nw=1:nk=1", str(p)],
                                capture_output=True, text=True).stdout.strip())


VF = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}"


# --------------------------------------------------------------- de-silence base
def _detect_silences(src):
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(src),
                        "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN}",
                        "-f", "null", "-"], capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", r.stderr)]
    dur = probe_dur(src)
    return [(max(0.0, s), min(dur, ends[i] if i < len(ends) else dur))
            for i, s in enumerate(starts)], dur


def _keep_ranges(sil, dur):
    speech, prev = [], 0.0
    for s, e in sil:
        if s > prev:
            speech.append((prev, s))
        prev = e
    if prev < dur:
        speech.append((prev, dur))
    if not sil:
        speech = [(0.0, dur)]
    padded = [(max(0.0, a - KEEP_PAD), min(dur, b + KEEP_PAD)) for a, b in speech]
    merged = []
    for a, b in padded:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    bridged = []
    for a, b in merged:
        if bridged and (b - a) < MIN_KEEP:
            bridged[-1] = (bridged[-1][0], b)
        else:
            bridged.append((a, b))
    return bridged


def _cut_piece(src, t, d, out, silent=False):
    cmd = [FFMPEG, "-y", "-ss", f"{t:.3f}", "-t", f"{d:.3f}", "-i", src, "-vf", VF]
    cmd += ["-an"] if silent else ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18", out]
    run(cmd)
    return out


def _concat(parts, out):
    lf = Path(out).with_suffix(".txt")
    lf.write_text("".join(f"file '{p}'\n" for p in parts))
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", lf,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", out])
    return out


# --------------------------------------------------------------- B-roll auto-plan
def plan_windows(cut_durs, brolls, total):
    """Rotate through EVERY available B-roll on a fixed ~WINDOW_SPACING cadence, starting at
    HOOK_FLASH_AT (the one locked rule kept from the old design: cutaway ~3s in, never after
    the full A-roll). REWRITTEN 2026-07-10 — the old design (hook_flash + hero_close + one
    join_mask + one mid_detail) only ever placed 2-4 windows by CONSTRUCTION and left however
    many B-rolls didn't fit a named slot completely unused; user: 'what happened to the rest of
    it ... we had all the clips.' Now every clip in `brolls` gets used, round-robin, in order,
    wrapping back to the start if the video is longer than len(brolls) * WINDOW_SPACING.
    Returns [(start, dur, name, broll_idx, in_point)]."""
    if not brolls:
        return []
    plan, t, bi = [], HOOK_FLASH_AT, 0
    while t + 0.5 <= total:
        b = brolls[bi % len(brolls)]
        dur = min(WINDOW_DUR, total - t)
        plan.append((t, dur, f"broll_{bi + 1}", bi % len(brolls), BROLL_IN.get(b["kind"], 2.0)))
        t += WINDOW_SPACING
        bi += 1
    return plan


def stitch(cuts, brolls, out_path, work_dir, log=print):
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    log("  de-silencing A-roll ...")
    seg_paths, cut_durs = [], []
    for ci, src in enumerate(cuts):
        sil, dur = _detect_silences(src)
        keeps = _keep_ranges(sil, dur)
        kept = 0.0
        for ki, (a, b) in enumerate(keeps):
            seg = work / f"c{ci}_k{ki}.mp4"
            _cut_piece(src, a, b - a, seg)
            seg_paths.append(seg)
            kept += b - a
        cut_durs.append(kept)
        log(f"    cut{ci+1}: {dur:.2f}s -> {kept:.2f}s ({len(keeps)} ranges)")
    base = _concat(seg_paths, work / "_base.mp4")
    total = sum(cut_durs)

    windows = plan_windows(cut_durs, brolls, total)
    log(f"  base {total:.2f}s | {len(windows)} B-roll windows: "
        + ", ".join(f"{n}@{s:.1f}s" for s, d, n, _, _ in windows))

    inputs = [FFMPEG, "-y", "-i", str(base)]
    fc, prev = [], "0:v"
    bidx = 1
    for wa, wd, name, bi, bin_pt in windows:
        b = brolls[bi]
        bp = work / f"b{bidx:02d}_{Path(b['path']).stem}.mp4"
        _cut_piece(b["path"], bin_pt, wd, bp, silent=True)
        inputs += ["-i", str(bp)]
        fc.append(f"[{bidx}:v]setpts=PTS-STARTPTS+{wa:.3f}/TB,setsar=1,format=yuv420p[b{bidx}]")
        fc.append(f"[{prev}][b{bidx}]overlay=enable='between(t,{wa:.3f},{wa+wd:.3f})'"
                  f":eof_action=pass[o{bidx}]")
        prev = f"o{bidx}"
        log(f"    {name}: {wa:.2f}-{wa+wd:.2f}s <- {Path(b['path']).name} [{b['kind']} in {bin_pt}s]")
        bidx += 1

    run(inputs + ["-filter_complex", ";".join(fc), "-map", f"[{prev}]", "-map", "0:a",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18",
                  "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)])
    log(f"  stitched -> {out_path} ({probe_dur(out_path):.2f}s)")
    return str(out_path)
