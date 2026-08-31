"""ONE VISUAL IDENTITY FOR EVERY CHART (2026-08-30).

The palette is the workbook's design.py palette - already run through the
dataviz validator against a white surface (categorical order IS the
colorblind-safety mechanism; revenue blue / cost red semantic pair passed
all-pairs CVD) - so the document's charts and the workbook's charts read as
one system. Nothing in the writing phase picks a color; it picks a ROLE.

Figures render at 200 dpi, 6.5in wide (full page width inside 1in margins),
PNG bytes, matplotlib Agg only - no display, no browser, no plotly (Nick
refused a Chromium dependency to draw a static chart).
"""
from __future__ import annotations

import io
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

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
GRID = _hx(D.GRID)
RULE = _hx(D.RULE)
SERIES = [_hx(c) for c in D.SERIES]
REVENUE = _hx(D.SERIES_REVENUE)
COST = _hx(D.SERIES_COST)
ATTENTION = _hx(D.SERIES_ATTENTION)

FIG_W_IN = 6.5
DPI = 200
_FONT = "DejaVu Sans"   # matplotlib's own; consistent across every figure


def _style_axes(ax, *, money_axis: bool = True):
  ax.spines["top"].set_visible(False)
  ax.spines["right"].set_visible(False)
  ax.spines["left"].set_color(RULE)
  ax.spines["bottom"].set_color(RULE)
  ax.tick_params(colors=INK_MUTED, labelsize=8)
  ax.yaxis.grid(True, color=GRID, linewidth=0.8)
  ax.set_axisbelow(True)
  if money_axis:
    ax.yaxis.set_major_formatter(FuncFormatter(_money_tick))


def _money_tick(v, _pos):
  a = abs(v)
  if a >= 1_000_000:
    return "$%.1fM" % (v / 1_000_000.0)
  if a >= 1_000:
    return "$%.0fK" % (v / 1_000.0)
  return "$%.0f" % v


def _finish(fig) -> bytes:
  buf = io.BytesIO()
  fig.tight_layout()
  fig.savefig(buf, format="png", dpi=DPI, facecolor="white")
  plt.close(fig)
  return buf.getvalue()


def _new_fig(height_in: float = 3.2):
  fig, ax = plt.subplots(figsize=(FIG_W_IN, height_in))
  plt.rcParams["font.family"] = _FONT
  for item in ([ax.title, ax.xaxis.label, ax.yaxis.label]):
    item.set_color(INK)
  return fig, ax


YEARS = ["Year 1", "Year 2", "Year 3", "Year 4", "Year 5"]


def fig_revenue_by_lob(lob_annual: Dict[str, Sequence[float]]) -> bytes:
  """Chart 1 - stacked columns, one series per line of business, Y1-Y5."""
  fig, ax = _new_fig()
  bottom = [0.0] * 5
  for i, (lob, vals) in enumerate(lob_annual.items()):
    ax.bar(YEARS, vals[:5], bottom=bottom, color=SERIES[i % len(SERIES)],
           label=lob, width=0.62, edgecolor="white", linewidth=0.5)
    bottom = [b + v for b, v in zip(bottom, vals[:5])]
  _style_axes(ax)
  ax.legend(loc="upper left", frameon=False, fontsize=8, labelcolor=INK)
  return _finish(fig)


def fig_revenue_net_income(revenue: Sequence[float], net_income: Sequence[float]) -> bytes:
  """Chart 3 - revenue columns with a net-income line, Y1-Y5."""
  fig, ax = _new_fig()
  ax.bar(YEARS, revenue[:5], color=REVENUE, width=0.62, label="Revenue")
  ax2 = ax.twinx()
  ax2.plot(YEARS, net_income[:5], color=COST, linewidth=2.0, marker="o",
           markersize=4, label="Net income")
  ax2.spines["top"].set_visible(False)
  ax2.spines["right"].set_color(RULE)
  ax2.tick_params(colors=INK_MUTED, labelsize=8)
  ax2.yaxis.set_major_formatter(FuncFormatter(_money_tick))
  _style_axes(ax)
  h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
  ax.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False, fontsize=8, labelcolor=INK)
  return _finish(fig)


def fig_cash_position(quarter_labels: Sequence[str], cash: Sequence[float],
                      trough_index: Optional[int] = None) -> bytes:
  """Chart 5 - QUARTERLY cash area with the trough annotated. Quarterly by
  Nick's ruling: a trough chart with five annual points cannot show a trough."""
  fig, ax = _new_fig()
  x = list(range(len(cash)))
  ax.fill_between(x, cash, color=_hx(D.BAND_PROFIT), alpha=1.0)
  ax.plot(x, cash, color=REVENUE, linewidth=1.8)
  if trough_index is not None and 0 <= trough_index < len(cash):
    ax.plot([trough_index], [cash[trough_index]], marker="o", markersize=6, color=ATTENTION)
    ax.annotate("cash trough", (trough_index, cash[trough_index]),
                textcoords="offset points", xytext=(8, -14),
                fontsize=8, color=INK)
  ax.set_xticks(x[::2])
  ax.set_xticklabels([quarter_labels[i] for i in x[::2]], fontsize=7)
  _style_axes(ax)
  return _finish(fig)


def fig_margin_structure(gross: Sequence[float], operating: Sequence[float],
                         net: Sequence[float]) -> bytes:
  """Chart 4 - margin lines, Y1-Y5, sized for WRAP placement (sits beside
  prose at ~3.1in), so fonts run slightly larger relative to the frame."""
  fig, ax = plt.subplots(figsize=(3.2, 2.6))
  for vals, color, label in ((gross, SERIES[0], "Gross"),
                             (operating, SERIES[2], "Operating"),
                             (net, SERIES[6], "Net")):
    ax.plot(YEARS, [v * 100 for v in vals[:5]], color=color, linewidth=1.8,
            marker="o", markersize=3, label=label)
  ax.spines["top"].set_visible(False)
  ax.spines["right"].set_visible(False)
  ax.spines["left"].set_color(RULE)
  ax.spines["bottom"].set_color(RULE)
  ax.tick_params(colors=INK_MUTED, labelsize=7)
  ax.set_xticklabels(["Y1", "Y2", "Y3", "Y4", "Y5"])
  ax.yaxis.grid(True, color=GRID, linewidth=0.8)
  ax.set_axisbelow(True)
  ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: "%.0f%%" % v))
  ax.legend(loc="best", frameon=False, fontsize=7, labelcolor=INK)
  return _finish(fig)


def fig_industry_history(years: Sequence[int], establishments: Sequence[float],
                         highlight_label: str = "") -> bytes:
  """The 46-year BDS series (depth item 4): establishments in the industry,
  one line, full width. One chart and two sentences - never a lecture."""
  fig, ax = _new_fig(2.8)
  ax.plot(list(years), list(establishments), color=REVENUE, linewidth=1.8)
  ax.fill_between(list(years), list(establishments), color=_hx(D.BAND_PROFIT), alpha=1.0)
  if highlight_label:
    ax.annotate(highlight_label, (years[-1], establishments[-1]),
                textcoords="offset points", xytext=(-8, 8), ha="right",
                fontsize=8, color=INK)
  ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: "{:,.0f}".format(v)))
  _style_axes(ax, money_axis=False)
  ax.yaxis.grid(True, color=GRID, linewidth=0.8)
  return _finish(fig)
