"""ONE VISUAL IDENTITY FOR EVERY CHART (2026-08-30; reworked to the approved
design brief 2026-08-31).

The palette is the workbook's design.py palette - already run through the
dataviz validator against a white surface (categorical order IS the
colorblind-safety mechanism; revenue blue / cost red semantic pair passed
all-pairs CVD) - so the document's charts and the workbook's charts read as
one system. Nothing in the writing phase picks a color; it picks a ROLE.

THE BRIEF (Nick's ruling): no gridlines, no borders, no legend boxes; series
labelled directly on the line or the last bar; two colours and a neutral;
restraint, not decoration. And ANNOTATION is what separates a consultant's
chart from a template's - each figure carries the annotation the chart
registry records for it, drawn ON the chart.

Figures render at 200 dpi, 6.5in wide full width / 3.2in wrapped, PNG bytes,
matplotlib Agg only - no display, no browser, no plotly (Nick refused a
Chromium dependency to draw a static chart).
"""
from __future__ import annotations

import io
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "..")):
  if _p not in sys.path:
    sys.path.insert(0, _p)
from client_statements_output_excel import design as D  # noqa: E402  the single door

def _hx(c: str) -> str:
  return "#" + c

INK = _hx(D.INK)
INK_MUTED = _hx(D.INK_MUTED)
RULE = _hx(D.RULE)
SERIES = [_hx(c) for c in D.SERIES]
REVENUE = _hx(D.SERIES_REVENUE)
COST = _hx(D.SERIES_COST)
ATTENTION = _hx(D.SERIES_ATTENTION)
NEUTRAL = _hx(D.SERIES_REFERENCE)
WASH = _hx(D.BAND_PROFIT)

FIG_W_IN = 6.5
WRAP_W_IN = 3.2
DPI = 200
_FONT = "DejaVu Sans"   # matplotlib's own; consistent across every figure

YEARS = ["Year 1", "Year 2", "Year 3", "Year 4", "Year 5"]
YEARS_SHORT = ["Y1", "Y2", "Y3", "Y4", "Y5"]


def _style_axes(ax, *, money_axis: bool = True, small: bool = False):
  """The brief, enforced in one place: no gridlines, no top/right spines,
  hairline left/bottom only."""
  for side in ("top", "right"):
    ax.spines[side].set_visible(False)
  for side in ("left", "bottom"):
    ax.spines[side].set_color(RULE)
    ax.spines[side].set_linewidth(0.8)
  ax.tick_params(colors=INK_MUTED, labelsize=6.5 if small else 8, length=3)
  ax.yaxis.grid(False)
  ax.xaxis.grid(False)
  if money_axis:
    ax.yaxis.set_major_formatter(FuncFormatter(_money_tick))


def _money_tick(v, _pos):
  a = abs(v)
  if a >= 1_000_000:
    return "$%.1fM" % (v / 1_000_000.0)
  if a >= 1_000:
    return "$%.0fK" % (v / 1_000.0)
  return "$%.0f" % v


def _money(v: float) -> str:
  a = abs(v)
  s = "$%.1fM" % (a / 1e6) if a >= 1e6 else ("$%.0fK" % (a / 1e3) if a >= 1e3 else "$%.0f" % a)
  return ("-" if v < 0 else "") + s


def _finish(fig) -> bytes:
  buf = io.BytesIO()
  fig.tight_layout()
  # bbox_inches="tight" grows the canvas to include direct labels drawn past
  # the axes (annotation_clip=False) - the docx insert scales to width, so a
  # slightly wider canvas never breaks the page.
  fig.savefig(buf, format="png", dpi=DPI, facecolor="white",
              bbox_inches="tight", pad_inches=0.06)
  plt.close(fig)
  return buf.getvalue()


def _trunc(s: str, n: int) -> str:
  s = str(s)
  return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _new_fig(height_in: float = 3.2, width_in: float = FIG_W_IN):
  plt.rcParams["font.family"] = _FONT
  fig, ax = plt.subplots(figsize=(width_in, height_in))
  for item in ([ax.title, ax.xaxis.label, ax.yaxis.label]):
    item.set_color(INK)
  return fig, ax


def _end_label(ax, x, y, text, color, *, dx=6, dy=0, size=8, weight="normal"):
  ax.annotate(text, (x, y), textcoords="offset points", xytext=(dx, dy),
              fontsize=size, color=color, va="center", fontweight=weight,
              annotation_clip=False)


