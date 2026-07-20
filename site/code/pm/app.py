#!/usr/bin/env python3
"""Local self-serve web app for the product-modelling pipeline. Zero Claude tokens.

Form: PID · Character (dropdown) · Type · #videos -> runs modelling.run_modelling in a
background thread -> results page shows the try-on still + each video with its QC contact
sheet for your final review.

Run:  python3 app.py     then open http://127.0.0.1:7860
      Set UGC_DATA_ROOT if auto-detect fails: export UGC_DATA_ROOT='/path/to/Perf UGC Ads'
"""
import json
import threading
import uuid
from pathlib import Path

from flask import Flask, abort, redirect, render_template_string, request, send_file, url_for

import modelling

ROOT = modelling.ROOT
app = Flask(__name__)
JOBS = {}

# Unboxing (U2) is intentionally NOT here — it is a SEPARATE tool (user 2026-06-22).
# Remix (added 2026-07-14): a character cycles through 2-4 products, each its own chapter
# clip (stills + 2 hard-cut Kling shots). See modelling.py's REMIX section for the full recipe.
TYPES = [("product_modelling", "Product Modelling"), ("remix", "Remix")]

FORM = """
<!doctype html><html><head><title>UGC Studio</title>
<style>body{font:15px/1.5 -apple-system,system-ui,sans-serif;max-width:560px;margin:40px auto;padding:0 16px;color:#1a1a2e}
h1{font-size:20px}label{display:block;margin:16px 0 4px;font-weight:600}
input,select{width:100%;padding:10px;border:1px solid #ccc;border-radius:8px;font-size:15px}
button{margin-top:24px;padding:12px 20px;background:#1a1a2e;color:#fff;border:0;border-radius:8px;font-size:15px;cursor:pointer;width:100%}
.hint{color:#777;font-size:13px;margin-top:4px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}</style></head><body>
<h1>🎬 UGC Product-Modelling Studio</h1>
<form method="post" action="{{ url_for('run') }}">
  <label>Type</label>
  <select name="kind" id="kind" onchange="syncKind()">{% for k,lbl in types %}<option value="{{k}}">{{lbl}}</option>{% endfor %}</select>

  <div id="pm-fields">
    <label>PID (product id)</label>
    <input name="pid" id="pid" placeholder="e.g. 206041">
    <div class="hint">Reads product images from <code>Stock PID Images/&lt;PID&gt;/</code></div>
    <label>Sub Type</label>
    <select name="subtype" id="subtype" onchange="syncVar()">{% for k,lbl,_ in subtypes %}<option value="{{k}}">{{lbl}}</option>{% endfor %}</select>
    <label>Variation <span style="color:#777;font-weight:400;font-size:13px">— location, depends on Sub Type</span></label>
    <select name="variation" id="variation"></select>
    <label>Video model</label>
    <select name="model">{% for m,lbl in models %}<option value="{{m}}">{{lbl}}</option>{% endfor %}</select>
    <div class="hint">Seedance = 12-shot rich editorial (true multishot, natural skin) · Kling 3.0 = 10-shot numbered editorial with camera + model movement. Each take rotates a distinct prompt variant — 2–3 takes give you intentionally different raw material to cut from.</div>
    <label>Number of videos <span style="color:#777;font-weight:400;font-size:13px">— takes of the SAME model · PID · variation</span></label>
    <select name="n"><option>1</option><option selected>2</option><option>3</option></select>
  </div>

  <div id="remix-fields" style="display:none">
    <label>PIDs <span style="color:#777;font-weight:400;font-size:13px">— 2 to 4, comma-separated</span></label>
    <input name="remix_pids" id="remix_pids" placeholder="e.g. 245787, 134220">
    <div class="hint">Each PID becomes its own chapter clip. Reads product images from <code>Stock PID Images/&lt;PID&gt;/</code> for each.</div>
    <label>Outfit</label>
    <div class="row2">
      <select name="top_style">{% for k in clothing.tops %}<option value="{{k}}" {% if k==clothing._defaults.top_style %}selected{% endif %}>{{k}}</option>{% endfor %}</select>
      <select name="top_color">{% for c in clothing.top_colors %}<option value="{{c}}" {% if c==clothing._defaults.top_color %}selected{% endif %}>{{c}}</option>{% endfor %}</select>
    </div>
    <div class="row2" style="margin-top:8px">
      <select name="bottom_style">{% for k in clothing.bottoms %}<option value="{{k}}" {% if k==clothing._defaults.bottom_style %}selected{% endif %}>{{k}}</option>{% endfor %}</select>
      <select name="bottom_color">{% for c in clothing.bottom_colors %}<option value="{{c}}" {% if c==clothing._defaults.bottom_color %}selected{% endif %}>{{c}}</option>{% endfor %}</select>
    </div>
    <label>Run name</label>
    <input name="run_name" id="run_name" placeholder="e.g. Video_1_test">
    <div class="hint">Output lands in <code>Ads/Remix/&lt;run name&gt;/</code> — one shared kit frame + one subfolder per chapter (stills + chapter video).</div>
  </div>

  <label>Character / Model</label>
  <select name="char">{% for cid,_ in chars %}<option value="{{cid}}">{{cid}}</option>{% endfor %}</select>
  <button type="submit">Generate</button>
</form>
<p class="hint">{{ chars|length }} characters available · Product Modelling outputs land in <code>Ads/&lt;PID&gt;/_selfserve/</code> · Remix outputs land in <code>Ads/Remix/&lt;run name&gt;/</code></p>
<script>
const VARS = {{ varmap_json|safe }};
function syncVar(){
  const st=document.getElementById('subtype').value, v=document.getElementById('variation');
  v.innerHTML=''; const opts=VARS[st]||[];
  if(!opts.length){const o=document.createElement('option');o.value='';o.textContent='— to build later —';o.disabled=true;v.appendChild(o);}
  else opts.forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n;v.appendChild(o);});
}
function syncKind(){
  const k=document.getElementById('kind').value;
  const isRemix = k==='remix';
  document.getElementById('pm-fields').style.display = isRemix ? 'none' : '';
  document.getElementById('remix-fields').style.display = isRemix ? '' : 'none';
  document.getElementById('pid').required = !isRemix;
  document.getElementById('remix_pids').required = isRemix;
}
syncVar(); syncKind();
</script>
</body></html>"""

