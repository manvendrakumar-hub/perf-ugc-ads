#!/usr/bin/env python3
"""Product-modelling pipeline (A.3) for the self-serve tool. Zero Claude tokens.

Given PID + character + N: product images from `Stock PID Images/<PID>/` + the
character anchor from the Character Library ->
  1) gpt_image_2 try-on still (anchor + product)  -> QC image fit-gate
  2) seedance_2_0 x N (start_image=still + product ref) -> QC video each
Outputs land in `Ads/<PID>/_selfserve/`. All generation shells out to the
Higgsfield CLI (device-login). Importable: call run_modelling(...).
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path


def _find_data_root() -> Path:
    """Walk up from this file to find the UGC project root (has Stock PID Images + Character Library).
    Override with UGC_DATA_ROOT env var if auto-detect fails."""
    if "UGC_DATA_ROOT" in os.environ:
        return Path(os.environ["UGC_DATA_ROOT"])
    candidate = Path(__file__).resolve().parent
    for _ in range(8):
        if (candidate / "Stock PID Images").exists() and (candidate / "Character Library").exists():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        "Cannot find UGC project root (needs 'Stock PID Images/' + 'Character Library/').\n"
        "Fix: export UGC_DATA_ROOT='/path/to/Perf UGC Ads'"
    )


ROOT = _find_data_root()
HOME = Path.home()
ENV = dict(os.environ)
ENV["PATH"] = f"{HOME}/.local/node/bin:{HOME}/.local/bin:" + ENV.get("PATH", "")

STOCK = ROOT / "Stock PID Images"
CHAR_DIRS = [ROOT / "Character Library" / "Female Indian",
             ROOT / "Character Library" / "Female European",
             ROOT / "Character Library" / "Male"]
# QC script lives alongside this file in the same tool directory
QC = Path(__file__).resolve().parent / "qc_check.py"
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")

# Max auto-retries per take on nsfw/ip_detected (uncharged — retry freely)
NSFW_RETRIES = 3


# ----------------------------------------------------------------- registries
def list_characters():
    """[(char_id, anchor_path)] across the Character Library, sorted."""
    out = []
    for base in CHAR_DIRS:
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            anchors = sorted(d.glob("*_anchor.png")) or sorted(
                p for p in d.iterdir() if p.suffix.lower() in IMG_EXT)
            if anchors:
                out.append((d.name, anchors[0]))
    return out


def character_anchor(char_id):
    for cid, path in list_characters():
        if cid == char_id:
            return path
    return None


def product_images(pid):
    """Local product images for a PID: `Stock PID Images/<pid>/*` or `<pid>.<ext>`."""
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


# ----------------------------------------------------------------- HF CLI
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
        raise RuntimeError(f"submit {model}: no job id in response: {str(item)[:300]}")
    return jid


def _wait(job_id, timeout=1500, interval=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _hf("generate", "get", job_id, "--json")
        if r.returncode == 0:
            d = json.loads(r.stdout)
            it = d[0] if isinstance(d, list) and d else d
            st = it.get("status")
            if st == "completed":
                # video jobs: result_url; image jobs: results.rawUrl
                url = it.get("result_url") or (it.get("results") or {}).get("rawUrl")
                return url
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


def _qc(kind, target, references):
    """Run qc_check.py against ONE OR MORE PID reference images (product-match gate);
    return (contact_sheet_path | None, raw_json | None)."""
    refs = references if isinstance(references, (list, tuple)) else [references]
    cmd = ["python3", str(QC), kind, "--" + ("video" if kind == "video" else "image"),
           str(target), "--reference", *[str(r) for r in refs], "--strict"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=ENV)
    sheet = None
    m = re.search(r'"contact_sheet":\s*"([^"]+)"', r.stdout)
    if m:
        sheet = m.group(1)
    return sheet, r.stdout


def _split_products(prods):
    """(box_img | None, [glasses_imgs]) — a file whose name contains 'box' is the packaging."""
    box = next((p for p in prods if "box" in p.stem.lower()), None)
    glasses = [p for p in prods if p is not box]
    return box, glasses


def _tryon_still(anchor, product_front, preamble, out_path, log=print):
    """Generate a try-on still (gpt_image_2): character wearing the product.
    Returns local path or None on failure. Two attempts before giving up."""
    prompt = (
        preamble.rstrip() + " "
        "Medium front portrait of the character (from the reference) wearing the eyewear from "
        "the product reference. Frames sized correctly to fit her face — rim about face-width, "
        "lenses cover her eyes, not oversized. Keep the exact frame shape, colour, lens tint "
        "IDENTICAL to the product reference — do not alter the design. Natural skin texture "
        "with visible pores, fashion editorial look. No invented accessories, no text, no captions."
    )
    params = {"prompt": prompt, "aspect_ratio": "9:16", "quality": "high", "resolution": "2k"}
    medias = [("image", anchor), ("image", product_front)]
    for attempt in range(1, 3):
        try:
            jid = _submit("gpt_image_2", params, medias)
            log(f"  try-on still attempt {attempt} -> {jid}")
            url = _wait(jid, timeout=240, interval=5)
            if url:
                return _download(url, out_path)
        except Exception as e:
            log(f"  try-on still attempt {attempt} failed: {e}")
    return None


# ----------------------------------------------------------------- prompts
# Two engines, three rotating prompt variants each (variant rotates per take so N videos are
# intentionally diverse, not random stochastic repeats of the same instruction).
#   • Seedance 2.0 → true multishot editorial: 12 numbered moment prompts produce genuine
#     distinct cuts. V1 = balanced, V2 = ECU/product-beauty heavy, V3 = movement+action heavy.
#   • Kling 3.0   → continuous 15s clip (Kling Director Mode / Custom Storyboard that produces
#     real jump cuts is a UI-only feature not accessible via Higgsfield CLI). Three variants
#     explore: V1 = camera choreography, V2 = product ECU beauty, V3 = pose + expression.
# NSFW-safe: outdoor/boutique settings only (never grey studio), no brand names, medium
# framing — avoid "ECU from below"/"tight face" language. See a3-product-modelling-recipe-v2.

MODELS = ("seedance_2_0", "kling3_0")
MODEL_LABELS = {
    "seedance_2_0": "Seedance 2.0 — 10–12 rich editorial moments (natural skin)",
    "kling3_0": "Kling 3.0 — Dynamic continuous clip (varied camera + poses)",
}

# Shared eyewear-fidelity lock (the 147022 / 137974 lesson).
_LOCK = ("She wears the exact eyewear from the product reference — keep the frame shape, "
         "colour, rim and lenses IDENTICAL in every shot; never morph, warp, recolour, or "
         "add/remove parts. ")

# Seedance V1 — balanced editorial (poses + camera + light + gesture variety).
_SEEDANCE_V1 = (
    "She wears EXACTLY the same outfit, hair and accessories shown in the start-image — "
    "do NOT change clothing, hair colour, jewellery or skin tone between shots. " +
    _LOCK +
    "Real natural skin texture with visible pores, NOT airbrushed; fluid lifelike motion; "
    "premium fashion-campaign look. 12 distinct editorial shot moments, each a clear new "
    "camera setup or physical action with a crisp cut between them: "
    "[1] medium front, chin level, direct eye-contact; "
    "[2] cut closer, medium-close 3/4 right, chin slightly raised, shoulders back; "
    "[3] profile left, full frame silhouette visible, one hand resting at jaw; "
    "[4] she reaches up with two fingers and adjusts the temple arm; "
    "[5] cut — the eyewear bridge and lens rim catch the light, medium-close front; "
    "[6] she turns head from 3/4 left back to face camera with a composed breath; "
    "[7] cut wider to bust — weight shifts onto one hip, arms relaxed; "
    "[8] she sweeps a strand of hair off her shoulder then snaps eyes to camera; "
    "[9] over-the-shoulder glance back to the lens, slight chin lift; "
    "[10] low-angle medium — she looks slightly downward then raises her chin confidently; "
    "[11] chin drops then lifts into a slow, satisfied smile; "
    "[12] final medium front, shoulders square, looking straight into camera. "
    "Soft natural light, no on-screen text, no captions.")

# Seedance V2 — ECU + product beauty heavy (eyewear interaction is the hero).
_SEEDANCE_V2 = (
    "She wears EXACTLY the same outfit, hair and accessories shown in the start-image — "
    "do NOT change clothing, hair colour, jewellery or skin tone between shots. " +
    _LOCK +
    "Real natural skin texture with visible pores, NOT airbrushed; fluid lifelike motion; "
    "premium fashion-campaign look. 12 distinct editorial shot moments, each a clear new "
    "camera setup or action with a crisp cut between them: "
    "[1] medium front, direct gaze — frame clearly visible on her face; "
    "[2] she slowly removes the eyewear, holds it at arm's length toward camera; "
    "[3] she puts it back on with one hand, fingertips settling it on her nose bridge; "
    "[4] cut close — lens rim and bridge catch diffused light, medium-close portrait; "
    "[5] she turns 3/4 right — frame profile visible, temple arm detail at her cheek; "
    "[6] ECU on her face wearing the frame — lenses, bridge, natural skin visible; "
    "[7] she tilts head left — light rakes across the frame surface; "
    "[8] she pushes glasses up bridge with one fingertip — confident, deliberate; "
    "[9] she adjusts the temple arm with two fingers, then looks straight to camera; "
    "[10] medium front — she looks down at the frame then raises her chin, lenses flashing; "
    "[11] she looks right off-frame then snaps back — direct gaze through the lenses; "
    "[12] final medium front, wearing the frame confidently, straight into camera. "
    "Soft natural light, no on-screen text, no captions.")

# Seedance V3 — movement + dynamic action heavy (body range + gestures + walk-in energy).
_SEEDANCE_V3 = (
    "She wears EXACTLY the same outfit, hair and accessories shown in the start-image — "
    "do NOT change clothing, hair colour, jewellery or skin tone between shots. " +
    _LOCK +
    "Real natural skin texture with visible pores, NOT airbrushed; fluid lifelike motion; "
    "premium fashion-campaign look. 12 distinct editorial shot moments, each a clear new "
    "camera setup or action with a crisp cut between them: "
    "[1] wide — she walks a few steps into frame, stops, faces camera with natural momentum; "
    "[2] she turns 3/4 right — body rotation shows frame and profile together; "
    "[3] profile left — she pauses in full silhouette, one hand resting near jaw; "
    "[4] she turns back front, momentum carries a natural hair sweep; "
    "[5] medium-close — she steps forward slightly, fills the frame, direct gaze; "
    "[6] she pushes glasses up bridge with one finger and looks confidently to camera; "
    "[7] she tips chin down — eyes up, intense held gaze; "
    "[8] chin raises — proud tilt, weight shifting to one hip; "
    "[9] slow hair toss to one side, then she settles her gaze direct; "
    "[10] she crosses arms loosely — composed editorial pose, direct camera address; "
    "[11] she leans slightly forward toward camera, contained half-smile; "
    "[12] final — stands square, chin level, still and full confident gaze into camera. "
    "Soft natural light, no on-screen text, no captions.")

# Kling 3.0 — three 10-shot numbered variants (same format as validated Seedance multishot).
# Each shot = one concrete camera position OR model action OR product detail beat.
# Movement keywords woven in across all three: weight shifts, hair tosses, chin lifts,
# lean-in, step forward, arm/hand gestures, shoulder rolls, slow pivots.
# V1: camera choreography + balanced body movement.
_KLING_V1 = (
    "She wears EXACTLY the same outfit, hair and accessories shown in the start-image — "
    "do NOT change clothing, hair colour, jewellery or skin tone. " +
    _LOCK +
    "10 distinct editorial shot moments: "
    "[1] medium front, she stands tall, chin level, direct gaze to camera, shoulders rolled back; "
    "[2] she slowly rotates 30 degrees right, chin raised, shoulders drawing back with the turn; "
    "[3] camera moves closer — frame rim and lenses in sharp focus, soft bokeh behind her; "
    "[4] she raises one hand and adjusts the frame on her nose bridge, precise and deliberate; "
    "[5] full right profile — clean frame silhouette crisp, she holds an elegant composed pose; "
    "[6] she pivots back through 3/4 to face camera, hair catching the light as it settles; "
    "[7] camera pulls slightly wider — she shifts her weight to one hip, hand resting at her side; "
    "[8] she tosses her hair off one shoulder with a fluid sweep, snaps eyes back to camera; "
    "[9] camera drifts forward — lenses catching the warm raking light, bridge sharp; "
    "[10] final medium front — she steps forward slightly, shoulders square, full confident gaze. "
    "Real natural skin texture with visible pores, NOT airbrushed; soft natural light. "
    "No on-screen text, no captions.")

# V2: attitude angles + eyewear interaction (slides, pushes, over-shoulder, low-angle).
_KLING_V2 = (
    "She wears EXACTLY the same outfit, hair and accessories shown in the start-image — "
    "do NOT change clothing, hair colour, jewellery or skin tone. " +
    _LOCK +
    "10 distinct editorial shot moments: "
    "[1] medium wide — she stands relaxed, looking off-frame right, weight easy on one hip; "
    "[2] she slowly turns her gaze to camera, confident and direct, chin at level; "
    "[3] over-shoulder 3/4 — camera behind-right, she looks back toward us through the frame; "
    "[4] low-angle medium — camera below eye level, she looks down the lens, chin raised proud; "
    "[5] she lifts one hand and slides the sunglasses slightly down her nose, peers over the rim; "
    "[6] she pushes the sunglasses firmly back up with one finger, composed reset, direct gaze; "
    "[7] camera drifts to her side — hinge detail and temple arm in sharp focus, face in bokeh; "
    "[8] full left profile — clean frame silhouette against the background, jaw line strong; "
    "[9] she turns back almost front, shifts weight to other hip, a strand of hair settling; "
    "[10] final medium close-up — facing camera directly, lenses catching the light, composed. "
    "Real natural skin texture with visible pores, NOT airbrushed; soft natural light. "
    "No on-screen text, no captions.")

# V3: movement and expression variety (chin drops, lean-in, cross arms, finger-through-hair).
_KLING_V3 = (
    "She wears EXACTLY the same outfit, hair and accessories shown in the start-image — "
    "do NOT change clothing, hair colour, jewellery or skin tone. " +
    _LOCK +
    "10 distinct editorial shot moments: "
    "[1] 3/4 left — she gazes off-frame, frame catching the ambient light, relaxed open stance; "
    "[2] she turns naturally to face camera, unhurried, calm composed expression; "
    "[3] one hand lifts — she runs fingers lightly through her hair, then settles gaze forward; "
    "[4] she tilts chin up slightly, lenses catching the warm raking light, proud lift; "
    "[5] 3/4 right — she looks at an angle away from camera, weight shifted, easy open pose; "
    "[6] she turns back to front — both hands settle at her sides, a slow composed breath; "
    "[7] she reaches up and adjusts the temple arm with one deliberate finger, holds the gaze; "
    "[8] she tips chin down, eyes up — intense held gaze; then chin raises back tall and proud; "
    "[9] slight lean forward toward camera, weight on front foot, engaged direct energy; "
    "[10] final medium front — she stands square, chin level, still and full confident gaze. "
    "Real natural skin texture with visible pores, NOT airbrushed; soft natural light. "
    "No on-screen text, no captions.")


_KLING_VARIANTS = (_KLING_V1, _KLING_V2, _KLING_V3)
_SEEDANCE_VARIANTS = (_SEEDANCE_V1, _SEEDANCE_V2, _SEEDANCE_V3)


def _shots_for(model, take_idx=0):
    """Return the shot-block string for this model × take index (rotates 0→1→2→0…).
    Each take gets a distinct variant so N videos explore different emphases, not
    random stochastic repeats of the same instruction."""
    if model == "kling3_0":
        return _KLING_VARIANTS[take_idx % 3]
    return _SEEDANCE_VARIANTS[take_idx % 3]


# ----------------------------------------------------------------- QC prompt gate
_NSFW_SUBS = [
    (r"grey\s+seamless(?:\s+studio)?(?:\s+backdrop)?", "outdoor architectural wall"),
    (r"gray\s+seamless(?:\s+studio)?(?:\s+backdrop)?", "outdoor architectural wall"),
    (r"grey\s+studio", "boutique interior"),
    (r"gray\s+studio", "boutique interior"),
    (r"ECU\s+from\s+below", "low-angle close portrait"),
    (r"tight\s+ECU", "close portrait"),
    (r"tight\s+face", "close portrait"),
]
_BRAND_WARNS = [
    "lenskart", "vincent chase", "john jacobs", "aqualens", "meller",
    "oakley", "ray-ban", "ray ban", "rayban", "prada", "gucci", "dior",
]
_LOCK_MARKERS = ("frame shape", "identical", "do not alter", "keep the exact")
_PROMPT_CHAR_LIMIT = 2400  # below Kling's documented 2500-char hard cap


def _prompt_gate(prompt, model, log=print):
    """Validate + auto-fix a prompt before any credits are spent.
    Logs every change. Returns the safe-to-submit prompt string."""
    fixed = prompt

    # 1. Brand name warnings (can't safely auto-replace without context)
    for brand in _BRAND_WARNS:
        if brand.lower() in fixed.lower():
            log(f"  [GATE WARN] brand name '{brand}' — risk of ip_detected")

    # 2. NSFW / false-positive trigger replacement
    for pattern, replacement in _NSFW_SUBS:
        swapped = re.sub(pattern, replacement, fixed, flags=re.IGNORECASE)
        if swapped != fixed:
            log(f"  [GATE FIX] NSFW pattern removed → '{replacement}'")
            fixed = swapped

    # 3. Eyewear fidelity lock (must be present or QC gate can't verify fidelity)
    if not any(m.lower() in fixed.lower() for m in _LOCK_MARKERS):
        fixed = _LOCK + fixed
        log("  [GATE FIX] eyewear fidelity lock prepended (was missing)")

    # 4. Prompt length hard cap
    if len(fixed) > _PROMPT_CHAR_LIMIT:
        fixed = fixed[:_PROMPT_CHAR_LIMIT]
        log(f"  [GATE FIX] prompt truncated to {_PROMPT_CHAR_LIMIT} chars")

    return fixed


# A.3 SUB TYPE → VARIATION → scene preamble. A *variation* only swaps the SETTING/location;
# the multishot shot-block (10–12 Seedance / 18–20 Kling) is appended UNCHANGED, so every
# variation stays product-modelling + multishot in one 15s clip (user constraint 2026-06-22).
# Variations are built out manually over time — A3.3 (Studio) has none yet: the button exists,
# but the scene is intentionally NOT hardwired ("add the button, build it later", user 2026-06-22).
SUBTYPES = {
    "A3.1": {"label": "A3.1 — Indoor", "variations": {
        "Store":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, in a "
            "sunlit optician boutique / eyewear store interior with warm window light and "
            "soft bokeh shelves. ",
        "Café":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, inside a "
            "warm sunlit café with large windows, wooden tables, soft morning light streaming "
            "in and gentle bokeh of espresso cups and shelves in the background. ",
        "Home":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, in a bright "
            "lived-in home interior — warm painted walls, large natural-light windows, relaxed "
            "domestic atmosphere with a bookshelf and soft ambient light. ",
        "Dressing Room":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, in a stylish "
            "dressing room with a large lit vanity mirror, warm soft bulb lighting, and an "
            "elegant personal-styling atmosphere. ",
        "Hotel Lobby":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, inside a "
            "luxury hotel lobby with marble surfaces, tall polished columns, refracted light "
            "through large windows, and an upscale aspirational atmosphere. ",
        "Gallery":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, inside a "
            "minimalist white-walled contemporary art gallery with clean architectural lines, "
            "soft overhead diffused track lighting, and an art-adjacent premium atmosphere. ",
        "Neon Room":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, in a dark "
            "stylish room bathed in vivid neon and RGB ambient lighting — cool blues, electric "
            "purples and deep pinks — creating a bold Y2K maximalist fashion editorial atmosphere. ",
        "Brutalist":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, inside a raw "
            "exposed-concrete brutalist interior with hard directional daylight from a narrow "
            "window, sharp geometric shadows on bare concrete walls, bold architectural atmosphere. ",
        "Office":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, inside a "
            "modern open-plan office with clean desk surfaces, soft diffused overhead light, "
            "floor-to-ceiling windows with a city view beyond, polished professional atmosphere. ",
        "Warm Apartment":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, inside a "
            "cosy warm apartment with amber-toned lamps, textured plaster walls, a plush sofa "
            "and natural window light creating a soft intimate lived-in editorial atmosphere. ",
        "Car Interior":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, inside a "
            "sleek modern car interior — leather seats, sunroof or side window light streaming "
            "in — creating a stylish GRWM on-the-go editorial atmosphere. ",
    }},
    "A3.2": {"label": "A3.2 — Outdoor", "variations": {
        "Architecture":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, "
            "outdoors against a clean white architectural wall in bright diffused daylight. ",
        "Beach":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, on a calm "
            "sandy beach at golden hour — soft warm raking light, gentle surf and horizon "
            "visible behind, open coastal breeze, editorial seaside atmosphere. ",
        "Rooftop":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, on a stylish "
            "rooftop terrace at golden or blue hour with a panoramic city skyline behind, warm "
            "ambient city glow, polished aspirational urban editorial atmosphere. ",
        "Street":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, on an urban "
            "city street with large colourful graffiti murals on the walls behind, open diffused "
            "shade, youthful street-fashion energy. ",
        "Golden Hour Field":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, in an open "
            "field or meadow at golden hour — warm directional backlight, soft haze on the "
            "horizon, luminous backlit grass and a natural editorial atmosphere. ",
        "Café Terrace":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, on a shaded "
            "outdoor café terrace with iron bistro furniture, dappled shadow from an awning or "
            "overhead trees, relaxed Parisian street-café editorial atmosphere. ",
        "Botanical":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, in a lush "
            "botanical garden or tropical greenhouse — oversized green leaves, dappled diffused "
            "light filtering through the plant canopy, rich sensory editorial atmosphere. ",
        "Poolside":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, beside a "
            "sunlit outdoor pool — sparkling turquoise water visible behind, warm afternoon "
            "light, resort cabana and sun loungers, editorial poolside fashion atmosphere. ",
        "Blue Hour City":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, on a city "
            "street or bridge at blue hour — the sky a deep cobalt-violet gradient, city lights "
            "beginning to glow, cool-toned cinematic urban editorial atmosphere. ",
        "Graffiti Wall":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, standing "
            "directly in front of a large vivid graffiti mural on an urban wall, shot in open "
            "diffused shade, high-energy street-art editorial atmosphere. ",
        "Staircase":
            "Cinematic product-modelling fashion video, vertical 9:16, 15 seconds, on a dramatic "
            "architectural staircase — heritage stone steps or sleek modern concrete — strong "
            "geometric lines and natural sidelight casting bold shadows, editorial atmosphere. ",
    }},
    "A3.3": {"label": "A3.3 — Studio", "variations": {}},  # build variations later (user 2026-06-22)
}


def subtype_options():
    """[(subtype_key, label, [variation_names])] for the self-serve form dropdowns."""
    return [(k, v["label"], list(v["variations"].keys())) for k, v in SUBTYPES.items()]

# U2 — Unbox Modelling (indoor). Seedance only. Replicates Video ref/Unboxing video1.mp4:
# unbox → see → wear → style, as one multishot indoor clip. Refs = anchor + box + the EXACT
# product shot(s). Product/branding described by spec only (brand NAME kept OUT of the prompt to
# avoid Seedance ip_detected — the wordmark renders from the image refs); box constrained to its
# real wordmark with NO invented text (user 2026-06-22 feedback after the first Meller take).
_UNBOX_INDOOR = (
    "Cinematic UGC unboxing-and-styling video, vertical 9:16, 15 seconds, filmed selfie-style "
    "indoors in a real bright home with soft natural daylight. A real, natural-looking person "
    "(matching the character reference) unboxes and then models the sunglasses. "
    "PRODUCT — render the eyewear EXACTLY like the product reference images: glossy black chunky "
    "RECTANGULAR acetate sunglasses, dark blue-grey gradient tinted lenses, slim silver hinges, "
    "and the small gold brand wordmark on the temple arm; keep the shape, colour, lens tint and "
    "that wordmark identical in every shot — never morph, recolour, resize or restyle the frame. "
    "BOX — the orange branded box from the reference; show ONLY its existing brand wordmark and "
    "NOTHING else: do NOT add or invent any other text, words, letters, numbers or logos anywhere "
    "on the box or the product. "
    "Tell it as distinct shot moments with clear cuts following this arc: "
    "[1] she holds the closed orange box up near her face, excited reaction to camera; "
    "[2] cut — her hands open the box and slide out the inner sleeve; "
    "[3] cut — she lifts the folded black sunglasses out and holds them up, examining them; "
    "[4] cut — closer on the sunglasses in her hands, turning them, light catching the lenses and "
    "the gold temple wordmark; "
    "[5] cut — she unfolds the temples and brings the frame toward her face; "
    "[6] cut — she puts the sunglasses ON and settles them on the nose bridge with one finger; "
    "[7] cut — medium, she looks to camera now wearing them, confident happy smile; "
    "[8] cut — 3/4 turn showing the side profile of the frame and the gold temple wordmark; "
    "[9] cut — she adjusts the temple and flicks her hair, styling it; "
    "[10] cut — final hero medium, wearing the sunglasses, relaxed and delighted to camera. "
    "Real natural skin texture with visible pores, NOT airbrushed; fluid lifelike motion; candid "
    "iPhone-selfie energy; real-time normal speed, no slow motion. No on-screen text, no captions.")


# ----------------------------------------------------------------- per-model render params
def _submit_params(model, prompt):
    """Render params differ by engine (Seedance has resolution/bitrate; Kling has mode/sound)."""
    if model == "kling3_0":
        return {"prompt": prompt, "aspect_ratio": "9:16", "duration": 15,
                "mode": "pro", "sound": "off"}
    return {"prompt": prompt, "aspect_ratio": "9:16", "resolution": "1080p",
            "duration": 15, "mode": "std", "bitrate_mode": "high"}


# ----------------------------------------------------------------- REMIX (multi-PID / multi-outfit)
# Added 2026-07-14. A second Type alongside Product Modelling: a character cycles through
# 2-4 products (PIDs), each product rendered as its own short "chapter" clip, output
# organized per RUN (not per PID, since a run is multi-chapter by design) at
# `Ads/Remix/<run_name>/`. Validated live via direct Higgsfield calls before being ported
# here (see docs/memory + project plan for the full history):
#   - Stills engine is `nano_banana_2`, NOT `gpt_image_2` — nano_banana_2 is what holds real
#     iPhone-candid skin texture; gpt_image_2 reads too polished/AI for this recipe.
#   - Clothing is a real, selectable input here (ported from th-tool's clothing.json pattern)
#     — today's Product Modelling type has no clothing control at all, it just inherits
#     whatever the character's fixed anchor happens to be wearing.
#   - Kling's genuine multi-shot "Director Mode" (real jump cuts in ONE generation) is a
#     web-UI-only feature — confirmed via direct API testing (the `multi_shots`/`multi_prompt`
#     fields exist in the job schema but silently no-op through this API path). The reliable,
#     fully-automatable way to get real jump cuts is what's implemented below: generate several
#     short, DISTINCT Kling clips (different start/end still pairs) and hard-cut concatenate
#     them with ffmpeg — genuine editorial cuts, not hoped-for single-take interpolation.
#   - The CLI genuinely supports `--start-image` / `--end-image` as distinct flags (an older
#     internal doc claiming CLI-only-supports-`--image` was stale) — confirmed via
#     `higgsfield model get kling3_0` and a live test call.

CLOTHING = json.loads((Path(__file__).resolve().parent / "clothing.json").read_text())


def outfit_phrase(top_style, top_color, bottom_style, bottom_color):
    """Compose the 4 clothing.json dropdown picks into one outfit sentence fragment,
    exactly mirroring th-tool's outfit_phrase() pattern."""
    t = CLOTHING["tops"].get(top_style, next(iter(CLOTHING["tops"].values()))).format(color=top_color)
    b = CLOTHING["bottoms"].get(bottom_style, next(iter(CLOTHING["bottoms"].values()))).format(color=bottom_color)
    return f"{t} and {b}"


