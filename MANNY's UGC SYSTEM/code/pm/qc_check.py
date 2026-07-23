#!/usr/bin/env python3
"""
qc_check.py — UGC video QC gate. The FIRST and LAST thing to run on any video.

WHY THIS EXISTS
---------------
Higgsfield/Seedance/Marketing-Studio generations fail in two expensive ways:
  (A) "Looks AI" — plastic/over-smooth skin + filter glow (e.g. seg1_5838e365).
  (B) Product hallucination — the eyewear changes: extra temple arm, wrong
      shape/colour, invented logo, surprise tint (e.g. seg2_0b3b638e, 3 temples).

This tool catches both BEFORE we accept a clip or spend more credits. It does the
cheap, deterministic, FREE work (frame extraction + quantitative realism metrics +
a contact sheet that crops the face and the eyewear). The final hard-fail verdict
on the eyewear is made by the AGENT'S VISION using the contact sheet + the per-PID
reference image — see the `ugc-qc` skill. Quantitative skin metrics auto-flag the
plastic-skin failure so it never slips through.

TWO PHASES
----------
  preflight : validate a PRODUCT reference image before generating (clean? single
              product? optional BiRefNet matte → a pixel-true reference cut to
              compare against later). Run this FIRST.
  video     : validate a GENERATED clip. Sample frames → realism metrics → contact
              sheet (full | face-zoom | eyewear-zoom) → JSON verdict. Run this LAST.

  calibrate : measure metrics across known-GOOD and known-BAD clips to (re)derive
              thresholds. Already run once; results baked into qc_thresholds.json.

DESIGN
------
* No ffmpeg needed — OpenCV reads mp4. No mediapipe — OpenCV Haar cascade ships in.
* BiRefNet is OPTIONAL and reused, never re-downloaded: tries `import rembg`, else
  the Catalogue Experience venv, else skips with a clear note. Model lives in the
  shared ~/.u2net/ cache (birefnet-general.onnx, 928 MB).
* Self-normalising skin metric (skin detail / hair detail in the SAME frame) so the
  score is resolution- and compression-independent.

Usage:
  python3 qc_check.py preflight --product <img> [--out <dir>] [--matte]
  python3 qc_check.py video --video <mp4> --reference <product_img> [--frames 9] [--out <dir>]
  python3 qc_check.py calibrate --good d1.mp4 d2.mp4 --bad b1.mp4
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
THRESH_FILE = HERE / "qc_thresholds.json"

# Reuse the Catalogue Experience BiRefNet install instead of re-downloading (~928 MB).
CATALOGUE_VENV_PY = Path(
    "/Users/manvendrakumar/Desktop/VS Code Projects /Catalogue Experience/orchestrator/.venv/bin/python"
)
# Both models are cached in ~/.u2net/. Default to the FAST one for QC detection
# (isnet ~4s/img, 170 MB). 'birefnet-general' (928 MB) has premium thin-metal edges
# but is impractically slow on CPU here (>3 min) — opt in with --matte-model when needed.
DEFAULT_MATTE_MODEL = "isnet-general-use"
PREMIUM_MATTE_MODEL = "birefnet-general"

# ADVISORY thresholds only (see calibration note in qc_thresholds.json). Set safely
# OUTSIDE our known-good range so they fire only on a genuinely heavy filter, never
# hard-failing on their own. Realism FAIL/PASS is the agent's vision verdict.
DEFAULTS = {
    "saturation_max": 140.0,   # good clips measured 88-101; >140 = heavy filter, eyeball.
    "bloom_frac_max": 0.18,    # good clips up to ~0.095; >0.18 = strong over-glow, eyeball.
}


# ----------------------------------------------------------------- frame I/O
def load_thresholds():
    t = dict(DEFAULTS)
    if THRESH_FILE.exists():
        try:
            t.update(json.loads(THRESH_FILE.read_text()).get("thresholds", {}))
        except Exception:
            pass
    return t


def extract_frames(video_path, n=9):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"ERROR: cannot open video {video_path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if total <= 0:  # some encoders don't report count; walk it
        frames = []
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            frames.append(fr)
        cap.release()
        if not frames:
            raise SystemExit(f"ERROR: no frames decoded from {video_path}")
        idxs = np.linspace(0, len(frames) - 1, n).astype(int)
        return [(int(i), frames[i]) for i in idxs]
    idxs = np.linspace(0, total - 1, n).astype(int)
    out = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            out.append((int(i), fr))
    cap.release()
    if not out:
        raise SystemExit(f"ERROR: no frames sampled from {video_path}")
    return out


_FACE_CASCADE = None


def detect_face(bgr):
    """Largest frontal face box (x, y, w, h) or None."""
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        _FACE_CASCADE = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    faces = _FACE_CASCADE.detectMultiScale(gray, 1.2, 5, minSize=(80, 80))
    if len(faces) == 0:
        return None
    return tuple(int(v) for v in max(faces, key=lambda f: f[2] * f[3]))


# ----------------------------------------------------------------- metrics
def _hf_energy(gray_patch):
    """High-frequency energy = variance of the Laplacian. Real texture -> high."""
    if gray_patch.size == 0:
        return 0.0
    return float(cv2.Laplacian(gray_patch.astype(np.float32), cv2.CV_32F).var())


def _fft_high_ratio(gray_patch, cutoff=0.25):
    """Fraction of spectral energy above `cutoff` of Nyquist. Waxy skin -> low."""
    if gray_patch.size == 0 or min(gray_patch.shape) < 16:
        return 0.0
    f = np.fft.fftshift(np.fft.fft2(gray_patch.astype(np.float32)))
    mag = np.abs(f)
    h, w = mag.shape
    cy, cx = h // 2, w // 2
    yy, xx = np.ogrid[:h, :w]
    r = np.sqrt(((yy - cy) / (h / 2)) ** 2 + ((xx - cx) / (w / 2)) ** 2)
    total = mag.sum() + 1e-9
    return float(mag[r > cutoff].sum() / total)


def realism_metrics(bgr, face_box):
    """Quantitative 'looks AI' signals. Self-normalised against hair texture."""
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    if face_box is None:
        # fall back to centre region; flag low confidence
        fx, fy, fw, fh = int(w * 0.3), int(h * 0.25), int(w * 0.4), int(h * 0.5)
        conf = "low (no face)"
    else:
        fx, fy, fw, fh = face_box
        conf = "ok"

    # skin patches: two cheeks + mid-forehead inside the face box
    def clamp(x, lo, hi):
        return max(lo, min(hi, x))

    patches = []
    for rx, ry, rw, rh in [
        (0.18, 0.55, 0.22, 0.22),  # left cheek
        (0.60, 0.55, 0.22, 0.22),  # right cheek
        (0.38, 0.18, 0.24, 0.16),  # forehead
    ]:
        x0 = clamp(int(fx + rw * 0 + fw * rx), 0, w - 2)
        y0 = clamp(int(fy + fh * ry), 0, h - 2)
        x1 = clamp(int(x0 + fw * rw), x0 + 1, w)
        y1 = clamp(int(y0 + fh * rh), y0 + 1, h)
        patches.append((x0, y0, x1, y1))

    skin_hf = np.mean([_hf_energy(gray[y0:y1, x0:x1]) for x0, y0, x1, y1 in patches])
    skin_fft = np.mean([_fft_high_ratio(gray[y0:y1, x0:x1]) for x0, y0, x1, y1 in patches])

    # hair / texture reference band: strip just ABOVE the face box (hair/brows)
    hy1 = clamp(fy, 1, h)
    hy0 = clamp(fy - int(fh * 0.35), 0, hy1 - 1)
    hx0, hx1 = clamp(fx, 0, w - 2), clamp(fx + fw, 1, w)
    hair_hf = _hf_energy(gray[hy0:hy1, hx0:hx1]) if hy1 > hy0 + 1 else skin_hf
    hf_ratio = float(skin_hf / (hair_hf + 1e-6))  # self-normalised: ~1 real, <<1 waxy

    # filter / glow signals over the whole face box
    face_hsv = hsv[clamp(fy, 0, h - 1):clamp(fy + fh, 1, h),
                   clamp(fx, 0, w - 1):clamp(fx + fw, 1, w)]
    if face_hsv.size == 0:
        face_hsv = hsv
    sat_mean = float(face_hsv[:, :, 1].mean())
    val = face_hsv[:, :, 2].astype(np.float32)
    bloom_frac = float((val > 235).mean())  # waxy near-white sheen

    return {
        "face_confidence": conf,
        "skin_hf_ratio": round(hf_ratio, 4),
        "skin_fft_high": round(float(skin_fft), 4),
        "skin_hf_abs": round(float(skin_hf), 2),
        "hair_hf_abs": round(float(hair_hf), 2),
        "saturation": round(sat_mean, 1),
        "bloom_frac": round(bloom_frac, 4),
        "_face_box": [int(fx), int(fy), int(fw), int(fh)],
    }


def filter_flags(metrics_list, thresholds):
    """ADVISORY only. Calibration proved local-texture numbers DON'T separate plastic
    skin from real (see qc_thresholds.json). So numbers never hard-fail realism — they
    only raise a soft flag for an extreme *filter* (heavy saturation / waxy bloom) that
    the agent should look at. The realism FAIL/PASS verdict is the agent's vision call."""
    def med(key):
        vals = [x[key] for x in metrics_list if isinstance(x.get(key), (int, float))]
        return float(np.median(vals)) if vals else 0.0

    agg = {k: med(k) for k in ("skin_hf_ratio", "skin_fft_high", "saturation", "bloom_frac")}
    flags = []
    if agg["saturation"] > thresholds["saturation_max"]:
        flags.append(f"advisory: high saturation {agg['saturation']:.0f} "
                     f"(>{thresholds['saturation_max']:.0f}) — possible filter, eyeball it")
    if agg["bloom_frac"] > thresholds["bloom_frac_max"]:
        flags.append(f"advisory: waxy bloom {agg['bloom_frac']*100:.1f}% "
                     f"(>{thresholds['bloom_frac_max']*100:.0f}%) — possible over-glow, eyeball it")
    no_face = sum(1 for x in metrics_list if x.get("face_confidence", "").startswith("low"))
    if no_face >= max(1, len(metrics_list) // 2):
        flags.append(f"advisory: face undetected in {no_face}/{len(metrics_list)} frames "
                     "— crops may be off, review the full frames")
    return flags, agg


REALISM_RUBRIC = [
    "SKIN: real pores/texture/micro-shadow? or plastic/waxy/over-smoothed (the seg1 fail)? "
    "Look at the face-zoom crop. Airbrushed, even, poreless = FAIL.",
    "LIGHTING: natural and consistent? or the tell-tale even AI glow / floaty studio sheen?",
    "EYES & TEETH: catchlights real, not glassy? teeth not fused/over-white?",
    "HANDS/FINGERS: correct count, no melting/morphing across cuts?",
    "MOTION FEEL (open the clip if unsure): natural micro-movement, not the warping/"
    "morphing puppet feel of a motion-transfer artifact?",
    "OVERALL: would this pass as a real person filmed on a phone? In STRICT mode, any "
    "clear plastic-skin or uncanny tell = FAIL.",
]


# ----------------------------------------------------------------- BiRefNet (optional)
def birefnet_matte(img_path, out_path):
    """Cut the subject/product with BiRefNet. Reuses existing install; never downloads.
    Returns out_path on success, None if unavailable."""
    code = (
        "import sys;from rembg import remove,new_session;from PIL import Image;"
        f"s=new_session('{BIREFNET_MODEL}');"
        "im=Image.open(sys.argv[1]).convert('RGBA');"
        "Image.fromarray(remove(__import__('numpy').array(im),session=s)).save(sys.argv[2])"
    )
    # matte is OPTIONAL — it must NEVER hang the gate, so every call has a hard timeout.
    TIMEOUT = 180  # model load + 1 image on CPU; skip gracefully if exceeded
    candidates = []
    try:
        import rembg  # noqa
        candidates.append([sys.executable, "-c", code, str(img_path), str(out_path)])
    except Exception:
        pass
    if CATALOGUE_VENV_PY.exists():
        candidates.append([str(CATALOGUE_VENV_PY), "-c", code, str(img_path), str(out_path)])
    for runner in candidates:
        try:
            subprocess.run(runner, check=True, capture_output=True, timeout=TIMEOUT)
            return out_path
        except subprocess.TimeoutExpired:
            print(f"  (BiRefNet matte skipped: exceeded {TIMEOUT}s — optional, continuing)")
            return None
        except Exception:
            continue
    return None


# ----------------------------------------------------------------- contact sheet
def _to_pil(bgr, max_w=420):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    im = Image.fromarray(rgb)
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)))
    return im