# ---------------------------------------------------------------------------
# MARKET & INDUSTRY
# ---------------------------------------------------------------------------
def fig_industry_history(years: Sequence[int], establishments: Sequence[float],
                         entry_year: Optional[int] = None) -> bytes:
  """The 46-year BDS series: one line, full width. Annotation: final point
  labelled with count and year; a marker at the client's entry year."""
  years, est = list(years), list(establishments)
  fig, ax = _new_fig(2.8)
  ax.plot(years, est, color=REVENUE, linewidth=1.8)
  ax.fill_between(years, est, color=WASH, alpha=1.0)
  _end_label(ax, years[-1], est[-1], "{:,.0f}\n({})".format(est[-1], years[-1]),
             INK, dx=8, size=8, weight="bold")
  if entry_year is not None and years[0] <= entry_year <= years[-1] + 3:
    xe = min(entry_year, years[-1])
    ye = est[years.index(xe)] if xe in years else est[-1]
    ax.plot([xe], [ye], marker="v", markersize=7, color=ATTENTION, zorder=5)
    ax.annotate("enters here", (xe, ye), textcoords="offset points",
                xytext=(-8, -16), ha="right", fontsize=8, color=ATTENTION)
  ax.margins(x=0.02)
  ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: "{:,.0f}".format(v)))
  _style_axes(ax, money_axis=False)
  return _finish(fig)


def fig_local_market_composition(rows: Sequence[Dict[str, Any]]) -> bytes:
  """County sibling lines as horizontal bars, WRAP width. The client's own
  line is the only coloured bar - annotation by colour and label."""
  rows = list(rows)
  fig, ax = _new_fig(0.5 + 0.42 * len(rows), WRAP_W_IN)
  labels = [_trunc(r["label"], 28) for r in rows][::-1]
  vals = [float(r["establishments"]) for r in rows][::-1]
  own = [bool(r.get("is_client_line")) for r in rows][::-1]
  colors = [REVENUE if o else NEUTRAL for o in own]
  bars = ax.barh(range(len(rows)), vals, color=colors, height=0.62)
  ax.set_yticks(range(len(rows)))
  ax.set_yticklabels(labels, fontsize=6.5, color=INK)
  for i, (b, v, o) in enumerate(zip(bars, vals, own)):
    ax.annotate(("%d — your line" % v) if o else "%d" % v,
                (v, i), textcoords="offset points", xytext=(4, 0),
                fontsize=6.5, color=INK if o else INK_MUTED, va="center",
                fontweight="bold" if o else "normal")
  ax.set_xticks([])
  _style_axes(ax, money_axis=False, small=True)
  ax.spines["bottom"].set_visible(False)
  ax.margins(x=0.18)
  return _finish(fig)


# ---------------------------------------------------------------------------
# PRODUCTS & SERVICES
# ---------------------------------------------------------------------------
def fig_revenue_by_lob(series: Sequence[Dict[str, Any]]) -> bytes:
  """Stacked columns Y1-Y5, one colour per line, labelled at the final
  column - no legend. Annotation: the fastest-growing line's CAGR."""
  series = list(series)
  fig, ax = _new_fig()
  bottom = [0.0] * 5
  tops: List[float] = []
  fastest, fastest_cagr = None, None
  for i, s in enumerate(series):
    vals = [float(v) for v in s["annual"][:5]]
    ax.bar(YEARS, vals, bottom=bottom, color=SERIES[i % len(SERIES)],
           width=0.62, edgecolor="white", linewidth=0.5)
    mid = bottom[4] + vals[4] / 2.0
    # anchored past the bar's right EDGE (half-width 0.31), never its centre -
    # a centre anchor puts the label's first characters under the next
    # series' columns (caught on the first render, 2026-08-31)
    _end_label(ax, 4.36, mid, _trunc(s["lob"], 22), SERIES[i % len(SERIES)], dx=2, size=8)
    bottom = [b + v for b, v in zip(bottom, vals)]
    if vals[0] > 0 and vals[4] > 0:
      cagr = (vals[4] / vals[0]) ** 0.25 - 1.0
      if fastest_cagr is None or cagr > fastest_cagr:
        fastest, fastest_cagr = str(s["lob"]), cagr
    tops = bottom[:]
  if fastest is not None:
    ax.annotate("fastest: %s, %.0f%% a year" % (_trunc(fastest, 24), fastest_cagr * 100),
                (0.02, 0.96), xycoords="axes fraction", fontsize=8, color=INK,
                va="top")
  ax.margins(x=0.02)
  ax.set_xlim(-0.6, 5.6)   # room for the direct labels on the right
  _style_axes(ax)
  return _finish(fig)


