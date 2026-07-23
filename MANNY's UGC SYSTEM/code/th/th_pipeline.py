#!/usr/bin/env python3
"""TH tool (A.1 Talking Head) pipeline — staged orchestration, 2 approval gates.
Rebuilt 2026-07-04 after the v1 run failed (see docs/memory + project memory).

Key v2 changes:
  - CHARACTERS sourced from the FULL library (Female Indian + European), like the PM tool.
  - FRAME = the proven kit recipe: one Nano-Banana pass from the ANCHOR (identity holds) +
    location + clothing + light-makeup. NO per-character hand-built sheet, NO recolor-from-
    scene drift.
  - CLOTHING = Top style/color + Bottom style/color (clothing.json). LOCATION dropdown
    (locations.json) → environments vary run to run.
  - NO reuse-hook: every cut (incl. the no-glasses hook) is generated fresh from THIS run's
    script → one person, one outfit, one scene throughout.
  - B-ROLL = natural-scale WEARING shots (dropped the physically-impossible held-to-lens hold).
  - SCRIPT locked to Pattern-1, general (no origin city), Claude-vision on the PID images.

Zero Claude tokens at runtime EXCEPT the scripting stage (creative core; `claude -p`).
Run: python3 app.py  → http://127.0.0.1:7861   (RESTART after any edit; debug=False)
"""
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

import scripting
import stitcher
import voicer


def _find_data_root() -> Path:
    if "UGC_DATA_ROOT" in os.environ:
        return Path(os.environ["UGC_DATA_ROOT"])
    c = Path(__file__).resolve().parent
    for _ in range(8):
        if (c / "Stock PID Images").exists() and (c / "Character Library").exists():
            return c
        c = c.parent
    raise RuntimeError("Cannot find UGC project root — export UGC_DATA_ROOT='/path/to/Perf UGC Ads'")


ROOT = _find_data_root()
HOME = Path.home()
ENV = dict(os.environ)
ENV["PATH"] = f"{HOME}/.local/node/bin:{HOME}/.local/bin:" + ENV.get("PATH", "")

TOOL = Path(__file__).resolve().parent
STOCK = ROOT / "Stock PID Images"
CHAR_DIRS = [("Female Indian", ROOT / "Character Library" / "Female Indian"),
             ("Female European", ROOT / "Character Library" / "Female European")]
QC = TOOL.parent / "pm-tool" / "qc_check.py"          # shared QC gate
FFMPEG = str(HOME / ".local/bin/ffmpeg")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
NSFW_RETRIES = 3

CLOTHING = json.loads((TOOL / "clothing.json").read_text())
LOCATIONS = {k: v for k, v in json.loads((TOOL / "locations.json").read_text()).items()
             if not k.startswith("_")}


# ----------------------------------------------------------------- registries
def list_characters():
    """[(char_id, anchor_path, group)] across the library — like the PM tool."""
    out = []
    for group, base in CHAR_DIRS:
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            anchors = sorted(d.glob("*_anchor*.png")) or sorted(
                p for p in d.iterdir() if p.suffix.lower() in IMG_EXT)
            if anchors:
                out.append((d.name, anchors[0], group))
    return out


def character_entry(char_id):
    for cid, anchor, group in list_characters():
        if cid == char_id:
            return anchor, group
    raise FileNotFoundError(f"character '{char_id}' not found in the library")


def product_images(pid):
    pid = str(pid).strip()
    d = STOCK / pid
    if d.is_dir():
        imgs = sorted(p for p in d.iterdir() if p.suffix.lower() in IMG_EXT)
        if imgs:
            return imgs
    for ext in IMG_EXT:
        f = STOCK / f"{pid}{ext}"
        if f.exists():
            return [f]
    return []


def list_pids():
    return sorted(d.name for d in STOCK.iterdir() if d.is_dir() and product_images(d.name))


def outfit_phrase(top_style, top_color, bottom_style, bottom_color):
    t = CLOTHING["tops"].get(top_style, list(CLOTHING["tops"].values())[0]).format(color=top_color)
    b = CLOTHING["bottoms"].get(bottom_style, list(CLOTHING["bottoms"].values())[0]).format(color=bottom_color)
    return f"{t} and {b}"


# ----------------------------------------------------------------- HF CLI (pm-tool pattern)
def _hf(*args):
    return subprocess.run(["higgsfield", *args], capture_output=True, text=True, env=ENV)


