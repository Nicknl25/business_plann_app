"""Render the coherence author proof (JSON from coherence_author_proof.py)
as the report page for Nick: per business, what the transcript offered
next to what the author would have offered."""
from __future__ import annotations

import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_coherence_proof_20260912.json")
DST = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "docs", "postmortems", "coherence_author_proof_20260912.html")

ORDER = ["3d57edc6", "955d2b46", "578d2006", "ef02160d", "625de320"]
NOTES = {
  "3d57edc6": "The walk cut a signed lease before the client could stop it, then read a yearly figure as monthly. The author reads the lease, the crews and the volume stop from the client's own words; the engine refuses every price move as gap-widening.",
  "955d2b46": "Evidence draft, read only. Point B shows the author reading seven refusals the walk answered with the same volume paragraph three times; the engine refuses the agent's own overhead-and-space candidate because the lease is held.",
  "578d2006": "Trapped in coherence last night. Here the engine refuses the materials-only move outright: under a fixed-cost-burden wall, cheaper materials close nothing, and the client was shown 'closing about $0' for it.",
  "ef02160d": "Killed by the rounding false-fail. Point A shows the over-read the proof caught and fixed: a rent figure the client merely stated was read as a floor.",
  "625de320": "The clean run. The numbers passed at the first evaluation, so nothing was offered and nothing would be.",
}
REASON = {
  "widens_the_gap": "widens the gap",
  "breaches_bound": "past the believable ceiling",
  "lever_floored_or_unavailable": "touches a floor",
  "closes_nothing": "closes nothing",
  "no_change": "no change",
  "unknown_line": "unknown line",
  "unknown_lever": "unknown lever",
  "depth_out_of_bounds": "depth out of bounds",
  "multiplier_below_one": "below today",
}
FLOOR = {"rent": "the space", "payroll": "the team", "marketing": "marketing", "gna": "other operating costs",
         "cogs": "direct costs", "pricing": "prices", "volume": "volumes", "new_lines": "new lines", "cost_structure": "cost structure"}


def e(x) -> str:
  return html.escape(str(x if x is not None else ""))


def cand_words(c: dict) -> str:
  k = c.get("kind")
  if k == "cost":
    return f"{k}: {', '.join(FLOOR.get(l, l) for l in (c.get('levers') or []))} at {c.get('depth')}"
  lines = ", ".join(f"{str(lm.get('line', '')).split(chr(0x241f))[-1][:28]} x{lm.get('multiplier')}" for lm in (c.get("line_moves") or []))
  return f"{k}: {lines}"


def option_rows(opts: list, id_key="id") -> str:
  rows = []
  for o in opts:
    why = f'<div class="why">{e(o.get("why"))}</div>' if o.get("why") else ""
    tags = []
    if o.get("recommended"):
      tags.append('<span class="tag rec">suggested</span>')
    if o.get("deep_cut"):
      tags.append('<span class="tag deep">deep cut</span>')
    rows.append(
      f'<li><div class="opt-main"><div class="label">{e(o.get("label"))} {" ".join(tags)}</div>{why}'
      f'<div class="id">{e(o.get(id_key))}</div></div>'
      f'<div class="closes">{e(o.get("closes_display") or "")}</div></li>')
  return "<ul class='opts'>" + "".join(rows) + "</ul>" if rows else "<p class='muted'>nothing</p>"


def actual_block(rep: dict) -> str:
  offers = rep.get("actual_offers") or []
  parts = []
  if rep.get("first_gate_message"):
    parts.append(f'<p class="quote">{e(rep["first_gate_message"][:600])} …</p>')
  shown = 0
  for off in offers:
    if not off.get("options"):
      continue
    shown += 1
    if shown > 3:
      break
    parts.append(f'<p class="trigger">message {off["index"]}, after the client said: <q>{e(off.get("after", "")[:160])}</q></p>')
    parts.append("<ul class='actual'>" + "".join(f"<li>{e(o)}</li>" for o in off["options"]) + "</ul>")
  if shown == 0:
    parts.append("<p class='muted'>no numbered options appear in the transcript</p>")
  return "".join(parts)