def _gen_nb2(prompt, medias, out_path, log=print, aspect_ratio="9:16"):
    """Generic nano_banana_2 still generator shared by every Remix still type.
    medias: ordered list of local image paths. Returns local path or None after 2 attempts."""
    params = {"prompt": prompt, "aspect_ratio": aspect_ratio}
    media_tuples = [("image", m) for m in medias]
    for attempt in range(1, 3):
        try:
            jid = _submit("nano_banana_2", params, media_tuples)
            log(f"  nano_banana_2 attempt {attempt} -> {jid}")
            url = _wait(jid, timeout=240, interval=5)
            if url:
                return _download(url, out_path)
        except Exception as e:
            log(f"  nano_banana_2 attempt {attempt} failed: {e}")
    return None


# ---- still prompts (validated 2026-07-14 on PIDs 245787 + 134220, character 39_Cafe_Aesthetic)
_REMIX_KIT_PROMPT = (
    "Editorial candid photo, natural daylight, medium shot from the waist up. The SAME "
    "person as in the reference image — keep her exact face, bone structure, skin tone, and "
    "hairstyle IDENTICAL; do NOT change her identity or beautify her. She has no eyewear on "
    "in this shot — completely bare-faced, remove any glasses from the reference photo. "
    "She is standing in {location}. She is wearing {outfit}, fully covered and brand-safe. "
    "Real candid skin texture with visible pores and a few flyaway hairs, no beauty filter, "
    "no HDR, photorealistic, shallow depth of field.")
