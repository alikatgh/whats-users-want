#!/usr/bin/env python3
"""Generate a self-contained HTML page comparing two extraction CSVs, ticket by ticket.

For eyeballing in a browser whether one model (e.g. DeepSeek V4) reads tickets better
than another (Mistral): each shared ticket's text shown next to both models'
job / want / money-trust-urgency / emotion, with graded-score differences highlighted,
plus a summary of how much each model spreads the 1-5 scores.

Data is embedded inline (no fetch), so the single HTML file works over http.server or
file://. CONTAINS TICKET TEXT + UIDs — serve on localhost only, never a public host.

Usage:
  python scripts/build_compare_view.py <run_dir> \
     [--baseline ollama_mistral-small3.2-24b_extractions.csv] \
     [--candidate deepseek_v4_sample.csv] [--out outputs/v4_compare/index.html]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

FIELDS = ["job_to_be_done", "actual_user_want", "money_risk_level", "trust_risk_level",
          "urgency_level", "safety_policy_risk_level", "user_emotion", "confidence"]
SUMMARY_FIELDS = ["money_risk_level", "trust_risk_level", "urgency_level", "confidence"]

TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>V4 vs Mistral — extraction comparison</title>
<style>
:root{--bg:#fafafa;--fg:#141414;--muted:#6b6b6b;--line:#e4e4e4;--diff:#fff3e0;--vk:#0b74d1}
*{box-sizing:border-box}
body{margin:0;font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--fg);background:var(--bg)}
header{padding:18px 24px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:5}
h1{font-size:17px;margin:0 0 3px;font-weight:650}
.sub{color:var(--muted);font-size:13px}
.summary{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
.stat{border:1px solid var(--line);border-radius:8px;padding:7px 11px;background:#fff;font-size:12.5px}
.stat .f{color:var(--muted)}
.stat b{font-variant-numeric:tabular-nums}
.controls{padding:10px 24px;border-bottom:1px solid var(--line);font-size:13px;color:var(--muted)}
main{padding:16px 24px;max-width:1080px}
.card{border:1px solid var(--line);border-radius:10px;background:#fff;margin-bottom:13px;overflow:hidden}
.ticket{padding:11px 14px;border-bottom:1px solid var(--line)}
.sr{font-family:ui-monospace,Menlo,monospace;color:var(--muted);font-size:11.5px}
.cols{display:grid;grid-template-columns:1fr 1fr}
.col{padding:11px 14px}
.col+.col{border-left:1px solid var(--line)}
.who{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:6px;font-weight:600}
.col.v .who{color:var(--vk)}
.kv{margin:3px 0}.kv .k{color:var(--muted)}
.num{font-variant-numeric:tabular-nums}
.d{background:var(--diff);border-radius:4px;padding:0 5px;font-weight:650}
.want{margin-top:7px;color:#333;font-size:13px}
</style></head><body>
<header><h1>DeepSeek&nbsp;V4 vs Mistral — extraction comparison</h1>
<div class="sub" id="sub"></div><div class="summary" id="summary"></div></header>
<div class="controls"><label><input type="checkbox" id="onlyDiff"> Only tickets where a graded score differs</label> &nbsp;·&nbsp; <span id="count"></span></div>
<main id="main"></main>
<script>const DATA=/*DATA*/;
function esc(s){return String(s==null?"":s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}
document.getElementById("sub").textContent=DATA.rows.length+" shared tickets · baseline "+DATA.baseline+" · candidate "+DATA.candidate;
document.getElementById("summary").innerHTML=DATA.summary.map(s=>
 '<div class="stat"><span class="f">'+esc(s.field.replace("_level","").replace("_risk",""))+'</span> &nbsp; '+
 'dom <b>'+(s.mDom*100).toFixed(0)+'%→'+(s.vDom*100).toFixed(0)+'%</b> &nbsp; spread <b>'+s.mEnt.toFixed(2)+'→'+s.vEnt.toFixed(2)+'</b></div>').join("");
const GR=[["money","money_risk_level"],["trust","trust_risk_level"],["urg","urgency_level"]];
function graded(o,other){
 let p=GR.map(([lab,k])=>'<span class="k">'+lab+'</span> <b class="num '+(o[k]!==other[k]?"d":"")+'">'+esc(o[k])+'</b>').join(" · ");
 p+=' · <span class="k">emo</span> <b>'+esc(o.user_emotion)+'</b> · <span class="k">conf</span> <b class="num">'+esc(o.confidence)+'</b>';
 return p;
}
function col(o,other,cls){return '<div class="col '+cls+'"><div class="who">'+esc(cls==="v"?DATA.candidate:DATA.baseline)+'</div>'+
 '<div class="kv"><span class="k">job:</span> <b>'+esc(o.job_to_be_done)+'</b></div>'+
 '<div class="kv">'+graded(o,other)+'</div>'+
 '<div class="want">'+esc(o.actual_user_want)+'</div></div>';}
function render(){
 const only=document.getElementById("onlyDiff").checked;
 const rows=DATA.rows.filter(r=>!only||r.hasDiff);
 document.getElementById("count").textContent="showing "+rows.length+" of "+DATA.rows.length;
 document.getElementById("main").innerHTML=rows.map(r=>
  '<div class="card"><div class="ticket"><span class="sr">source_row '+esc(r.sr)+'</span><br>'+esc(r.ticket)+'</div>'+
  '<div class="cols">'+col(r.m,r.v,"m")+col(r.v,r.m,"v")+'</div></div>').join("");
}
document.getElementById("onlyDiff").addEventListener("change",render);render();
</script></body></html>"""