JOB = """
<!doctype html><html><head><title>Job {{jid[:8]}}</title>
{% if status=='running' %}<meta http-equiv="refresh" content="6">{% endif %}
<style>body{font:15px/1.5 -apple-system,system-ui,sans-serif;max-width:900px;margin:30px auto;padding:0 16px;color:#1a1a2e}
.s{padding:4px 10px;border-radius:6px;font-weight:600;font-size:13px}
.running{background:#fff3cd}.done{background:#d1e7dd}.error{background:#f8d7da}
pre{background:#0d1117;color:#c9d1d9;padding:12px;border-radius:8px;overflow:auto;font-size:13px;max-height:240px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
video,img{width:100%;border-radius:10px;border:1px solid #ddd}.card{border:1px solid #eee;border-radius:12px;padding:12px}
a{color:#1a1a2e}</style></head><body>
<p><a href="{{ url_for('index') }}">← new job</a></p>
{% if job.kind == 'remix' %}
<h1>Remix · {{job.char}} · <small style="font-weight:400;color:#666">{{job.pids}}</small> <span class="s {{status}}">{{status}}</span></h1>
{% else %}
<h1>PID {{job.pid}} · {{job.char}} · <small style="font-weight:400;color:#666">{{job.subtype}}/{{job.variation}} · {{job.model}}</small> <span class="s {{status}}">{{status}}</span></h1>
{% endif %}
<pre>{{ '\n'.join(job.log) }}</pre>
{% if job.log_path %}<p style="font-size:13px;color:#777">Log file: <code>{{job.log_path}}</code></p>{% endif %}
{% if status!='running' %}
  {% set r = job.result %}
  {% if r and job.kind == 'remix' %}
    {% if r.final_video %}
    <h3>Final compilation <small style="font-weight:400;color:#666">({{ r.chapters|length }} chapters, hard-cut joined)</small></h3>
    <video controls src="{{ url_for('media') }}?p={{r.final_video}}" style="max-width:400px"></video>
    {% endif %}
    <h3>Kit frame <small style="font-weight:400;color:#666">{{r.outfit}}</small></h3>
    {% if r.kit_frame %}<img src="{{ url_for('media') }}?p={{r.kit_frame}}" style="max-width:320px">{% endif %}
    <h3>Chapters ({{ r.chapters|length }})</h3>
    <div class="grid">
    {% for c in r.chapters %}
      <div class="card"><b>PID {{c.pid}}</b><br>
      {% if c.video %}<video controls src="{{ url_for('media') }}?p={{c.video}}"></video>{% else %}<i>chapter video not available</i>{% endif %}
      <div style="display:flex;gap:6px;margin-top:8px">
        {% if c.tryon %}<img src="{{ url_for('media') }}?p={{c.tryon}}" style="width:33%" title="tryon">{% endif %}
        {% if c.temple_zoom %}<img src="{{ url_for('media') }}?p={{c.temple_zoom}}" style="width:33%" title="temple_zoom">{% endif %}
        {% if c.front_closeup %}<img src="{{ url_for('media') }}?p={{c.front_closeup}}" style="width:33%" title="front_closeup">{% endif %}
      </div>
      </div>
    {% endfor %}
    </div>
    {% if r.errors %}<h3>Errors</h3><pre>{{ '\n'.join(r.errors) }}</pre>{% endif %}
  {% elif r %}
    <h3>Try-on still {% if r.still_sheet %}(<a href="{{ url_for('media') }}?p={{r.still_sheet}}">QC sheet</a>){% endif %}</h3>
    {% if r.still %}<img src="{{ url_for('media') }}?p={{r.still}}" style="max-width:320px">{% endif %}
    <h3>Videos ({{ r.videos|length }})</h3>
    <div class="grid">
    {% for v in r.videos %}
      <div class="card"><b>Take {{v.take}}</b><br><video controls src="{{ url_for('media') }}?p={{v.path}}"></video>
      {% if v.sheet %}<br><a href="{{ url_for('media') }}?p={{v.sheet}}">QC contact sheet ↗</a>{% endif %}</div>
    {% endfor %}
    </div>
    {% if r.errors %}<h3>Errors</h3><pre>{{ '\n'.join(r.errors) }}</pre>{% endif %}
  {% endif %}
{% endif %}
</body></html>"""