_REMIX_DEFAULT_LOCATION = ("a bright, plant-filled café interior with warm wood tones and "
                            "large windows, soft natural window light")

_REMIX_TRYON_PROMPT = (
    "The SAME woman as in the first reference image — keep her exact face, hairstyle, "
    "outfit, pose, and location IDENTICAL to that reference. She is now wearing the eyewear "
    "shown in the second reference image, correctly sized to fit her face: frame width "
    "matching her face width, temples resting naturally over her ears, lenses fully "
    "covering her eyes — not oversized, not too small. Keep the EXACT frame shape, colour, "
    "and lens tint identical to the product reference image. Medium front-facing portrait "
    "from the chest up, looking directly at the camera, warm natural smile. No other "
    "changes to her appearance, outfit, or the background. Real candid skin texture with "
    "visible pores, no beauty filter, no HDR, photorealistic.")

# Required fix (validated, not optional): without the explicit hair-tuck clause, loose hair
# drapes over and hides the exact hinge detail this shot exists to show.
_REMIX_TEMPLE_ZOOM_PROMPT = (
    "The SAME woman, wearing the SAME eyewear, in the SAME outfit and location as the first "
    "reference image. She has turned her head to a 3/4 angle toward the camera, so the "
    "temple arm and hinge of her glasses are clearly visible and in sharp focus — a front "
    "pose would hide this detail, so the 3/4 angle is essential. Her hair is tucked behind "
    "her near ear and swept back off her face on that side — the temple arm, hinge, and ear "
    "are fully visible and NOT covered or draped by any hair. Match the temple/hinge "
    "hardware EXACTLY to the product reference image(s). Tighter framing than a medium "
    "shot, focused on her face and the eyewear temple detail, still in sharp focus. Real "
    "candid skin texture, no beauty filter, no HDR, photorealistic.")