def dom_ent(series: pd.Series) -> tuple[float, float]:
    vc = series.dropna().astype(str).value_counts()
    if vc.empty:
        return 0.0, 0.0
    total = vc.sum()
    dom = vc.iloc[0] / total
    if len(vc) <= 1:
        return float(dom), 0.0
    ent = -sum((c / total) * math.log(c / total) for c in vc) / math.log(len(vc))
    return float(dom), float(ent)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--baseline", default="ollama_mistral-small3.2-24b_extractions.csv")
    ap.add_argument("--candidate", default="deepseek_v4_sample.csv")
    ap.add_argument("--out", default="outputs/v4_compare/index.html")
    a = ap.parse_args()
    run = Path(a.run_dir)

    enr = pd.read_csv(run / "enriched_tickets.csv", dtype=str)
    enr["source_row"] = enr["source_row"].astype(str)
    tcol = "question_flat" if "question_flat" in enr.columns else "question"
    ticket = dict(zip(enr["source_row"], enr[tcol].fillna("")))

    def load(name):
        df = pd.read_csv(run / name, dtype=str).drop_duplicates("source_row")
        df["source_row"] = df["source_row"].astype(str)
        return df.set_index("source_row")

    b, c = load(a.baseline), load(a.candidate)
    shared = sorted(set(b.index) & set(c.index))

    def fields(row):
        return {k: (row.get(k) if k in row.index else "") for k in FIELDS}

    rows = []
    for sr in shared:
        m, v = fields(b.loc[sr]), fields(c.loc[sr])
        has_diff = any(m[k] != v[k] for k in ["money_risk_level", "trust_risk_level", "urgency_level"])
        rows.append({"sr": sr, "ticket": str(ticket.get(sr, ""))[:600], "m": m, "v": v, "hasDiff": has_diff})

    summary = []
    for f in SUMMARY_FIELDS:
        md, me = dom_ent(b.loc[shared, f]) if f in b.columns else (0, 0)
        vd, ve = dom_ent(c.loc[shared, f]) if f in c.columns else (0, 0)
        summary.append({"field": f, "mDom": md, "mEnt": me, "vDom": vd, "vEnt": ve})

    label = lambda n: n.replace("_extractions.csv", "").replace(".csv", "")
    data = {"baseline": label(a.baseline), "candidate": label(a.candidate), "rows": rows, "summary": summary}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.replace("/*DATA*/", payload), encoding="utf-8")
    print(f"wrote {out}  ({len(rows)} shared tickets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
