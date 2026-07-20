#!/usr/bin/env python3
"""TH Tool (A.1 Talking Head) — local web app, staged flow, 2 gates.  (rebuilt 2026-07-04)

Run:  python3 app.py    → http://127.0.0.1:7861   (pm-tool owns :7860)
⚠️ debug=False → NO auto-reload: RESTART the server after ANY code edit.
Flow: form → Stage 1 (script + kit/try-on stills) → GATE 1 (review/edit script) →
      Stage 2 (fresh cuts + natural B-roll) → GATE 2 → Stage 3 (stitch + voice).
"""
import threading
import uuid
from pathlib import Path

from flask import Flask, abort, redirect, render_template_string, request, send_file, url_for

import scripting
import th_pipeline as P

ROOT = P.ROOT
app = Flask(__name__)
JOBS = {}

CSS = """<style>body{font:15px/1.5 -apple-system,system-ui,sans-serif;max-width:940px;margin:30px auto;padding:0 16px;color:#1a1a2e}
h1{font-size:20px}label{display:block;margin:14px 0 4px;font-weight:600}
input,select,textarea{width:100%;padding:10px;border:1px solid #ccc;border-radius:8px;font-size:15px;box-sizing:border-box}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
button{margin-top:18px;padding:12px 20px;background:#1a1a2e;color:#fff;border:0;border-radius:8px;font-size:15px;cursor:pointer}
.hint{color:#777;font-size:13px;margin-top:4px}.warn{background:#fff3cd;padding:10px;border-radius:8px;margin:8px 0;font-size:14px}
.s{padding:4px 10px;border-radius:6px;font-weight:600;font-size:13px}
.running{background:#fff3cd}.gate{background:#cfe2ff}.done{background:#d1e7dd}.error{background:#f8d7da}
pre{background:#0d1117;color:#c9d1d9;padding:12px;border-radius:8px;overflow:auto;font-size:12px;max-height:260px}
.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px}
video,img{width:100%;border-radius:10px;border:1px solid #ddd}.card{border:1px solid #eee;border-radius:12px;padding:10px;font-size:13px}
a{color:#1a1a2e}</style>"""

FORM = """<!doctype html><html><head><title>TH Studio</title>""" + CSS + """</head><body>
<h1>🎬 UGC Talking-Head Studio (A.1) &middot; premium</h1>
<form method="post" action="{{ url_for('run') }}">
  <label>PID (premium product)</label>
  <select name="pid">{% for p in pids %}<option>{{p}}</option>{% endfor %}</select>
  <label>Character</label>
  <select name="char">{% for cid,grp in chars %}<option value="{{cid}}">{{cid}} &nbsp;·&nbsp; {{grp}}</option>{% endfor %}</select>
  <div class="hint">Full library — the kit frame is generated live from the anchor (identity holds)</div>
  <div class="row">
    <div><label>Top style</label><select name="top_style">{% for t in tops %}<option>{{t}}</option>{% endfor %}</select></div>
    <div><label>Top color</label><select name="top_color">{% for c in top_colors %}<option>{{c}}</option>{% endfor %}</select></div>
  </div>
  <div class="row">
    <div><label>Bottom style</label><select name="bottom_style">{% for b in bottoms %}<option>{{b}}</option>{% endfor %}</select></div>
    <div><label>Bottom color</label><select name="bottom_color">{% for c in bottom_colors %}<option>{{c}}</option>{% endfor %}</select></div>
  </div>
  <label>Location / environment</label>
  <select name="location">{% for l in locations %}<option>{{l}}</option>{% endfor %}</select>
  <label>Script mode</label>
  <select name="script_mode">
    <option value="manual" selected>Manual — Claude Pattern-1 (Celebrity Interruption), editable at Gate 1</option>
    <option value="auto">Auto — randomized Pattern-2 (Direct Hook Testimonial)</option>
  </select>
  <div class="hint">Auto mixes hook/opener/middle/close from `Talking head scripts..pdf`'s format — shorter, names Lens Kart directly, no celebrity bridge. Still editable at Gate 1 either way.</div>
  <button type="submit">Start — Stage 1: script + stills (cheap)</button>
</form>
<p class="hint">Stage 1 ≈ script + ~2 Nano-Banana images · Gate 1 approve · Stage 2 ≈ 3 cuts + 4 B-rolls · Gate 2 approve · Stage 3 stitch + voice</p>
</body></html>"""