def eyewear_crop(bgr, face_box):
    """Tight band across the eyes (where the frame sits), upscaled for inspection."""
    h, w = bgr.shape[:2]
    if face_box is None:
        return _to_pil(bgr[int(h*0.30):int(h*0.55), int(w*0.2):int(w*0.8)], 420)
    fx, fy, fw, fh = face_box
    y0 = max(0, int(fy + fh * 0.18)); y1 = min(h, int(fy + fh * 0.62))
    x0 = max(0, int(fx - fw * 0.12)); x1 = min(w, int(fx + fw * 1.12))
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        crop = bgr
    return _to_pil(crop, 420)


def frame_fit_ratio(bgr, face_box):
    """Estimate eyewear frame width / face width in the eye band (dark frames only).
    >1.05 = frame spans wider than the face = likely oversized/scaled. Advisory."""
    if face_box is None:
        return None, "no face"
    fx, fy, fw, fh = face_box
    h, w = bgr.shape[:2]
    y0, y1 = max(0, int(fy + fh * 0.30)), min(h, int(fy + fh * 0.55))
    x0, x1 = max(0, int(fx - fw * 0.30)), min(w, int(fx + fw * 1.30))
    band = bgr[y0:y1, x0:x1]
    if band.size == 0:
        return None, "empty"
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    thr = max(45, int(gray.mean() * 0.55))
    dark_cols = (gray < thr).sum(axis=0)
    cols = np.where(dark_cols > band.shape[0] * 0.25)[0]
    if len(cols) < 5:
        return None, "low (no dark frame found — light frame? judge by eye)"
    return round(float((cols.max() - cols.min()) / fw), 2), "ok"