# Required fix (validated, not optional): vague "tighter/closer" framing language measurably
# under-shot on a real test — barely moved the crop. Forceful explicit anchors are needed.
_REMIX_FRONT_CLOSEUP_PROMPT = (
    "Extreme close-up beauty shot of the SAME woman's face, wearing the SAME eyewear, same "
    "location softly out of focus behind her. Crop tight: her face fills most of the "
    "vertical frame, from the top of her hair to just below her chin — shoulders barely "
    "visible at the very bottom edge, NOT a chest-up shot. She faces the camera almost "
    "head-on, chin very slightly tilted down, both lenses and the full top of the frame "
    "clearly visible and in sharp focus. Keep the exact frame shape, colour, and lens tint "
    "identical to the product reference image(s). Real candid skin texture with visible "
    "pores, no beauty filter, no HDR, photorealistic.")


def _kit_frame(anchor, outfit, out_path, log=print, location=None):
    prompt = _REMIX_KIT_PROMPT.format(location=location or _REMIX_DEFAULT_LOCATION, outfit=outfit)
    return _gen_nb2(prompt, [anchor], out_path, log=log)


def _remix_tryon(kit_path, product_front, out_path, log=print):
    return _gen_nb2(_REMIX_TRYON_PROMPT, [kit_path, product_front], out_path, log=log)