def authored_block(entry: dict) -> str:
  parts = [f'<h4>Point {e(entry.get("point"))}</h4>']
  parts.append(f'<p class="meta">transcript through message {entry.get("through")}; one author call, '
               f'{(entry.get("call") or {}).get("input_tokens") or "?"} tokens in, '
               f'{(entry.get("call") or {}).get("output_tokens") or "?"} out, {(entry.get("call") or {}).get("seconds") or "?"}s</p>')
  if entry.get("fallback"):
    parts.append(f"<p class='muted'>nothing authored: {e(entry['fallback'])}</p>")
    return "".join(parts)
  fr = entry.get("floors_read") or []
  if fr:
    parts.append("<div class='floors'><span class='k'>Floors read, and held before any move was built</span><ul>" + "".join(
      f"<li><b>{e(FLOOR.get(f.get('cost'), f.get('cost')))}</b> <span class='kind'>{e(f.get('kind') or '')}</span> — <q>{e(str(f.get('because'))[:140])}</q></li>" for f in fr) + "</ul></div>")
  else:
    parts.append("<div class='floors'><span class='k'>Floors read</span> <span class='muted'>none yet in the client's words</span></div>")
  fm = entry.get("floors_mentioned") or []
  if fm:
    parts.append("<div class='floors mention'><span class='k'>Mentioned, not refused (holds nothing)</span><ul>" + "".join(
      f"<li><b>{e(FLOOR.get(f.get('cost'), f.get('cost')))}</b> — <q>{e(str(f.get('because'))[:120])}</q></li>" for f in fm) + "</ul></div>")
  parts.append(option_rows(entry.get("options") or []))
  rej = entry.get("rejections") or []
  if rej:
    parts.append("<div class='refused'><span class='k'>Proposed by the agent, refused by the engine</span><ul>" + "".join(
      f"<li>{e(cand_words(r.get('candidate') or {}))} <span class='reason'>{e(REASON.get(r.get('reason'), r.get('reason')))}</span></li>" for r in rej) + "</ul></div>")
  return "".join(parts)


def business_section(rep: dict) -> str:
  key = rep["draft"]
  head = f'<section class="biz" id="{key}"><header><h2>{e(rep["business"])}</h2><div class="sub">draft {key} · {rep.get("messages")} messages</div>'
  head += f'<p class="note">{e(NOTES.get(key, ""))}</p></header>'
  if not rep.get("gate_fired"):
    return head + '<p class="pass">No gap at the gate. Nothing was offered; nothing would be authored.</p></section>'
  delta = (rep["gap_rebuilt"] / rep["gap_stated"] - 1) * 100 if rep.get("gap_stated") else 0
  gapline = (f'<div class="gapline"><span>Gap the gate stated</span><b>${rep["gap_stated"]:,.0f}</b>'
             f'<span>rebuilt pre-walk basis</span><b>${rep["gap_rebuilt"]:,.0f}</b><span class="delta">{delta:+.1f}%</span></div>')
  legacy = rep.get("legacy_round") or {}
  cols = ('<div class="cols"><div class="col was"><h3>What they were offered</h3>' + actual_block(rep)
          + f'<h4>The legacy engine on the rebuilt basis</h4><p class="meta">round: {e(legacy.get("key"))}</p>' + option_rows(legacy.get("options") or [])
          + '</div><div class="col would"><h3>What they would have been offered</h3>'
          + "".join(authored_block(a) for a in rep.get("authored") or []) + "</div></div>")
  return head + gapline + cols + "</section>"