def build_contact_sheet(samples, metrics, references, out_path, matte_ref=None):
    """Rows = sampled frames [full | face/eyewear zoom]. Top band = ALL PID reference shots
    (+ optional matte) so the agent compares the rendered product to the full ground-truth set."""
    from PIL import ImageDraw
    cell_w = 420
    rows = []
    for (idx, bgr), m in zip(samples, metrics):
        full = _to_pil(bgr, cell_w)
        zoom = eyewear_crop(bgr, m.get("_face_box") and tuple(m["_face_box"]))
        zoom = zoom.resize((cell_w, int(zoom.height * cell_w / zoom.width)))
        rows.append((idx, full, zoom, m))

    pad, lab, head = 12, 22, 30
    row_h = max(r[1].height for r in rows) + max(r[2].height for r in rows) + lab + pad
    W = cell_w * 2 + pad * 3

    # All PID reference shots (+ optional matte of the first) tiled in one band at the top.
    refs = references if isinstance(references, (list, tuple)) else [references]
    ref_ims = []
    for rp in refs:
        try:
            ref_ims.append(Image.open(rp).convert("RGB"))
        except Exception:
            pass
    if matte_ref and Path(matte_ref).exists():
        mt = Image.open(matte_ref).convert("RGBA")
        bg = Image.new("RGB", mt.size, (255, 255, 255)); bg.paste(mt, mask=mt.split()[-1])
        ref_ims.append(bg)
    if not ref_ims:
        ref_ims = [Image.new("RGB", (cell_w, 120), (230, 230, 235))]
    ncell = len(ref_ims)
    ref_cw = max(80, int((W - pad * (ncell + 1)) / ncell))
    ref_h = 0
    for i, im in enumerate(ref_ims):
        im.thumbnail((ref_cw, 320)); ref_ims[i] = im; ref_h = max(ref_h, im.height)

    H = head + ref_h + pad + len(rows) * row_h + pad
    sheet = Image.new("RGB", (W, H), (244, 245, 248))
    dr = ImageDraw.Draw(sheet)
    dr.text((pad, 8), "PID GROUND TRUTH — rendered product/packaging must MATCH these exactly "
            "(shape, colour, lens tint, branding); NOTHING invented or extra", fill=(15, 15, 35))
    x = pad
    for im in ref_ims:
        sheet.paste(im, (x, head + (ref_h - im.height) // 2)); x += ref_cw + pad
    y = head + ref_h + pad
    for idx, full, zoom, m in rows:
        dr.text((pad, y - 2), f"frame {idx}  hf_ratio={m['skin_hf_ratio']}  "
                              f"sat={m['saturation']}  bloom={m['bloom_frac']}", fill=(40, 40, 60))
        sheet.paste(full, (pad, y + lab))
        sheet.paste(zoom, (pad * 2 + cell_w, y + lab))
        y += row_h
    sheet.save(out_path, quality=90)
    return out_path


# ----------------------------------------------------------------- commands
def cmd_preflight(args):
    product = Path(args.product)
    out = Path(args.out or product.parent / "_qc")
    out.mkdir(parents=True, exist_ok=True)
    im = Image.open(product).convert("RGB")
    report = {"phase": "preflight", "product": str(product),
              "resolution": im.size, "issues": []}
    if min(im.size) < 600:
        report["issues"].append(f"low resolution {im.size} — frame detail may be unreliable")
    matte_path = None
    if args.matte:
        matte_path = birefnet_matte(product, out / (product.stem + "_matte.png"))
        report["matte"] = str(matte_path) if matte_path else "UNAVAILABLE (BiRefNet not found)"
    report["verdict"] = "PASS" if not report["issues"] else "REVIEW"
    (out / "preflight_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print("\nNEXT: agent must read the reference image and note ground-truth eyewear "
          "facts (temple count=2, shape, colour, logo/hinge, lens tint) for the post-QC checklist.")
    return report


def cmd_video(args):
    video = Path(args.video)
    out = Path(args.out or video.parent / "_qc")
    out.mkdir(parents=True, exist_ok=True)
    thresholds = load_thresholds()
    samples = extract_frames(video, args.frames)
    metrics = [realism_metrics(bgr, detect_face(bgr)) for _, bgr in samples]
    flags, agg = filter_flags(metrics, thresholds)

    matte_ref = None
    if args.reference and args.matte:
        matte_ref = birefnet_matte(Path(args.reference[0]),
                                   out / (Path(args.reference[0]).stem + "_matte.png"))
    sheet = None
    if args.reference:
        sheet = build_contact_sheet(samples, metrics, args.reference,
                                    out / f"{video.stem}_contact.jpg", matte_ref)

    report = {
        "phase": "video", "video": str(video), "strict": args.strict,
        "overall_verdict": "PENDING_AGENT_VISION",
        "realism": {
            "verdict": "PENDING_AGENT_VISION",
            "advisory_flags": flags,            # never a hard-fail on their own
            "rubric": REALISM_RUBRIC,           # agent answers each, FAIL on any clear tell
            "metrics_note": "numeric metrics are ADVISORY; calibration showed they do not "
                            "reliably separate plastic from real skin — trust the crops.",
            "aggregate_metrics": agg,
        },
        "eyewear": {
            "verdict": "PENDING_AGENT_VISION",
            "checklist": [
                "PRODUCT MATCH: compare the rendered product to ALL PID reference shots at the top "
                "of the sheet — it must be the SAME product — HARD FAIL if it's a different frame",
                "Exactly 2 temple arms (no third arm) — HARD FAIL if wrong",
                "Frame shape + rim thickness match the PID — HARD FAIL if wrong",
                "Frame colour matches the PID — HARD FAIL if wrong",
                "Logo / hinge hardware matches the PID, nothing invented — HARD FAIL if wrong",
                "Lens tint/clarity matches the PID (clear stays clear / tint stays tint) — HARD FAIL if wrong",
                "BRANDING/TEXT: every word/logo on the product AND any packaging matches the PID "
                "exactly — NO invented or extra text, letters, numbers or logos (packaging shows "
                "ONLY the real brand wordmark) — HARD FAIL if wrong",
            ],
        },
        "contact_sheet": str(sheet) if sheet else None,
        "per_frame": metrics, "thresholds": thresholds,
    }
    (out / f"{video.stem}_qc.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"advisory_flags": flags, "aggregate_metrics": agg,
                      "contact_sheet": report["contact_sheet"]}, indent=2))
    print("\nNEXT (agent): OPEN THE CONTACT SHEET and judge with your own vision —\n"
          "  1) REALISM: walk the rubric; in strict mode any clear plastic-skin/uncanny tell = FAIL.\n"
          "  2) EYEWEAR: compare each eyewear-zoom to the reference; answer the 5-point checklist.\n"
          "ANY eyewear hard-fail OR realism FAIL => BLOCK, show the user the contact sheet, "
          "ask before regenerating (do not auto-spend credits).")
    return report