def _remix_temple_zoom(tryon_path, product_refs, out_path, log=print):
    return _gen_nb2(_REMIX_TEMPLE_ZOOM_PROMPT, [tryon_path] + list(product_refs), out_path, log=log)


def _remix_front_closeup(tryon_path, product_refs, out_path, log=print):
    return _gen_nb2(_REMIX_FRONT_CLOSEUP_PROMPT, [tryon_path] + list(product_refs), out_path, log=log)


# ---- video shots (validated 2026-07-14: genuine start+end frame conditioning per shot,
# then hard-cut concat — NOT one long single-take generation, and NOT Kling's multi_shots
# flag, which was confirmed non-functional through this API path).
_REMIX_PUSHIN_PROMPT = (
    "Vertical 9:16 candid café UGC clip, natural daylight. She wears the exact eyewear "
    "shown in the reference images — keep the frame shape, colour and lens tint IDENTICAL, "
    "never morph the product. Camera pushes in steadily from a medium front shot to a "
    "close, warm portrait, she holds a natural relaxed smile the entire time, minimal head "
    "movement. Real candid skin texture, no beauty filter, no HDR.")
_REMIX_TEMPLE_TURN_PROMPT = (
    "Vertical 9:16 candid café UGC clip, natural daylight. She wears the exact eyewear "
    "shown in the reference images — keep the frame shape, colour and lens tint IDENTICAL, "
    "never morph the product. She smoothly turns her head from facing the camera to a 3/4 "
    "angle, hair tucked behind her near ear, the temple arm and hinge of the glasses coming "
    "clearly into view and sharp focus by the end. Real candid skin texture, no beauty "
    "filter, no HDR.")