# ---------------------------------------------------------------------------
# STAFFING & HUMAN CAPITAL
# ---------------------------------------------------------------------------
def fig_headcount_by_role(series: Sequence[Dict[str, Any]]) -> bytes:
  """Stacked area over the five years, WRAP width. Bands labelled directly at
  the right edge; total headcount labelled at both ends."""
  series = list(series)
  fig, ax = _new_fig(2.6, WRAP_W_IN)
  x = list(range(5))
  bottom = [0.0] * 5
  for i, s in enumerate(series):
    vals = [float(v) for v in s["annual"][:5]]
    top = [b + v for b, v in zip(bottom, vals)]
    ax.fill_between(x, bottom, top, color=SERIES[i % len(SERIES)], alpha=0.9,
                    linewidth=0)
    if vals[4] >= 0.4:   # a band too thin to label stays unlabelled
      _end_label(ax, 4, bottom[4] + vals[4] / 2.0, _trunc(s["group"], 18),
                 SERIES[i % len(SERIES)], dx=5, size=6.5)
    bottom = top
  for xi in (0, 4):
    _end_label(ax, xi, bottom[xi], "%.1f FTE" % bottom[xi], INK,
               dx=(-2 if xi == 0 else 2), dy=8, size=7, weight="bold")
  ax.set_xticks(x)
  ax.set_xticklabels(YEARS_SHORT, fontsize=6.5)
  ax.margins(x=0.02)
  _style_axes(ax, money_axis=False, small=True)
  return _finish(fig)


def fig_wage_positioning(rows: Sequence[Dict[str, Any]]) -> bytes:
  """Each OEWS-matched role: the state p10-p90 band as a neutral bar, the
  p25-p75 span thicker, a median tick, and the PLANNED wage as the coloured
  dot labelled with its value. Full width."""
  rows = list(rows)
  fig, ax = _new_fig(0.7 + 0.52 * len(rows))
  for i, r in enumerate(reversed(rows)):
    p10, p90 = float(r["p10"] or r["p25"]), float(r["p90"] or r["p75"])
    p25, p75 = float(r["p25"]), float(r["p75"])
    med, wage = float(r["median"]), float(r["planned_wage"])
    ax.plot([p10, p90], [i, i], color=NEUTRAL, linewidth=2.0, solid_capstyle="round")
    ax.plot([p25, p75], [i, i], color=NEUTRAL, linewidth=6.0, alpha=0.45,
            solid_capstyle="round")
    ax.plot([med, med], [i - 0.16, i + 0.16], color=INK_MUTED, linewidth=1.2)
    inside = p10 <= wage <= p90
    ax.plot([wage], [i], marker="o", markersize=7,
            color=REVENUE if inside else ATTENTION, zorder=5)
    _end_label(ax, wage, i, _money(wage), INK, dx=0, dy=10, size=7, weight="bold")
  ax.set_yticks(range(len(rows)))
  ax.set_yticklabels([_trunc(r["role"], 34) for r in reversed(rows)], fontsize=7.5,
                     color=INK)
  ax.xaxis.set_major_formatter(FuncFormatter(_money_tick))
  _style_axes(ax, money_axis=False)
  ax.margins(y=0.2)
  fig.text(0.99, 0.01, "bar: state 10th-90th percentile for the occupation · tick: median · dot: this plan's wage",
           ha="right", fontsize=6.5, color=INK_MUTED)
  return _finish(fig)


# ---------------------------------------------------------------------------
# FINANCIAL PLAN
# ---------------------------------------------------------------------------
def fig_revenue_net_income(revenue: Sequence[float], net_income: Sequence[float],
                           cagr: Optional[float] = None) -> bytes:
  """Revenue columns with a net-income line, one shared money axis so the two
  are honest against each other. Annotation: the first profitable year, and
  the revenue growth rate."""
  rev, ni = [float(v) for v in revenue[:5]], [float(v) for v in net_income[:5]]
  fig, ax = _new_fig()
  ax.bar(YEARS, rev, color=REVENUE, width=0.62)
  ax.plot(range(5), ni, color=COST, linewidth=2.0, marker="o", markersize=4)
  _end_label(ax, 4, rev[4], "Revenue", REVENUE, dx=8, dy=4, size=8, weight="bold")
  _end_label(ax, 4, ni[4], "Net income", COST, dx=8, size=8, weight="bold")
  first_prof = next((i for i, v in enumerate(ni) if v > 0), None)
  if first_prof is not None:
    ax.annotate("profitable from %s" % YEARS[first_prof],
                (first_prof, ni[first_prof]), textcoords="offset points",
                xytext=(0, 14), fontsize=8, color=INK, ha="center")
  if cagr is not None:
    ax.annotate("revenue grows %.0f%% a year" % (cagr * 100), (0.02, 0.96),
                xycoords="axes fraction", fontsize=8, color=INK, va="top")
  ax.set_xlim(-0.6, 5.2)
  _style_axes(ax)
  return _finish(fig)