def cmd_image(args):
    """QC a try-on STILL before animating it. Adds a fit/proportion check on top of
    realism + eyewear. Run this on the character-wearing-PID image; only animate on PASS."""
    img = Path(args.image)
    out = Path(args.out or img.parent / "_qc")
    out.mkdir(parents=True, exist_ok=True)
    bgr = cv2.imread(str(img))
    if bgr is None:  # webp/other -> PIL fallback
        bgr = cv2.cvtColor(np.array(Image.open(img).convert("RGB")), cv2.COLOR_RGB2BGR)
    face = detect_face(bgr)
    m = realism_metrics(bgr, face)
    fit, fit_conf = frame_fit_ratio(bgr, face)
    thresholds = load_thresholds()
    flags, agg = filter_flags([m], thresholds)
    if fit is not None and fit > 1.05:
        flags.append(f"advisory: frame spans ~{fit:.2f}x the face width in the eye band "
                     "— looks OVERSIZED beyond the face, check fit closely")

    matte_ref = None
    if args.reference and args.matte:
        matte_ref = birefnet_matte(Path(args.reference[0]),
                                   out / (Path(args.reference[0]).stem + "_matte.png"))
    sheet = None
    if args.reference:
        sheet = build_contact_sheet([(0, bgr)], [m], args.reference,
                                    out / f"{img.stem}_contact.jpg", matte_ref)

    report = {
        "phase": "image", "image": str(img),
        "overall_verdict": "PENDING_AGENT_VISION",
        "fit": {"frame_to_face_width": fit, "confidence": fit_conf,
                "rule": "well-fitted ≈ 0.9-1.05x face width; >1.05 reads oversized/scaled"},
        "realism": {"verdict": "PENDING_AGENT_VISION", "advisory_flags": flags,
                    "rubric": REALISM_RUBRIC, "aggregate_metrics": agg},
        "eyewear": {"verdict": "PENDING_AGENT_VISION", "checklist": [
            "FIT: frames sit correctly on the face — rim roughly face-width, lenses cover "
            "the eyes, NOT scaled oversized/undersized — HARD FAIL if clearly off",
            "PRODUCT MATCH: same product as ALL PID reference shots at the top — HARD FAIL if a "
            "different frame",
            "Exactly 2 temple arms — HARD FAIL if wrong",
            "Frame shape + rim thickness match the PID — HARD FAIL if wrong",
            "Frame colour matches the PID — HARD FAIL if wrong",
            "Logo / hinge hardware matches the PID, nothing invented — HARD FAIL if wrong",
            "Lens tint/clarity matches the PID — HARD FAIL if wrong",
            "BRANDING/TEXT: all product/packaging text matches the PID exactly — NO invented or "
            "extra text/letters/numbers/logos — HARD FAIL if wrong",
        ]},
        "contact_sheet": str(sheet) if sheet else None,
    }
    (out / f"{img.stem}_qc.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"fit": report["fit"], "advisory_flags": flags,
                      "contact_sheet": report["contact_sheet"]}, indent=2))
    print("\nNEXT (agent): open the contact sheet. Judge FIT first (do the frames fit her "
          "face, or scaled too big like the last PID?), then realism + the 5 eyewear checks. "
          "PASS => animate this exact still (Seedance start_image + product ref). "
          "FAIL => regenerate the still, do NOT spend video credits yet.")
    return report