def _remix_video_shot(start_img, end_img, prompt, out_path, log=print, duration=5):
    """One Kling 3.0 clip with genuine start+end frame conditioning (`--start-image` /
    `--end-image` — confirmed real CLI flags, not the older `--image`-only assumption).
    Returns local path or None."""
    params = {"prompt": prompt, "aspect_ratio": "9:16", "duration": duration,
              "mode": "pro", "sound": "off"}
    medias = [("start-image", start_img), ("end-image", end_img)]
    for attempt in range(1, NSFW_RETRIES + 2):
        try:
            jid = _submit("kling3_0", params, medias)
            log(f"  Remix video shot attempt {attempt} -> {jid}")
            url = _wait(jid, timeout=1800)
            if url:
                return _download(url, out_path)
        except RuntimeError as e:
            err = str(e)
            if err.startswith("FILTERED:") and attempt <= NSFW_RETRIES:
                log(f"  Remix video shot {err} (uncharged) — retrying {attempt}/{NSFW_RETRIES}")
                continue
            log(f"  Remix video shot attempt {attempt} failed: {e}")
    return None


def _concat_hardcut(clip_paths, out_path, log=print):
    """Hard-cut concat (no crossfade) — validated recipe: scale+setsar-normalize every clip,
    then ffmpeg's concat filter. Returns local path or None."""
    if not clip_paths:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if len(clip_paths) == 1:
        shutil.copy2(clip_paths[0], out_path)
        return out_path
    inputs, filt = [], ""
    for i, p in enumerate(clip_paths):
        inputs += ["-i", str(p)]
        filt += f"[{i}:v]scale=1080:1920,setsar=1[v{i}];"
    filt += "".join(f"[v{i}]" for i in range(len(clip_paths))) + \
        f"concat=n={len(clip_paths)}:v=1:a=0[outv]"
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", *inputs, "-filter_complex", filt, "-map", "[outv]",
             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out_path)],
            capture_output=True, text=True, env=ENV, timeout=180)
        if r.returncode == 0 and out_path.exists():
            return out_path
        log(f"  concat failed: {(r.stderr or '')[-300:]}")
    except Exception as e:
        log(f"  concat error: {e}")
    return None