JOB = """<!doctype html><html><head><title>TH {{jid[:8]}}</title>
{% if 'running' in status or status=='finishing' %}<meta http-equiv="refresh" content="7">{% endif %}
""" + CSS + """</head><body>
<p><a href="{{ url_for('index') }}">← new job</a></p>
<h1>PID {{j.pid}} · {{j.char}} <span class="s {{'gate' if 'gate' in status else status if status in ('done','error') else 'running'}}">{{status}}</span></h1>
<pre>{{ '\\n'.join(j.log[-40:]) }}</pre>
{% if j.st and j.st.warnings %}{% for w in j.st.warnings %}<div class="warn">⚠️ {{w}}</div>{% endfor %}{% endif %}

{% if status=='gate1' %}
  <h3>Gate 1 — review script &amp; stills, then approve Stage 2 (video spend)</h3>
  <form method="post" action="{{ url_for('approve1', jid=jid) }}">
    <label>Script (editable — re-splits on approve · "Lens Kart" · no real names · no city)</label>
    <textarea name="script" rows="7">{{ j.st.script_data.script }}</textarea>
    <div class="hint">mode: {{ j.st.script_mode }} · {{ j.st.script_data.cuts|length }} cuts · lane {{ j.st.script_data.lane }} · product {{ j.st.script_data.product_short }} · outfit: {{ j.st.outfit }} · {{ j.st.location }}</div>
    <button type="submit">Approve → Stage 2: generate videos</button>
  </form>
  <div class="grid">
  {% for name,p in j.st.stills.items() if p and not name.endswith('_sheet') and not name.endswith('_soft') %}
    <div class="card"><b>{{name}}</b><br><img src="{{ url_for('media') }}?p={{p}}"></div>
  {% endfor %}</div>
  {% if j.st.stills.tryon_qc_sheet %}<p><a href="{{ url_for('media') }}?p={{j.st.stills.tryon_qc_sheet}}">try-on QC sheet ↗</a></p>{% endif %}
{% endif %}

{% if status=='gate2' %}
  <h3>Gate 2 — review clips, then approve stitch + voice</h3>
  <form method="post" action="{{ url_for('approve2', jid=jid) }}"><button type="submit">Approve → Stage 3: stitch + voice</button></form>
  <h4>Talking cuts</h4><div class="grid2">
  {% for c in j.st.cuts %}<div class="card"><b>{{c.role}}</b><br><video controls src="{{ url_for('media') }}?p={{c.path}}"></video>
    {% if c.qc_sheet %}<a href="{{ url_for('media') }}?p={{c.qc_sheet}}">QC ↗</a>{% endif %}</div>{% endfor %}</div>
  <h4>B-roll (natural wearing)</h4><div class="grid2">
  {% for b in j.st.brolls %}<div class="card"><b>{{b.kind}}</b><br><video controls src="{{ url_for('media') }}?p={{b.path}}"></video>
    {% if b.qc_sheet %}<a href="{{ url_for('media') }}?p={{b.qc_sheet}}">QC ↗</a>{% endif %}</div>{% endfor %}</div>
  {% if j.st.errors %}<h4>Errors</h4><pre>{{ '\\n'.join(j.st.errors) }}</pre>{% endif %}
{% endif %}

{% if status=='done' %}
  <h3>✅ Final</h3>
  <video controls style="max-width:420px" src="{{ url_for('media') }}?p={{j.st.final.final}}"></video>
  <p>voice: {{ j.st.final.voice }}{% if j.st.final.drift_ms is not none %} · lip-sync drift {{j.st.final.drift_ms}}ms ({{j.st.final.aligned_words}} words){% endif %}</p>
  <p class="hint">{{ j.st.final.final }}</p>
  {% if j.st.errors %}<h4>Notes</h4><pre>{{ '\\n'.join(j.st.errors) }}</pre>{% endif %}
{% endif %}
</body></html>"""