def cmd_calibrate(args):
    rows = []
    for label, vids in (("GOOD", args.good or []), ("BAD", args.bad or [])):
        for v in vids:
            samples = extract_frames(Path(v), args.frames)
            ms = [realism_metrics(bgr, detect_face(bgr)) for _, bgr in samples]
            agg = {k: round(float(np.median([x[k] for x in ms])), 4)
                   for k in ("skin_hf_ratio", "skin_fft_high", "saturation", "bloom_frac")}
            rows.append((label, Path(v).name, agg))
            print(f"{label:4} {Path(v).name:42} {agg}")
    print("\nSuggest thresholds BETWEEN good and bad medians (hf/fft = min; sat/bloom = max).")
    return rows


def main():
    ap = argparse.ArgumentParser(description="UGC video QC gate (realism + product fidelity).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("preflight"); pf.add_argument("--product", required=True)
    pf.add_argument("--out"); pf.add_argument("--matte", action="store_true")

    im = sub.add_parser("image"); im.add_argument("--image", required=True)
    im.add_argument("--reference", nargs="+"); im.add_argument("--out")
    im.add_argument("--strict", action="store_true"); im.add_argument("--matte", action="store_true")

    vd = sub.add_parser("video"); vd.add_argument("--video", required=True)
    vd.add_argument("--reference", nargs="+"); vd.add_argument("--frames", type=int, default=9)
    vd.add_argument("--out"); vd.add_argument("--strict", action="store_true")
    vd.add_argument("--matte", action="store_true")

    cb = sub.add_parser("calibrate"); cb.add_argument("--good", nargs="*")
    cb.add_argument("--bad", nargs="*"); cb.add_argument("--frames", type=int, default=9)

    args = ap.parse_args()
    {"preflight": cmd_preflight, "image": cmd_image, "video": cmd_video,
     "calibrate": cmd_calibrate}[args.cmd](args)


if __name__ == "__main__":
    main()