def main() -> int:
  data = json.load(open(SRC, encoding="utf-8"))
  meter = data.get("_meter") or []
  tin = sum(int(c.get("input_tokens") or 0) for c in meter)
  tout = sum(int(c.get("output_tokens") or 0) for c in meter)
  secs = sum(float(c.get("seconds") or 0) for c in meter)
  sections = "".join(business_section(data[k]) for k in ORDER if k in data)
  page = f"""<title>Coherence Author Proof</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{--paper:#f4f5f2;--ink:#17211f;--muted:#5d6a66;--rule:#cfd6d2;--panel:#ffffff;--accent:#0f6b62;--accent-soft:#e2efec;--refuse:#8f3a2c;--refuse-soft:#f6e7e3;--hold:#7a5d12;--hold-soft:#f5edd6;--quote:#eef0ed}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--paper:#161a19;--ink:#e7ebe9;--muted:#9aa8a3;--rule:#2d3634;--panel:#1e2523;--accent:#5fc3b5;--accent-soft:#1d3532;--refuse:#e08a78;--refuse-soft:#3a2420;--hold:#d9b45a;--hold-soft:#3a3120;--quote:#242c2a}}}}
:root[data-theme="dark"]{{--paper:#161a19;--ink:#e7ebe9;--muted:#9aa8a3;--rule:#2d3634;--panel:#1e2523;--accent:#5fc3b5;--accent-soft:#1d3532;--refuse:#e08a78;--refuse-soft:#3a2420;--hold:#d9b45a;--hold-soft:#3a3120;--quote:#242c2a}}
body{{background:var(--paper);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:15px;line-height:1.5;padding-inline:20px;padding-block:32px 64px}}
.wrap{{max-width:1080px;margin:0 auto}}
h1,h2,h3{{font-family:"Source Serif 4",Georgia,serif;font-weight:600;text-wrap:balance;margin:0}}
h1{{font-size:2.1rem;line-height:1.15}}
.lede{{max-width:68ch;color:var(--muted);margin:10px 0 0}}
.eyebrow{{font-family:"IBM Plex Mono",monospace;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin-bottom:8px}}
.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:28px 0 8px}}
.summary div{{border-top:2px solid var(--accent);padding-top:8px}}
.summary b{{display:block;font-family:"IBM Plex Mono",monospace;font-size:1.25rem;font-variant-numeric:tabular-nums}}
.summary span{{color:var(--muted);font-size:.85rem}}
.method{{max-width:72ch;border-left:3px solid var(--rule);padding-left:14px;margin:26px 0;color:var(--muted);font-size:.92rem}}
.method b{{color:var(--ink)}}
.found{{margin:22px 0 34px}}
.found h2{{font-size:1.3rem;margin-bottom:8px}}
.found ol{{margin:0;padding-left:22px;max-width:76ch}}
.found li{{margin:6px 0}}
.biz{{border-top:1px solid var(--rule);padding-top:26px;margin-top:30px}}
.biz header h2{{font-size:1.55rem}}
.sub{{font-family:"IBM Plex Mono",monospace;font-size:.75rem;color:var(--muted);margin-top:4px}}
.note{{max-width:72ch;margin:10px 0 0;color:var(--muted)}}
.pass{{background:var(--accent-soft);color:var(--accent);padding:12px 14px;border-radius:4px;margin-top:16px;font-weight:500}}
.gapline{{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;margin:18px 0 12px;font-size:.9rem;color:var(--muted)}}
.gapline b{{font-family:"IBM Plex Mono",monospace;color:var(--ink);font-variant-numeric:tabular-nums}}
.gapline .delta{{font-family:"IBM Plex Mono",monospace}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:8px}}
@media (max-width:820px){{.cols{{grid-template-columns:1fr}}}}
.col{{background:var(--panel);border:1px solid var(--rule);border-radius:4px;padding:16px 18px;min-width:0}}
.col h3{{font-size:1.05rem;margin-bottom:12px}}
.col.would h3{{color:var(--accent)}}
.col h4{{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:18px 0 4px;font-weight:600}}
.meta{{font-family:"IBM Plex Mono",monospace;font-size:.72rem;color:var(--muted);margin:0 0 8px}}
.quote{{background:var(--quote);padding:10px 12px;border-radius:3px;font-size:.88rem;margin:0 0 10px}}
.trigger{{font-size:.85rem;color:var(--muted);margin:10px 0 4px}}
.trigger q{{color:var(--ink)}}
ul.actual{{margin:0;padding-left:18px;font-size:.9rem}}
ul.actual li{{margin:3px 0}}
ul.opts{{list-style:none;margin:0;padding:0}}
ul.opts li{{display:flex;gap:12px;justify-content:space-between;align-items:flex-start;padding:9px 0;border-top:1px solid var(--rule)}}
ul.opts li:first-child{{border-top:0}}
.opt-main{{min-width:0}}
.label{{font-weight:600}}
.why{{font-size:.9rem;color:var(--muted);margin-top:2px}}
.id{{font-family:"IBM Plex Mono",monospace;font-size:.68rem;color:var(--muted);margin-top:3px;word-break:break-all}}
.closes{{font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:500}}
.tag{{font-family:"IBM Plex Mono",monospace;font-size:.66rem;padding:1px 6px;border-radius:3px;vertical-align:middle;font-weight:500}}
.tag.rec{{background:var(--accent-soft);color:var(--accent)}}
.tag.deep{{background:var(--hold-soft);color:var(--hold)}}
.floors,.refused{{font-size:.88rem;border-radius:3px;padding:8px 10px;margin:8px 0}}
.floors{{background:var(--hold-soft)}}
.floors.mention{{background:var(--quote)}}
.refused{{background:var(--refuse-soft)}}
.floors .k,.refused .k{{display:block;font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;font-weight:600;margin-bottom:4px}}
.floors .k{{color:var(--hold)}}
.refused .k{{color:var(--refuse)}}
.floors ul,.refused ul{{margin:0;padding-left:16px}}
.kind{{font-family:"IBM Plex Mono",monospace;font-size:.68rem;color:var(--muted)}}
.reason{{font-family:"IBM Plex Mono",monospace;font-size:.72rem;color:var(--refuse);margin-left:6px}}
.muted{{color:var(--muted)}}
.limits{{max-width:76ch;margin-top:36px;padding-top:18px;border-top:1px solid var(--rule);font-size:.92rem;color:var(--muted)}}
.limits b{{color:var(--ink)}}
</style>
<div class="wrap">
<div class="eyebrow">Coherence options · step 3 proof · 12 Sep 2026</div>
<h1>What each of last night's five would have been offered</h1>
<p class="lede">The GPT author reads the transcript, names the refusals in the client's own words, and proposes moves. The engine prices every one and refuses what widens the gap, breaches a bound, touches a floor or closes nothing. Below, each business as the walk actually ran it, next to the round the author would have put in front of the client, at the first offer and again after everything the client said.</p>
<div class="summary">
<div><b>{len(meter)}</b><span>author calls across the five drafts</span></div>
<div><b>{tin:,} / {tout:,}</b><span>tokens in / out, all calls</span></div>
<div><b>{secs / max(1, len(meter)):.0f}s</b><span>per call, average</span></div>
<div><b>{tin // max(1, len(meter)):,}</b><span>tokens in per call, average</span></div>
</div>
<div class="method"><b>How the moment was rebuilt.</b> A finished draft holds its final figures, after the walk moved them. The gate's own first evaluation gives the pre-walk cost ratios and the flat payroll and rent; the gate's own first message gives the revenue and the gap it stated. The basis is rebuilt from those and checked against the stated gap on each business (the percentage next to it). Revenue lines come from the ops model as it stands now, which is post-walk where the walk moved prices or volumes. Halloran &amp; Voss was read and never written.</div>
<div class="found"><h2>What the proof caught in the new work, and what changed</h2><ol>
<li><b>The engine accepted a volume move after the client refused volume.</b> Sablecreek, point B: the author read "No more volume" as a floor and still proposed a volume candidate; the revenue pricer had no floor check. It now refuses any price or volume candidate whose family the client refused.</li>
<li><b>Moves that close nothing were shown.</b> Meriwether was offered a materials cut "closing about $0": under a fixed-cost-burden wall, cheaper materials change nothing. All three pricers now refuse a no-op alongside a gap-widener.</li>
<li><b>The agent over-read floors.</b> "We rent the plant" and "rent and the lease come to 78,000 a month" became rent floors. Each floor the agent reads is now classified: refused, cannot move, or merely mentioned. Only the first two hold; the third is kept for the record.</li>
<li><b>The holding line repeated itself</b> ("your volumes, your volumes") and lowercased the engine's lease clause. Fixed.</li>
</ol></div>
{sections}
<div class="limits"><b>Where this proof is weaker than a live run.</b> Point B keeps the pre-walk basis while reading the whole walk, so its closures are against the original gap, not the gap as it stood by then. The reconstructed gap sits within a few percent of the stated one on three businesses and further off on Halloran &amp; Voss, whose walk moved both prices and volumes. Every author call ran live once and is now in the response lock, so a rerun replays. Nothing here touched a Cowork run; that stays behind this proof, as ruled.</div>
</div>
"""
  os.makedirs(os.path.dirname(DST), exist_ok=True)
  with open(DST, "w", encoding="utf-8") as fh:
    fh.write(page)
  print("written", DST)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