def fig_margin_structure(margins: Sequence[Dict[str, Any]]) -> bytes:
  """Three margin lines, WRAP width, each labelled at its right end with the
  name and Year-5 value - no legend."""
  m = list(margins)
  fig, ax = _new_fig(2.6, WRAP_W_IN)
  for key, color, label in (("gross", SERIES[0], "Gross"),
                            ("operating", SERIES[2], "Operating"),
                            ("net", SERIES[6], "Net")):
    vals = [float(r[key]) * 100 for r in m[:5]]
    ax.plot(range(5), vals, color=color, linewidth=1.8, marker="o", markersize=3)
    _end_label(ax, 4, vals[4], "%s %.0f%%" % (label, vals[4]), color, dx=5, size=6.5,
               weight="bold")
  ax.set_xticks(range(5))
  ax.set_xticklabels(YEARS_SHORT, fontsize=6.5)
  ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: "%.0f%%" % v))
  ax.set_xlim(-0.2, 5.6)
  _style_axes(ax, money_axis=False, small=True)
  return _finish(fig)


def fig_cash_position(cash: Sequence[float], trough_quarter: int,
                      months_cover: Optional[float] = None) -> bytes:
  """QUARTERLY cash area (the trough is a quarterly event). Annotation: the
  trough with its value, quarter, and months of operating cover."""
  cash = [float(v) for v in cash[:20]]
  fig, ax = _new_fig()
  x = list(range(1, len(cash) + 1))
  ax.fill_between(x, cash, color=WASH, alpha=1.0)
  ax.plot(x, cash, color=REVENUE, linewidth=1.8)
  ti = max(1, min(int(trough_quarter), len(cash)))
  tv = cash[ti - 1]
  ax.plot([ti], [tv], marker="o", markersize=7, color=ATTENTION, zorder=5)
  note = "low point: %s in Q%d" % (_money(tv), ti)
  if months_cover is not None:
    note += " — %.1f months of operating cover" % months_cover
  ax.annotate(note, (ti, tv), textcoords="offset points", xytext=(10, -16),
              fontsize=8.5, color=INK, fontweight="bold")
  ax.set_xticks(x[::2])
  ax.set_xticklabels(["Q%d" % i for i in x[::2]], fontsize=7)
  ax.margins(x=0.02)
  _style_axes(ax)
  return _finish(fig)


def fig_break_even_cvp(revenue_q: Sequence[float], total_cost_q: Sequence[float],
                       break_even_quarter: Optional[int] = None,
                       margin_of_safety: Optional[float] = None) -> bytes:
  """Revenue vs the all-in cost line; the crossing IS the model's break-even.
  Annotation: the crossing labelled with revenue and quarter, the margin of
  safety written into the gap."""
  rev = [float(v) for v in revenue_q[:20]]
  cost = [float(v) for v in total_cost_q[:20]]
  fig, ax = _new_fig()
  x = list(range(1, len(rev) + 1))
  ax.plot(x, rev, color=REVENUE, linewidth=1.9)
  ax.plot(x, cost, color=COST, linewidth=1.9)
  ax.fill_between(x, cost, rev, where=[r >= c for r, c in zip(rev, cost)],
                  color=WASH, alpha=1.0, interpolate=True)
  _end_label(ax, x[-1], rev[-1], "Revenue", REVENUE, dx=8, size=8, weight="bold")
  _end_label(ax, x[-1], cost[-1], "Total cost", COST, dx=8, size=8, weight="bold")
  if break_even_quarter is not None and 1 <= int(break_even_quarter) <= len(rev):
    b = int(break_even_quarter)
    ax.plot([b], [rev[b - 1]], marker="o", markersize=7, color=ATTENTION, zorder=5)
    ax.annotate("break-even: %s in Q%d" % (_money(rev[b - 1]), b),
                (b, rev[b - 1]), textcoords="offset points", xytext=(10, 10),
                fontsize=8.5, color=INK, fontweight="bold")
  if margin_of_safety is not None:
    gi = max(1, int(len(rev) * 0.7))
    ax.annotate("margin of safety %.0f%%" % (margin_of_safety * 100),
                (gi, (rev[gi - 1] + cost[gi - 1]) / 2.0), fontsize=7.5,
                color=INK_MUTED, ha="center", va="center")
  ax.set_xticks(x[::2])
  ax.set_xticklabels(["Q%d" % i for i in x[::2]], fontsize=7)
  ax.margins(x=0.02)
  _style_axes(ax)
  return _finish(fig)