def run_remix(pids, char_id, top_style=None, top_color=None, bottom_style=None,
              bottom_color=None, run_name=None, log=print):
    """Remix Milestones 1+2: ONE shared kit (character + outfit, no product) -> per-PID
    ("chapter") tryon/temple_zoom/front_closeup stills -> 2x Kling 5s shots (push-in, then
    turn-to-temple) -> hard-cut concat into one chapter video per PID.
    Output: `Ads/Remix/<run_name>/00_kit_frame_<char>.png` + `<PID>/` per chapter — NOT the
    `_selfserve/` per-PID convention Product Modelling uses, since a Remix run is
    multi-chapter by design and needs everything reviewable together.
    Cap: 2-4 PIDs. Cross-chapter stitching (transitions/title cards joining PID A's chapter
    to PID B's) is a separate, later milestone — this returns one clip PER chapter."""
    pids = [str(p).strip() for p in pids if str(p).strip()]
    if not (2 <= len(pids) <= 4):
        raise ValueError(f"Remix needs 2-4 PIDs, got {len(pids)}")

    d = CLOTHING["_defaults"]
    top_style = top_style or d["top_style"]
    top_color = top_color or d["top_color"]
    bottom_style = bottom_style or d["bottom_style"]
    bottom_color = bottom_color or d["bottom_color"]
    outfit = outfit_phrase(top_style, top_color, bottom_style, bottom_color)

    run_name = (run_name or "Video_1_test").strip().replace("/", "_")
    out = ROOT / "Ads" / "Remix" / run_name
    out.mkdir(parents=True, exist_ok=True)

    anchor = character_anchor(char_id)
    if not anchor:
        raise FileNotFoundError(f"No anchor for character '{char_id}'")

    res = {"run_name": run_name, "character": char_id, "outfit": outfit, "pids": pids,
           "kit_frame": None, "chapters": [], "errors": []}
    log(f"Remix run '{run_name}' | {char_id} | outfit: {outfit} | chapters: {', '.join(pids)}")

    kit_path = _kit_frame(anchor, outfit, out / f"00_kit_frame_{char_id}.png", log=log)
    if not kit_path:
        raise RuntimeError("kit_frame generation failed after retries — cannot continue")
    res["kit_frame"] = str(kit_path)
    log(f"kit_frame DONE -> {kit_path.name}")

    for pid in pids:
        chapter = {"pid": pid, "tryon": None, "temple_zoom": None, "front_closeup": None,
                   "video": None}
        try:
            prods = product_images(pid)
            if not prods:
                raise FileNotFoundError(f"No product images in 'Stock PID Images/{pid}/'")
            cdir = out / pid
            cdir.mkdir(parents=True, exist_ok=True)

            tryon = _remix_tryon(kit_path, prods[0], cdir / "01_tryon.png", log=log)
            if not tryon:
                raise RuntimeError("tryon still failed after retries")
            chapter["tryon"] = str(tryon)

            temple = _remix_temple_zoom(tryon, prods[:4], cdir / "02_temple_zoom.png", log=log)
            front_cu = _remix_front_closeup(tryon, prods[:4], cdir / "03_front_closeup.png", log=log)
            chapter["temple_zoom"] = str(temple) if temple else None
            chapter["front_closeup"] = str(front_cu) if front_cu else None
            log(f"[{pid}] stills DONE (temple_zoom={'ok' if temple else 'FAILED'}, "
                f"front_closeup={'ok' if front_cu else 'FAILED'})")

            if temple and front_cu:
                shot_a = _remix_video_shot(tryon, front_cu, _REMIX_PUSHIN_PROMPT,
                                           cdir / "_shot_a_pushin.mp4", log=log)
                shot_b = _remix_video_shot(front_cu, temple, _REMIX_TEMPLE_TURN_PROMPT,
                                           cdir / "_shot_b_temple.mp4", log=log)
                clips = [c for c in (shot_a, shot_b) if c]
                if clips:
                    video = _concat_hardcut(clips, cdir / f"{pid}_chapter.mp4", log=log)
                    chapter["video"] = str(video) if video else None
                    log(f"[{pid}] chapter video {'DONE' if video else 'FAILED (concat)'}")
                else:
                    log(f"[{pid}] chapter video SKIPPED — both shot generations failed")
            else:
                log(f"[{pid}] chapter video SKIPPED — missing temple_zoom or front_closeup still")
        except Exception as e:
            res["errors"].append(f"[{pid}]: {e}")
            log(f"[{pid}] FAILED: {e}")
        res["chapters"].append(chapter)

    # Milestone 3: join every completed chapter into ONE final compilation — same hard-cut
    # concat technique already validated within each chapter (no crossfade, matches the
    # reference videos' jump-cut energy). Title cards / branded end-card are NOT built yet —
    # this is a clean hard-cut join only.
    chapter_videos = [c["video"] for c in res["chapters"] if c.get("video")]
    if len(chapter_videos) >= 2:
        final_video = _concat_hardcut(chapter_videos, out / "final_compilation.mp4", log=log)
        res["final_video"] = str(final_video) if final_video else None
        log(f"final_compilation {'DONE' if final_video else 'FAILED (concat)'} "
            f"({len(chapter_videos)} chapters joined)")
    else:
        res["final_video"] = None
        log(f"final_compilation SKIPPED — only {len(chapter_videos)} chapter video(s) available, need 2+")

    log("Remix run complete.")
    return res