def _worker(jid, kind, params):
    j = JOBS[jid]
    if kind == "remix":
        run_name = (params.get("run_name") or "Video_1_test").strip().replace("/", "_")
        log_path = ROOT / "Ads" / "Remix" / run_name / f"job_{jid[:8]}.log"
    else:
        log_path = ROOT / "Ads" / params["pid"] / "_selfserve" / f"job_{jid[:8]}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    j["log_path"] = str(log_path)

    def _log(m):
        msg = str(m)
        j["log"].append(msg)
        with open(log_path, "a") as f:
            f.write(msg + "\n")

    try:
        if kind == "remix":
            j["result"] = modelling.run_remix(
                params["pids"], params["char"],
                top_style=params.get("top_style"), top_color=params.get("top_color"),
                bottom_style=params.get("bottom_style"), bottom_color=params.get("bottom_color"),
                run_name=params.get("run_name"), log=_log)
        else:
            j["result"] = modelling.run_modelling(
                params["pid"], params["char"], params["n"], kind, params["model"],
                params["subtype"], params["variation"], log=_log)
        j["status"] = "done"
    except Exception as e:
        j["status"] = "error"
        _log("ERROR: " + str(e))


@app.route("/")
def index():
    subs = modelling.subtype_options()
    varmap = {k: vrs for k, _lbl, vrs in subs}
    return render_template_string(FORM, chars=modelling.list_characters(), types=TYPES,
                                  models=list(modelling.MODEL_LABELS.items()),
                                  subtypes=subs, varmap_json=json.dumps(varmap),
                                  clothing=modelling.CLOTHING)


@app.route("/run", methods=["POST"])
def run():
    kind = request.form.get("kind", "product_modelling")
    char = request.form["char"]
    jid = uuid.uuid4().hex

    if kind == "remix":
        pids = [p.strip() for p in request.form.get("remix_pids", "").split(",") if p.strip()]
        run_name = request.form.get("run_name") or "Video_1_test"
        params = {"pids": pids, "char": char, "run_name": run_name,
                  "top_style": request.form.get("top_style"),
                  "top_color": request.form.get("top_color"),
                  "bottom_style": request.form.get("bottom_style"),
                  "bottom_color": request.form.get("bottom_color")}
        JOBS[jid] = {"status": "running", "log": [], "result": None, "kind": kind,
                     "char": char, "pids": ", ".join(pids), "log_path": None}
    else:
        pid = request.form["pid"].strip()
        n = int(request.form.get("n", 2))
        model = request.form.get("model", "seedance_2_0")
        subtype = request.form.get("subtype", "A3.1")
        variation = request.form.get("variation") or None
        params = {"pid": pid, "char": char, "n": n, "model": model,
                  "subtype": subtype, "variation": variation}
        JOBS[jid] = {"status": "running", "log": [], "result": None, "kind": kind,
                     "pid": pid, "char": char, "model": model, "subtype": subtype,
                     "variation": variation, "log_path": None}

    threading.Thread(target=_worker, args=(jid, kind, params), daemon=True).start()
    return redirect(url_for("job", jid=jid))


@app.route("/job/<jid>")
def job(jid):
    j = JOBS.get(jid) or abort(404)
    return render_template_string(JOB, jid=jid, job=j, status=j["status"])


@app.route("/media")
def media():
    p = Path(request.args.get("p", "")).resolve()
    if ROOT.resolve() not in p.parents or not p.exists():
        abort(404)
    return send_file(str(p))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=7860, debug=False, threaded=True)