def fig_sensitivity_band(revenue: Sequence[float], low_mult: float, high_mult: float,
                         scenario_label: str = "marketing cut back") -> bytes:
  """THE BOUNDED SCENARIO BAND - not a fan. One flat tone between two NAMED
  boundary lines; a gradient would claim a probability distribution we do not
  hold. Caption drawn on the figure: judged scenarios, bounds not confidence
  intervals."""
  rev = [float(v) for v in revenue[:5]]
  lo = [v * float(low_mult) for v in rev]
  hi = [v * float(high_mult) for v in rev]
  fig, ax = _new_fig()
  x = list(range(5))
  ax.fill_between(x, lo, hi, color=WASH, alpha=1.0, linewidth=0)
  ax.plot(x, rev, color=REVENUE, linewidth=2.0)
  for vals, mult in ((lo, low_mult), (hi, high_mult)):
    ax.plot(x, vals, color=NEUTRAL, linewidth=1.2, linestyle=(0, (4, 3)))
    _end_label(ax, 4, vals[4], "%s:\ndemand holds %.0f%%  (%s)"
               % (scenario_label, mult * 100, _money(vals[4])), INK_MUTED, dx=6, size=7)
  _end_label(ax, 4, rev[4], "plan  (%s)" % _money(rev[4]), REVENUE, dx=6, size=8,
             weight="bold")
  ax.set_xticks(x)
  ax.set_xticklabels(YEARS, fontsize=8)
  ax.set_xlim(-0.2, 5.8)
  _style_axes(ax)
  fig.text(0.99, 0.01, "judged scenarios — bounds, not confidence intervals",
           ha="right", fontsize=7, color=INK_MUTED, style="italic")
  return _finish(fig)


# ---------------------------------------------------------------------------
# FUNDING REQUEST
# ---------------------------------------------------------------------------
def fig_sba_ask_distribution(deciles: Sequence[Dict[str, Any]], ask: float,
                             percentile_label: str = "",
                             loan_count: Optional[int] = None) -> bytes:
  """The percentile strip: the in-scope 7(a) approval distribution as one
  horizontal band, the client's request marked ON it. WRAP width. Annotation:
  the ask with its percentile and the loan count behind it."""
  dv = {int(d["pct"]): float(d["amount"]) for d in deciles}
  p10, p25, p50, p75, p90 = (dv.get(p) for p in (10, 25, 50, 75, 90))
  fig, ax = _new_fig(1.9, WRAP_W_IN)
  y = 0
  ax.plot([p10, p90], [y, y], color=NEUTRAL, linewidth=3.0, solid_capstyle="round")
  ax.plot([p25, p75], [y, y], color=NEUTRAL, linewidth=9.0, alpha=0.45,
          solid_capstyle="round")
  ax.plot([p50, p50], [y - 0.12, y + 0.12], color=INK_MUTED, linewidth=1.4)
  _end_label(ax, p50, y, "median %s" % _money(p50), INK_MUTED, dx=0, dy=-16, size=6.5)
  ax.plot([float(ask)], [y], marker="o", markersize=9, color=REVENUE, zorder=5)
  note = "your request: %s" % _money(float(ask))
  if percentile_label:
    note += " — %s percentile" % percentile_label
  if loan_count:
    note += "\nof {:,} approved loans in this industry".format(int(loan_count))
  ax.annotate(note, (float(ask), y), textcoords="offset points", xytext=(0, 14),
              fontsize=7, color=INK, ha="center", fontweight="bold")
  ax.set_yticks([])
  ax.spines["left"].set_visible(False)
  ax.xaxis.set_major_formatter(FuncFormatter(_money_tick))
  _style_axes(ax, money_axis=False, small=True)
  ax.spines["left"].set_visible(False)
  ax.margins(y=0.6, x=0.08)
  return _finish(fig)