# ----------------------------------------------------------------- orchestration
def run_modelling(pid, char_id, n_videos=2, kind="product_modelling",
                  model="seedance_2_0", subtype="A3.1", variation=None, log=print):
    """kind: 'product_modelling' (A.3 — sub type × variation × selected model) or
    'unbox_modelling_indoor' (U2, CLI-only; not exposed in the PM tool).
    model: 'seedance_2_0' (10–12 rich) or 'kling3_0' (18–20 cuts) — ignored for U2.
    subtype/variation: A.3 location selectors; N videos = N takes of the SAME selection."""
    pid = str(pid).strip()
    if model not in MODELS:
        model = "seedance_2_0"
    out = ROOT / "Ads" / pid / "_selfserve"
    out.mkdir(parents=True, exist_ok=True)
    res = {"pid": pid, "character": char_id, "kind": kind, "model": model,
           "subtype": subtype, "variation": variation,
           "still": None, "still_sheet": None, "videos": [], "errors": []}

    prods = product_images(pid)
    if not prods:
        raise FileNotFoundError(f"No product images in 'Stock PID Images/{pid}/'")
    anchor = character_anchor(char_id)
    if not anchor:
        raise FileNotFoundError(f"No anchor for character '{char_id}'")

    # Build the list of takes: (idx, label, prompt) + the shared media refs + QC refs for this kind.
    if kind == "unbox_modelling_indoor":
        model = "seedance_2_0"  # U2 is locked to Seedance (natural model + product)
        res["model"] = model
        n = max(1, min(int(n_videos), 3))
        box, glasses = _split_products(prods)
        hero = glasses[0] if glasses else prods[0]            # exact studio shot drives fidelity
        gen_refs = [anchor] + ([box] if box else []) + [hero]  # identity + box + hero glasses
        medias = [("image", r) for r in gen_refs]
        qc_refs = ([box] if box else []) + glasses[:2]         # match box + exact glasses vs PID
        specs = [(i, "indoor", _UNBOX_INDOOR) for i in range(1, n + 1)]  # N motion variations
        log(f"U2 Unbox-Modelling (indoor) | gen refs: {', '.join(p.name for p in gen_refs)} | "
            f"QC vs PID: {', '.join(p.name for p in qc_refs)} | {char_id} | Seedance | {n} take(s)")
    else:
        subt = SUBTYPES.get(subtype) or SUBTYPES["A3.1"]
        vmap = subt["variations"]
        if not vmap:
            raise ValueError(f"{subtype} ({subt['label']}) has no variations built yet — "
                             f"add one to SUBTYPES in modelling.py before running it.")
        variation = variation if variation in vmap else next(iter(vmap))
        res["variation"] = variation
        preamble = vmap[variation]
        n = max(1, min(int(n_videos), 4))
        label = f"{subtype}_{variation}".replace(" ", "")
        # Each take i gets a distinct shot-block variant (i-1 → 0,1,2,0,1,2…) so the
        # N videos are intentionally diverse rather than random stochastic repeats.
        specs = [(i, label, preamble + _shots_for(model, i - 1)) for i in range(1, n + 1)]
        dens = "18–20 cut" if model == "kling3_0" else "10–12 moment"
        log(f"product: {prods[0].name} | {char_id} | {model} | {subtype}/{variation} | "
            f"{n} take(s) × {dens} multishot (same model · PID · variation)")

        # IMAGE-FIRST: try-on still locks the product onto the character before video spend.
        # Kling cannot accept kling_element_ids via CLI → still-as-start-image is the fix.
        # Seedance: still + product refs gives both identity lock and product fidelity.
        still = _tryon_still(anchor, prods[0], preamble,
                             out / "_stills" / f"still_{label}.jpg", log=log)
        if still:
            res["still"] = str(still)
            vsheet_s, _ = _qc("image", still, prods[:2])
            res["still_sheet"] = vsheet_s
            log(f"try-on still DONE | QC: {Path(vsheet_s).name if vsheet_s else 'none'}")
        else:
            log("try-on still FAILED — falling back to raw anchor")

        if still and model == "kling3_0":
            medias = [("image", still)]                              # glasses baked into first frame
        elif still:
            medias = [("image", still)]  # still has product baked in; Seedance accepts 1 start_image
        elif model == "kling3_0":
            medias = [("image", anchor)]                             # Kling: one start_image only
        else:
            # Seedance fallback (try-on still failed): send ONLY the anchor as the single
            # start_image. Seedance's CLI maps every --image to the start_image role and rejects
            # more than one ("'medias' can contain at most one start_image"), so anchor + product
            # refs together fail. Product fidelity here leans on the eyewear-lock text in the
            # prompt; injecting a product ref would need a distinct media role in _submit.
            medias = [("image", anchor)]

        qc_refs = prods[:2] if len(prods) >= 2 else prods

    # Submit all takes, then poll all with NSFW auto-retry (parallel inner loop).
    jobs = []
    for idx, label, prompt in specs:
        prompt = _prompt_gate(prompt, model, log=log)
        params = _submit_params(model, prompt)
        # Submit with NSFW auto-retry (uncharged retries — no credit cost)
        jid = None
        for attempt in range(1, NSFW_RETRIES + 2):
            try:
                jid = _submit(model, params, medias)
                log(f"  take {idx} [{label}] attempt {attempt} -> {jid}")
                break
            except RuntimeError as e:
                log(f"  take {idx} [{label}] submit error: {e}")
                if attempt > NSFW_RETRIES:
                    res["errors"].append(f"take {idx} [{label}]: submit failed after {attempt} attempts")
                    jid = None
                    break
        if jid:
            jobs.append((idx, label, jid))
        time.sleep(1)

    for idx, label, jid in jobs:
        try:
            url = None
            for attempt in range(1, NSFW_RETRIES + 2):
                try:
                    url = _wait(jid, timeout=1800)
                    break
                except RuntimeError as e:
                    err = str(e)
                    if err.startswith("FILTERED:"):
                        filter_type = err.split(":")[1]
                        log(f"  take {idx} [{label}] {filter_type} (uncharged) — retrying {attempt}/{NSFW_RETRIES}")
                        if attempt <= NSFW_RETRIES:
                            # Resubmit the same take
                            prompt = _prompt_gate(_shots_for(model, idx - 1), model, log=log)
                            jid = _submit(model, _submit_params(model, prompt), medias)
                            log(f"  take {idx} [{label}] retry job -> {jid}")
                            continue
                    raise
            if not url:
                raise RuntimeError(f"take {idx} exhausted {NSFW_RETRIES} NSFW retries")
            vid = _download(url, out / f"{kind}_take{idx}_{label}.mp4")
            vsheet, _ = _qc("video", vid, qc_refs)
            res["videos"].append({"path": str(vid), "sheet": vsheet, "take": idx, "scene": label})
            log(f"take {idx} [{label}] DONE + QC")
        except Exception as e:
            res["errors"].append(f"take {idx} [{label}]: {e}")
            log(f"take {idx} [{label}] FAILED: {e}")

    log("complete.")
    return res


if __name__ == "__main__":
    import sys
    pid = sys.argv[1] if len(sys.argv) > 1 else "206041"
    char = sys.argv[2] if len(sys.argv) > 2 else "F07_purple"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    kind = sys.argv[4] if len(sys.argv) > 4 else "product_modelling"
    model = sys.argv[5] if len(sys.argv) > 5 else "seedance_2_0"
    subtype = sys.argv[6] if len(sys.argv) > 6 else "A3.1"
    variation = sys.argv[7] if len(sys.argv) > 7 else None
    print(json.dumps(run_modelling(pid, char, n, kind, model, subtype, variation), indent=2))