def _logger(j):
    return lambda m: j["log"].append(str(m))


def _run_stage(jid, fn, next_status):
    j = JOBS[jid]
    try:
        j["st"] = fn(j["st"], log=_logger(j)) if j["st"] else fn(log=_logger(j))
        j["status"] = next_status
    except Exception as e:
        j["status"] = "error"
        j["log"].append("ERROR: " + str(e))


@app.route("/")
def index():
    chars = [(cid, grp) for cid, _a, grp in P.list_characters()]
    return render_template_string(
        FORM, pids=P.list_pids(), chars=chars, locations=list(P.LOCATIONS),
        tops=list(P.CLOTHING["tops"]), bottoms=list(P.CLOTHING["bottoms"]),
        top_colors=P.CLOTHING["top_colors"], bottom_colors=P.CLOTHING["bottom_colors"])


@app.route("/run", methods=["POST"])
def run():
    f = request.form
    jid = uuid.uuid4().hex
    JOBS[jid] = {"status": "stage1_running", "log": [], "st": None,
                 "pid": f["pid"], "char": f["char"]}

    def worker():
        j = JOBS[jid]
        try:
            j["st"] = P.run_stage_images(f["pid"], f["char"], f["top_style"], f["top_color"],
                                         f["bottom_style"], f["bottom_color"], f["location"],
                                         script_mode=f.get("script_mode", "manual"), log=_logger(j))
            j["status"] = "gate1"
        except Exception as e:
            j["status"] = "error"
            j["log"].append("ERROR: " + str(e))

    threading.Thread(target=worker, daemon=True).start()
    return redirect(url_for("job", jid=jid))


@app.route("/approve1/<jid>", methods=["POST"])
def approve1(jid):
    j = JOBS.get(jid) or abort(404)
    if j["status"] != "gate1":
        abort(409)
    edited = request.form.get("script", "").strip()
    sd = j["st"]["script_data"]
    if edited and edited != sd["script"]:
        auto = j["st"].get("script_mode") == "auto"
        wc_range = scripting.P2_WC_RANGE if auto else (85, 145)
        upd = scripting.resplit(edited, wc_range=wc_range, mode="auto" if auto else "manual")
        sd.update(upd)
        j["log"].append(f"script edited at Gate 1 -> {len(upd['cuts'])} cuts")
        for n in upd["notes"]:
            j["log"].append(n)
        P.save_script(j["st"])
    j["status"] = "stage2_running"
    threading.Thread(target=lambda: _run_stage(jid, P.run_stage_videos, "gate2"), daemon=True).start()
    return redirect(url_for("job", jid=jid))


@app.route("/approve2/<jid>", methods=["POST"])
def approve2(jid):
    j = JOBS.get(jid) or abort(404)
    if j["status"] != "gate2":
        abort(409)
    j["status"] = "finishing"
    threading.Thread(target=lambda: _run_stage(jid, P.run_stage_finish, "done"), daemon=True).start()
    return redirect(url_for("job", jid=jid))


@app.route("/job/<jid>")
def job(jid):
    j = JOBS.get(jid) or abort(404)
    return render_template_string(JOB, jid=jid, j=j, status=j["status"])


@app.route("/media")
def media():
    p = Path(request.args.get("p", "")).resolve()
    if ROOT.resolve() not in p.parents or not p.exists():
        abort(404)
    return send_file(str(p))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=7861, debug=False, threaded=True)