def _submit(model, params, medias):
    args = ["generate", "create", model]
    for k, v in params.items():
        args += [f"--{k}", str(v)]
    for flag, path in medias:
        args += [f"--{flag}", str(path)]
    args.append("--json")
    r = _hf(*args)
    if r.returncode != 0:
        raise RuntimeError(f"submit {model} failed: {(r.stderr or r.stdout).strip()[:200]}")
    d = json.loads(r.stdout)
    item = d[0] if isinstance(d, list) and d else d
    jid = item if isinstance(item, str) else item.get("id")
    if not jid:
        raise RuntimeError(f"submit {model}: no job id: {str(item)[:300]}")
    return jid


def _wait(job_id, timeout=1800, interval=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _hf("generate", "get", job_id, "--json")
        if r.returncode == 0:
            d = json.loads(r.stdout)
            it = d[0] if isinstance(d, list) and d else d
            st = it.get("status")
            if st == "completed":
                return it.get("result_url") or (it.get("results") or {}).get("rawUrl")
            if st in ("nsfw", "ip_detected"):
                raise RuntimeError(f"FILTERED:{st}:{job_id}")
            if st in ("failed", "canceled"):
                raise RuntimeError(f"job {job_id} -> {st}")
        time.sleep(interval)
    raise TimeoutError(f"job {job_id} timed out")


def _download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    return dest


# ----------------------------------------------------------------- spend pacer (6 video gens / 60 min)
SPEND_LOG = ROOT / "Ads" / "_th_spend_log.json"
MAX_VIDEOS_PER_HOUR = 6


def _pace_video_submit(log=print):
    now = time.time()
    hist = []
    if SPEND_LOG.exists():
        try:
            hist = [t for t in json.loads(SPEND_LOG.read_text()) if now - t < 3600]
        except Exception:
            hist = []
    while len(hist) >= MAX_VIDEOS_PER_HOUR:
        wait = int(3600 - (now - hist[0])) + 5
        log(f"  [PACER] {len(hist)} video gens in the last hour — waiting {wait}s (6/hr guardrail)")
        time.sleep(min(wait, 300))
        now = time.time()
        hist = [t for t in hist if now - t < 3600]
    hist.append(now)
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    SPEND_LOG.write_text(json.dumps(hist))


# ----------------------------------------------------------------- prompt gate
_NSFW_SUBS = [(r"grey\s+studio", "boutique interior"), (r"gray\s+studio", "boutique interior"),
              (r"tight\s+ECU", "close portrait"), (r"tight\s+face", "close portrait")]
_BRAND_WARNS = ["lenskart", "vincent chase", "john jacobs", "meller", "oakley", "ray-ban", "prada", "gucci"]
_LIMIT = 2400


def _prompt_gate(prompt, log=print):
    fixed = prompt
    for brand in _BRAND_WARNS:
        if brand.lower() in fixed.lower() and "speaks these exact words" not in fixed.lower():
            log(f"  [GATE WARN] brand '{brand}' outside dialogue — ip_detected risk")
    for pat, repl in _NSFW_SUBS:
        if re.search(pat, fixed, re.IGNORECASE):
            fixed = re.sub(pat, repl, fixed, flags=re.IGNORECASE)
            log(f"  [GATE FIX] NSFW pattern -> '{repl}'")
    return fixed[:_LIMIT]


def _qc(kind, target, references, log=print):
    refs = references if isinstance(references, (list, tuple)) else [references]
    cmd = ["python3", str(QC), kind, "--" + ("video" if kind == "video" else "image"),
           str(target), "--reference", *[str(r) for r in refs], "--strict"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=ENV)
    m = re.search(r'"contact_sheet":\s*"([^"]+)"', r.stdout)
    return (m.group(1) if m else None), r.stdout


# ----------------------------------------------------------------- image gen
def _gen_image(prompt, images, out_path, log=print, attempts=2, timeout=300):
    params = {"prompt": prompt, "aspect_ratio": "9:16", "resolution": "2k"}
    medias = [("image", p) for p in images]
    for a in range(1, attempts + 1):
        try:
            jid = _submit("nano_banana_2", params, medias)
            log(f"    nano_banana attempt {a} -> {jid}")
            url = _wait(jid, timeout=timeout, interval=5)
            if url:
                return _download(url, out_path)
        except Exception as e:
            log(f"    nano_banana attempt {a} failed: {e}")
    return None


def _soften(src, out):
    subprocess.run([FFMPEG, "-y", "-i", str(src),
                    "-vf", "smartblur=luma_radius=1.5:luma_strength=0.6:luma_threshold=0",
                    "-frames:v", "1", "-q:v", "2", str(out)], capture_output=True, check=True)
    return out


# --- prompts (PROVEN kit recipe; identity from anchor, makeup + outfit + location layered) ---
KIT_PROMPT = (
    "A friend took this candid photo of this exact woman from a few steps back in {location}. "
    "She is the SAME person as in image 1 — keep her exact face, bone structure, skin tone, "
    "skin texture and hair identical; do NOT change her identity. She is wearing {outfit}. "
    "{makeup} Natural waist-up to three-quarter framing, standing relaxed with her arms down, "
    "nothing in her hands, no phone, no mirror, no sunglasses, soft natural expression toward "
    "the camera. Premium but candid iPhone snapshot — real skin texture with visible pores, "
    "slightly soft, no HDR, no studio lighting, no heavy glamour retouch, no text, no captions. "
    "Soft natural daylight.")

TRYON_PROMPT = (
    "The exact same woman, outfit, room, light and framing as image 1, now WEARING the exact "
    "eyewear from image 2 — identical frame shape, colour and lens tint/clarity, sized correctly "
    "to her face, rim about face-width, not oversized. Nothing else changes. Premium candid iPhone "
    "snapshot, real untouched skin, unedited, no text, no captions.")

_SKIN = ("Real untouched skin, natural window light, candid iPhone feel, subtle film grain like a "
         "Sony A7 III at ISO 1600. No oversharpening, no beauty filter, no HDR, no identity drift. ")

# CADENCE cue — Rev 2.2 fix (2026-07-08): each talking cut is generated by a different engine
# (Seedance for the hook, Kling for wearing/pose), and each invents its OWN delivery of the same
# script. The post-hoc ElevenLabs STS pass unifies TIMBRE but faithfully preserves whatever cadence
# the source engine used — so a flatter/less-Indian delivery on one cut survives the voice swap and
# reads as "the tone changes mid-video." This cue is added to EVERY talking-cut prompt (both engines)
# to narrow that gap at the source, before STS ever touches it. Cheap to test; does not guarantee
# full uniformity since they remain two different models — see [[project-a1-tool-v1-failure-and-redirect]].
_CADENCE = ("She speaks with a natural, warm Indian-English conversational accent and a relaxed, "
            "unhurried pace — not flat, not rushed, not robotic. ")

    # BARE_FACE lock — Rev 2.3 fix (2026-07-08): tried to keep the hook bare-faced (matching a
    # no-glasses kit_soft start image) via a sandwiched negative, since generate_audio=true makes
    # Seedance weight the spoken words heavily. Confirmed working once (PID 147022), then FAILED
    # AGAIN on PID 241184 (2026-07-10) — a heavy-product hook script ("My new Lens kart glasses
    # don't just complete the look — they are the look") still hallucinated a frame onto her face
    # near the end of the clip. Two failures on the same mechanism means the mechanism is wrong,
    # not the wording of the negative.
    #
    # Rev 2.9 fix (2026-07-10, user): stop fighting the model to hide eyewear it's being told about
    # in the SAME breath — start the hook from tryon_soft (already wearing the product, same still
    # every Kling talking cut and B-roll already uses) instead of kit_soft (bare-faced). Nothing to
    # drift FROM means nothing to hallucinate — the product is simply already there, consistent
    # with every other cut in the video. kit_soft is untouched everywhere else (still needed for the
    # POV hand-only stills, which must stay bare/faceless on their own separate grounds).
HOOK_TMPL = (
    "Authentic UGC talking-head video, vertical 9:16, filmed on a phone from across a bright room — "
    "she stands back, upper body and room visible, wearing the exact {product_short} from the start "
    "image throughout (identical shape, colour and lenses, never morph or remove them). "
    "She talks to the camera with natural expressive hand gestures and animated real-person energy, "
    "shifting her weight, lively, not stiff. " + _CADENCE +
    "She speaks these exact words: \"{script}\" Preserve the exact face, composition, colours and "
    "skin texture of the start image — do not push in or zoom. " +
    _SKIN + "No captions, no text.")

WEARING_TMPL = (
    "Authentic UGC talking-head video, vertical 9:16, filmed on a phone in a bright room, medium "
    "framing — she wears the exact {product_short} from the start image throughout (identical shape, "
    "colour and lenses, never morph or remove them). " + _SKIN + _CADENCE +
    "[1] Medium front, natural expressive hand gestures as she speaks. [2] A slight three-quarter "
    "turn, one hand rising briefly near the glasses. [3] Settles square to camera, still talking, "
    "lively. She speaks these exact words, lip-synced: \"{script}\" No captions, no text.")

# Smile toned down Rev 2.9 (2026-07-10, user: the Kling pose cut's smile was "getting too big ...
# doesn't look very natural"). Both mentions in this template used to just say "smile" with no
# size/restraint cue — same lesson as the sleeve/grip fixes earlier this project: state the wanted
# result AND explicitly rule out the failure mode, don't leave the model to improvise the intensity.
POSE_TMPL = (
    "Authentic UGC talking-head video, vertical 9:16, filmed on a phone in a bright room, medium "
    "framing — the same woman wearing the exact {product_short} from the start image (identical "
    "shape, colour, lenses; the frame never morphs). " + _SKIN + _CADENCE +
    "[1] Medium front, relaxed posture, a small natural smile wearing the eyewear — subtle, lips "
    "barely parted, NOT a big toothy grin. [2] She lifts her chin slightly, two fingers brush the "
    "temple, a calm composed expression. [3] A slow three-quarter turn, hair shifting naturally, "
    "gaze staying toward the lens. [4] Settles square, composed hold, the same restrained smile. "
    "She delivers this line, lip-synced: \"{script}\" No studio flash, no warped frames, no captions, "
    "no text, no plastic skin, no exaggerated or oversized smile.")

# B-ROLL — Rev 2.2 mix (2026-07-08, user-specified): FIXED at 4 clips total — 2 posing (wearing-type,
# from tryon_soft) + 2 POV (hand-only, from the validated pov_temple/pov_front stills — see Detail 4/5
# of the Rev 2.1 architecture doc). Dropped touch_temple + hairflip to stay at 4. Each entry carries
# its own start-still key + which base prompt block it uses (wearing vs pov).
# Durations SHORTENED Rev 2.8 (2026-07-10, user): stitcher.py only ever uses ~2s windows of any
# given B-roll (see stitcher.WINDOW_DUR) — generating a full 10s Kling clip when 2-4s actually
# lands in the final cut was pure wasted credits. POV clips need less runway than the wearing/
# catwalk ones (a hand-hold rotation reads fine short); catwalk gets the full 7s since its motion
# (steps + turn + settle) needs more room than wearpose's single held pose.
SHOWCASE_SHOTS = [
    {"key": "wearpose", "still": "tryon_soft", "base": "wearing", "duration": 6,
     "motion": "She wears the eyewear and moves through relaxed confident poses — a small, natural, "
     "closed-lip smile, NOT a big grin, weight shift, hand resting near her jaw. Natural real "
     "movement, normal speed."},
    {"key": "catwalk", "still": "tryon_soft", "base": "wearing", "duration": 7,
     "motion": "Wearing the eyewear, she takes a few relaxed steps toward the camera then a natural "
     "turn and settle, easy confident energy."},
    {"key": "pov_temple", "still": "pov_temple_soft", "base": "pov", "duration": 5,
     "motion": "She gently rotates the eyewear slightly in her hand, a small natural POV movement — "
     "hand and forearm only, no face visible."},
    {"key": "pov_front", "still": "pov_front_soft", "base": "pov", "duration": 5,
     "motion": "She holds the eyewear steady then tilts it slightly, a small natural POV movement — "
     "hand and forearm only, no face visible."},
]
_SHOWCASE_BASE = (
    "Authentic UGC product clip, vertical 9:16, filmed on a phone in the same bright room, the same "
    "woman wearing the exact {product_short} from the start image at natural real-life scale — "
    "identical shape, colour and lenses, never oversized, never morphs. " + _SKIN)

# POV B-roll base — hand/forearm only, no face. Physical-scale lock is the load-bearing clause (the
# v1 lesson: an image model told to hold a REFERENCE object at true scale is reliable; a video model
# asked to invent that same hold from text alone is not — see Detail 4 of the Rev 2.1 architecture).
_POV_BROLL_BASE = (
    "Authentic UGC product clip, vertical 9:16, first-person POV — ONLY her hand and forearm are "
    "visible holding the exact {product_short} from the start image, NO face, NO other body parts. "
    "Physical realism is critical: the eyewear stays at its TRUE real-world size in her hand — "
    "proportionate to a real pair of glasses, NOT enlarged, NOT oversized. Identical frame shape, "
    "colour and lens clarity to the start image, never morphs. " + _SKIN)

# --- POV stills (Nano Banana) — Rev 2.2, promoted from the validated PID 208504 test into the
# general pipeline. Base = kit_soft (NO glasses) not tryon_soft — using an already-wearing base
# produced a continuity error (wearing AND holding a second pair) in the original test.
#
# Rev 2.4 (2026-07-09): the single generic "{side} facing up" template held scale correctly but
# left the GRIP itself unspecified, so the model improvised the hand mechanics — right maybe half
# the time. Split into two grip-specific templates matching 3 real reference photos (`POV Frame
# ref/`). Rejected by the user on PID 241187's real run the same day: pov_temple rendered one
# temple extended straight up (unfolded) while the other stayed folded and kicked out sideways —
# an open/closed mismatch, because the prompt specified ONE temple's direction and left the other's
# state unstated, so the model improvised it inconsistently. pov_front rendered a full fist wrapped
# around the frame (fingers curled under AND thumb over read as a whole-hand grab, not a pinch) —
# "nobody holds glasses like this."
#
# Rev 2.5 (2026-07-09): re-examined the 3 reference photos at the pixel level.
#   Position 1 — the frame is fully CLOSED (both temples folded flat against the lens fronts, lying
#     parallel to each other, both tips exiting the SAME side) and held VERTICALLY by pinching just
#     the top hinge corner between thumb and index finger only — like picking up a pen. This is the
#     "just picked it up off the table" gesture, not an unfolded side profile.
#   Position 3 — the frame is fully OPEN and held by a delicate thumb-and-index PINCH on ONE temple
#     near its hinge ONLY — the other three fingers stay curled into the palm, untouching. Nothing
#     else contacts the frame, which is why both lenses + bridge hang fully unobstructed toward camera.
#   Position 2 — a macro close-up on just the temple tip/branding; not a full-frame hold, but its
#     lesson (temple text must stay legible) is folded into POV_FRONT.
# Both templates now explicitly state the OPEN/CLOSED state of BOTH temples and exactly which
# fingers touch the frame — leaving either ambiguous is what caused Rev 2.4's failures.
#
# Rev 2.6 (2026-07-09): Rev 2.5 fixed the open/closed consistency but still shipped 2 defects, both
# caught by the user on the same PID 241187 test images (job 4c16ff29 = pov_temple, plus a sleeve
# continuity bug present in Rev 2.4's rejected images too, just not reported until now):
#   1. Sleeve continuity — _POV_SCENE said only "her top's sleeve visible at the edge of frame,"
#      with no sleeve LENGTH lock. kit_frame's actual top is short/half-sleeve (bare forearm+wrist),
#      but both POV stills rendered a sleeve cuff reaching the wrist — the model defaulted to a
#      generic long-sleeve holding-pose reference instead of matching image 1's actual hem. Fixed by
#      locking the sleeve length explicitly to image 1, generically (works for any future top added
#      to clothing.json, not hardcoded to "short sleeve").
#   2. pov_temple's hold angle was a flat EDGE-ON silhouette (both hinges stacked, lens rims seen
#      only in profile) — re-checked against `POV Frame ref/postion1.heic` pixel-by-pixel and that
#      reference is NOT edge-on: it's a 3/4 angle showing the LENS FRONTS, with the folded temple
#      draped diagonally across both lens faces. An edge-on silhouette barely shows the product and
#      gives a video model almost nothing to animate a believable rotation from — user: "the holding
#      position is not correct which will result in incorrect motion." Fixed by explicitly locking
#      the 3/4 angle + visible lens fronts + diagonal temple drape, with an explicit edge-on negative.
#
# Rev 2.7 (2026-07-09): Rev 2.6's sleeve fix ("if image 1 shows a short sleeve, stay bare... never
# extend the sleeve") did NOT hold on re-test — pixel-cropped both new stills and found the SAME
# ribbed cuff at the wrist in both. Root cause: the instruction still asserted "her top's sleeve IS
# visible at the edge of frame," which primes the model to draw fabric no matter what the
# conditional clause after it says — a conditional add-on rarely overrides the concrete claim it's
# attached to. The actual geometry: every top in `clothing.json` (tank/cropped tee/loose tee/rolled
# satin shirt/off-shoulder) ends above the elbow, and this POV crop only shows wrist-to-mid-forearm
# — nowhere near the elbow — so the correct, declarative fact is that NO sleeve fabric should be in
# frame at all. Stated it that way instead of conditionally. (Known gap, not yet hit: `clothing.json`'s
# "oversized button-down shirt" doesn't specify sleeve length and could plausibly read as full-length
# — if a future run on that top shows a cuff here, give it its own explicit long-sleeve carve-out
# rather than re-adding a conditional.)
_POV_SCALE_LOCK = (
    "Physical realism is critical: the eyewear appears at its TRUE real-world size — proportionate "
    "to a real pair of glasses relative to her hand, NOT enlarged, NOT oversized. Her hand, fingers "
    "and forearm are anatomically correct — a normal five-fingered grip, no extra or missing digits. ")

_POV_SCENE = (
    "Same room, soft natural window light as image 1, softly out of focus in the background. Her top "
    "is short-sleeved/sleeveless exactly as in image 1, and its hem ends well above the elbow — far "
    "above this shot's framing. So NO sleeve, cuff, or fabric of any kind appears anywhere in this "
    "image: her entire visible forearm, wrist and hand are bare skin from the top edge of frame all "
    "the way down. Identical frame shape, colour and lens clarity to image 2, never morphs. Premium "
    "candid iPhone POV snapshot, real skin texture, unedited, no text, no captions.")

POV_TEMPLE_PROMPT = (
    "First-person POV photo, as if the camera IS her own eyes looking down at her hand — ONLY her "
    "hand and forearm are visible, matching her exact skin tone from image 1. NO face, NO other body "
    "parts, NO mirror visible in frame. The exact eyewear from image 2 is fully FOLDED CLOSED — both "
    "temple arms folded flat, lying parallel to each other and draped DIAGONALLY ACROSS THE FRONT of "
    "the lenses, both temple tips exiting near the SAME lower corner. Never render one temple extended "
    "open while the other stays folded, and never point the two temples in opposite directions — they "
    "move as one closed unit. She holds this closed, folded frame UPRIGHT and VERTICAL by pinching "
    "ONLY the top hinge corner between her thumb-tip and index-fingertip, like picking up a pen — her "
    "other three fingers stay loosely curled into her palm, not touching the frame. The rest of the "
    "closed frame hangs straight down below the pinch, tilted at a natural 3/4 angle so the FRONT of "
    "both lenses is clearly visible toward camera with the folded temples draped across them — this is "
    "NOT a flat edge-on silhouette and NOT a pure side profile; the lens fronts must always be visible, "
    "like she just picked it up off a table to glance at it. "
    + _POV_SCALE_LOCK + _POV_SCENE)

POV_FRONT_PROMPT = (
    "First-person POV photo, as if the camera IS her own eyes looking down at her hand — ONLY her "
    "hand and forearm are visible, matching her exact skin tone from image 1. NO face, NO other body "
    "parts, NO mirror visible in frame. The exact eyewear from image 2 is fully OPEN, both temple "
    "arms extended at their normal ready-to-wear angle, parallel to each other. She holds it with a "
    "delicate two-finger PINCH on ONE temple arm near its hinge — ONLY her thumb-tip and "
    "index-fingertip touch that temple, like holding a pen; her middle, ring and pinky fingers stay "
    "loosely curled into her palm and do NOT touch the frame at all. This is a light pinch, NOT a "
    "fist and NOT a whole-hand grab — no finger or knuckle overlaps either lens or the bridge. The "
    "frame hangs FRONT-FACING toward the camera, both lenses and the full bridge completely "
    "unobstructed and clearly visible, tilted gently. The far, unheld temple arm extends freely away "
    "in the same open angle as the held one, softly out of focus in the background. Any text on the "
    "held temple stays sharp and legible. " + _POV_SCALE_LOCK + _POV_SCENE)


def save_script(st):
    """Persist the script + cuts to disk (Rev 2.3 — the script/log were only ever in the running
    Flask process's memory, unretrievable after the fact except by cross-referencing Higgsfield's
    own job records, which is how the PID 147022 hook-content bug was diagnosed on 2026-07-08).
    Called after Stage 1 and again after any Gate-1 edit, so every run is always inspectable."""
    Path(st["out"]).mkdir(parents=True, exist_ok=True)
    (Path(st["out"]) / "script.json").write_text(json.dumps(st["script_data"], indent=2))


# ----------------------------------------------------------------- STAGE 1 (script + frames)
def run_stage_images(pid, char_id, top_style, top_color, bottom_style, bottom_color, location,
                     script_mode="manual", log=print):
    pid = str(pid).strip()
    out = ROOT / "Ads" / pid / "_selfserve_th"
    (out / "_stills").mkdir(parents=True, exist_ok=True)
    anchor, group = character_entry(char_id)
    prods = product_images(pid)
    if not prods:
        raise FileNotFoundError(f"No product images in 'Stock PID Images/{pid}/'")
    loc_desc = LOCATIONS.get(location, next(iter(LOCATIONS.values())))
    outfit = outfit_phrase(top_style, top_color, bottom_style, bottom_color)

    st = {"pid": pid, "char": char_id, "group": group, "location": location,
          "outfit": outfit, "out": str(out), "stills": {}, "warnings": [],
          "script_mode": script_mode}

    # 1. SCRIPT — Manual = Claude Pattern-1 (Celebrity Interruption), vision on PID images.
    #    Auto = Pattern-2 (Direct Hook Testimonial, randomized from `Talking head scripts..pdf`'s
    #    architecture) — see scripting.generate_auto_script(). Either way: no hook reuse, fresh
    #    every run.
    if script_mode == "auto":
        sd = scripting.generate_auto_script([str(p) for p in prods[:3]], log=log)
    else:
        sd = scripting.generate_script([str(p) for p in prods[:3]], log=log)
    st["script_data"] = sd
    if any(n.startswith("[LINT FAIL]") for n in sd.get("notes", [])):
        st["warnings"].append("Script tripped a hard lint (origin-city leak) — regenerate the "
                              "script at Gate 1 before approving, or edit it.")

    # 2. KIT FRAME (proven recipe: anchor only, identity holds) + soft variant for the hook
    kit = _gen_image(KIT_PROMPT.format(location=loc_desc, outfit=outfit, makeup=CLOTHING["MAKEUP"]),
                     [anchor], out / "_stills" / "kit_frame.png", log=log)
    if not kit:
        raise RuntimeError("character kit frame failed after 2 attempts — re-run Stage 1")
    st["stills"]["kit_frame"] = str(kit)
    st["stills"]["kit_soft"] = str(_soften(kit, out / "_stills" / "kit_soft.png"))

    # 3. TRY-ON (kit + product) — start image for wearing/pose + B-roll; QC vs PID
    tryon = _gen_image(TRYON_PROMPT, [kit, prods[0]], out / "_stills" / "tryon.png", log=log)
    if not tryon:
        raise RuntimeError("try-on still failed — wearing/pose cuts need it; check the PID front image")
    st["stills"]["tryon"] = str(tryon)
    st["stills"]["tryon_soft"] = str(_soften(tryon, out / "_stills" / "tryon_soft.png"))
    sheet, _ = _qc("image", tryon, prods[:2], log=log)
    st["stills"]["tryon_qc_sheet"] = sheet

    # 4. POV pair (Rev 2.4, kit_soft — NOT tryon_soft — as the base; two grip-specific templates,
    # not one generic template — see POV_TEMPLE_PROMPT/POV_FRONT_PROMPT docstring)
    pov_refs = [kit] + prods[:2]
    for key, prompt in (("pov_temple", POV_TEMPLE_PROMPT), ("pov_front", POV_FRONT_PROMPT)):
        still = _gen_image(prompt, pov_refs, out / "_stills" / f"{key}.png", log=log)
        if not still:
            st["warnings"].append(f"{key} still failed — that POV B-roll slot will be skipped "
                                  "(stitcher adapts to fewer B-rolls)")
            continue
        st["stills"][key] = str(still)
        st["stills"][f"{key}_soft"] = str(_soften(still, out / "_stills" / f"{key}_soft.png"))

    log(f"  Stage 1 done | script {len(sd['script'].split())}w / {len(sd['cuts'])} cuts | "
        f"kit + try-on + POV stills ready")
    save_script(st)
    return st


# ----------------------------------------------------------------- STAGE 2 (videos)
def run_stage_videos(st, log=print):
    out = Path(st["out"])
    prods = product_images(st["pid"])
    sd = st["script_data"]
    short = sd.get("product_short", "eyewear")
    st["cuts"], st["brolls"], st["errors"] = [], [], []

    def submit_video(model, params, medias, label):
        _pace_video_submit(log=log)
        for a in range(1, NSFW_RETRIES + 2):
            try:
                jid = _submit(model, params, medias)
                log(f"  {label} attempt {a} -> {jid}")
                return jid
            except RuntimeError as e:
                log(f"  {label} submit error: {e}")
                if a > NSFW_RETRIES:
                    return None
        return None

    def wait_retry(jid, model, params, medias, label):
        for a in range(1, NSFW_RETRIES + 2):
            try:
                return _wait(jid, timeout=1800)
            except RuntimeError as e:
                if str(e).startswith("FILTERED:") and a <= NSFW_RETRIES:
                    log(f"  {label} {str(e).split(':')[1]} (uncharged) — retry {a}/{NSFW_RETRIES}")
                    jid = _submit(model, params, medias)
                    continue
                raise
        raise RuntimeError(f"{label}: exhausted retries")

    # talking cuts — all fresh from this run's script (NO reuse)
    for cm in sd["cuts"]:
        role, idx, text, dur = cm["role"], cm["idx"], cm["text"], cm["duration"]
        dest = out / f"cut{idx}_{role}.mp4"
        if role == "hook":
            model = "seedance_2_0"
            prompt = _prompt_gate(HOOK_TMPL.format(script=text, product_short=short), log=log)
            params = {"prompt": prompt, "aspect_ratio": "9:16", "resolution": "1080p",
                      "duration": dur, "mode": "std", "bitrate_mode": "high", "generate_audio": "true"}
            medias = [("image", st["stills"]["tryon_soft"])]
        else:
            model = "kling3_0"
            tmpl = WEARING_TMPL if role == "wearing" else POSE_TMPL
            prompt = _prompt_gate(tmpl.format(product_short=short, script=text), log=log)
            params = {"prompt": prompt, "aspect_ratio": "9:16", "duration": dur, "mode": "pro", "sound": "on"}
            medias = [("image", st["stills"]["tryon_soft"])]
        label = f"cut{idx} [{role}/{model}]"
        try:
            jid = submit_video(model, params, medias, label)
            if not jid:
                raise RuntimeError("submit failed after retries")
            url = wait_retry(jid, model, params, medias, label)
            vid = _download(url, dest)
            sheet = None if role == "hook" else _qc("video", vid, prods[:2], log=log)[0]
            st["cuts"].append({"path": str(vid), "role": role, "qc_sheet": sheet})
            log(f"  {label} DONE{' + QC' if sheet else ''}")
        except Exception as e:
            st["errors"].append(f"{label}: {e}")
            log(f"  {label} FAILED: {e}")

    # B-roll — 2 wearing (tryon_soft) + 2 POV (pov_temple_soft/pov_front_soft), fixed at 4 total
    for sc in SHOWCASE_SHOTS:
        still_key = sc["still"]
        if still_key not in st["stills"]:
            log(f"  broll [{sc['key']}] skipped — {still_key} was never generated (Stage 1 warning)")
            continue
        label = f"broll [{sc['key']}]"
        base = _SHOWCASE_BASE if sc["base"] == "wearing" else _POV_BROLL_BASE
        prompt = _prompt_gate(base.format(product_short=short) + sc["motion"], log=log)
        params = {"prompt": prompt, "aspect_ratio": "9:16", "duration": sc["duration"],
                  "mode": "pro", "sound": "off"}
        medias = [("image", st["stills"][still_key])]
        try:
            jid = submit_video("kling3_0", params, medias, label)
            if not jid:
                raise RuntimeError("submit failed after retries")
            url = wait_retry(jid, "kling3_0", params, medias, label)
            vid = _download(url, out / f"broll_{sc['key']}.mp4")
            sheet, _ = _qc("video", vid, prods[:2], log=log)
            st["brolls"].append({"path": str(vid), "kind": sc["key"], "qc_sheet": sheet})
            log(f"  {label} DONE + QC")
        except Exception as e:
            st["errors"].append(f"{label}: {e}")
            log(f"  {label} FAILED: {e}")
    return st


# ----------------------------------------------------------------- STAGE 3 (stitch + voice)
def run_stage_finish(st, log=print):
    out = Path(st["out"])
    ordered = sorted(st["cuts"], key=lambda c: Path(c["path"]).stem)
    if len(ordered) != len(st["script_data"]["cuts"]):
        raise RuntimeError("not all talking cuts exist — cannot stitch (see Stage-2 errors)")
    cut_paths = [c["path"] for c in ordered]
    # Rev 2.8 (2026-07-10): stitcher.plan_windows() now round-robins EVERY B-roll on a fixed ~3s
    # cadence instead of assigning named slots (hook_flash/hero_close/join_mask) to specific
    # kinds — so the old rotate/povrotate remap that only existed to feed those slots is gone.
    # Pass each B-roll's own kind straight through; stitcher.BROLL_IN keys match sc["key"] from
    # SHOWCASE_SHOTS directly (wearpose/catwalk/pov_temple/pov_front).
    brolls = [{"path": b["path"], "kind": b["kind"]} for b in st["brolls"]]

    # FINAL masters land in the PID folder per the per-PID standard: Ads/<PID>/final/
    # (working intermediates stay in _selfserve_th/). QC-passed masters only.
    final_dir = ROOT / "Ads" / st["pid"] / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    stitched = final_dir / f"TH_{st['pid']}_stitched.mp4"
    stitcher.stitch(cut_paths, brolls, stitched, out / "_stitch_work", log=log)

    voiced = final_dir / f"TH_{st['pid']}_{st['char']}_VOICED.mp4"
    try:
        st["final"] = voicer.run_voice_pass(ROOT, stitched, st["char"], st["script_data"]["script"],
                                            voiced, out / "_voice_work", log=log, group=st["group"])
    except Exception as e:
        st["errors"].append(f"voice pass: {e}")
        st["final"] = {"final": str(stitched), "voice": None,
                       "note": f"voice failed ({e}) — delivering stitched (engine voices)"}
        log(f"  voice pass FAILED: {e} — stitched file still available")
    st["final"]["stitched"] = str(stitched)
    log(f"  FINAL -> {st['final']['final']}")
    return st
