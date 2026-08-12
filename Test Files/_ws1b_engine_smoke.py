"""WS1(b) engine-half smoke: (1) per-line Sigma path, (2) single-line
exact legacy path, (3) solver lockstep via the blend lever, (4) raw-JSON
reconcile no-op on single-line, (5) contract accepts the COGS % row."""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "C:/dev/business_plann_app/python")

from financial_model_engine.model_inputs import FinancialModelInputs
from financial_model_engine.finmo_model import calculate_finmo_model


def _row(lob, product, slot, driver, values, extra=None):
    row = {
        "named_range": "model_input_revenue", "controller_write": True,
        "lever_id": f"revenue::{lob}::{product}::{driver}",
        "lob": lob, "product": product, "driver": driver,
        "revenue_slot_key": slot, "values": values,
    }
    row.update(extra or {})
    return row


Q = 20
ones = lambda v: [v] * (Q + 1)

# --- multi-line: bikes (rev 100*10*0.5=500/q, cogs 60%) + repairs (50*4*1.0=200/q, cogs 20%)
multi = {
    "start_date": "2026-01-01", "business_name": "SmokeCo",
    "sections": {
        "revenue": [
            _row("Retail", "Bikes", "lob_1_product_1", "Capacity", ones(100.0)),
            _row("Retail", "Bikes", "lob_1_product_1", "Unit Price", ones(10.0)),
            _row("Retail", "Bikes", "lob_1_product_1", "Utilization", ones(0.5)),
            _row("Retail", "Bikes", "lob_1_product_1", "COGS %", ones(0.6),
                 {"controller_write": False, "derived_driver": "per_line_cogs_source"}),
            _row("Service", "Repairs", "lob_2_product_1", "Capacity", ones(50.0)),
            _row("Service", "Repairs", "lob_2_product_1", "Unit Price", ones(4.0)),
            _row("Service", "Repairs", "lob_2_product_1", "Utilization", ones(1.0)),
            _row("Service", "Repairs", "lob_2_product_1", "COGS %", ones(0.2),
                 {"controller_write": False, "derived_driver": "per_line_cogs_source"}),
        ],
        # blend = (500*0.6 + 200*0.2)/700 = 340/700
        "expenses": [{
            "named_range": "model_input_expenses", "controller_write": True,
            "lever_id": "expenses::Cost of Goods Sold", "label": "Cost of Goods Sold",
            "values": ones(round(340.0 / 700.0, 6)),
        }],
        "balance_sheet": [],
        "schedules": {"rows": []},
    },
}

book = FinancialModelInputs.from_model_input_json(multi)
q1 = book.quarter(1)
sigma = q1.per_line_cogs_amount()
res = calculate_finmo_model(book)
r1 = res.quarter_results[1]
print("T1 per-line Sigma:", sigma, "expected 340 ->", abs(sigma - 340.0) < 1e-6)
print("T1 finmo cogs:", r1.cost_of_goods_sold, "->", abs(r1.cost_of_goods_sold - 340.0) < 1e-6,
      "| revenue:", r1.revenue)

# lockstep: solver writes blend 0.291 (~scale x0.6); lines must scale together
book.set_simple_driver(section="expenses", label="Cost of Goods Sold", quarter_index=1, value=0.291429)
q1 = book.quarter(1)
pcts = {p.product_name: round(p.cogs_percent, 6) for g in q1.revenue_groups for p in g.products}
sigma2 = q1.per_line_cogs_amount()
ratio_bikes = pcts["Bikes"] / 0.6
ratio_repairs = pcts["Repairs"] / 0.2
print("T3 lockstep pcts:", pcts, "| Sigma:", round(sigma2, 3),
      "expected ~204 ->", abs(sigma2 - 0.291429 * 700) < 0.01,
      "| same multiplier ->", abs(ratio_bikes - ratio_repairs) < 1e-6)

# --- single-line: no COGS % row -> exact legacy scalar path
single = json.loads(json.dumps(multi))
single["sections"]["revenue"] = [r for r in single["sections"]["revenue"]
                                 if r["lob"] == "Retail" and r["driver"] != "COGS %"]
single["sections"]["expenses"][0]["values"] = ones(0.55)
book_s = FinancialModelInputs.from_model_input_json(single)
qs = book_s.quarter(1)
print("T2 single-line per_line_cogs_amount is None ->", qs.per_line_cogs_amount() is None)
res_s = calculate_finmo_model(book_s)
print("T2 single-line cogs:", res_s.quarter_results[1].cost_of_goods_sold,
      "expected 275 ->", abs(res_s.quarter_results[1].cost_of_goods_sold - 500 * 0.55) < 1e-6)

# --- serializer round-trip: COGS % row emitted for multi, absent for single
mi_multi = book.to_model_input_json()
mi_single = book_s.to_model_input_json()
multi_cogs_rows = [r for r in mi_multi["sections"]["revenue"] if r["driver"] == "COGS %"]
single_cogs_rows = [r for r in mi_single["sections"]["revenue"] if r["driver"] == "COGS %"]
print("T4 serializer: multi emits", len(multi_cogs_rows), "COGS % rows (expect 2);",
      "single emits", len(single_cogs_rows), "(expect 0)")

# --- raw-JSON reconcile: blend moved in JSON, lines must follow
from client_intake_and_finmo.finmo_bridge import _reconcile_per_line_cogs_rows
recon = json.loads(json.dumps(multi))
recon["sections"]["expenses"][0]["values"] = ones(0.24285714)  # half the original blend
_reconcile_per_line_cogs_rows(recon)
new_pcts = {r["product"]: r["values"][5] for r in recon["sections"]["revenue"] if r["driver"] == "COGS %"}
print("T5 raw reconcile pcts:", new_pcts, "expected ~{Bikes:0.3, Repairs:0.1} ->",
      abs(new_pcts["Bikes"] - 0.3) < 1e-3 and abs(new_pcts["Repairs"] - 0.1) < 1e-3)

# single-line JSON reconcile must be a strict no-op
recon_s = json.loads(json.dumps(single))
before = json.dumps(recon_s, sort_keys=True)
_reconcile_per_line_cogs_rows(recon_s)
print("T6 single-line reconcile no-op ->", json.dumps(recon_s, sort_keys=True) == before)

# --- contract accepts the COGS % row shape
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import RevenueRow
try:
    RevenueRow(
        named_range="model_input_revenue", controller_write=False,
        derived_driver="per_line_cogs_source",
        lever_id="revenue::Retail::Bikes::COGS %", lob="Retail", product="Bikes",
        driver="COGS %", revenue_slot_key="lob_1_product_1",
        value_kind="ratio", input_semantics="percent_of_line_revenue",
        values=[0.6] * 21,
    )
    print("T7 contract accepts COGS % row -> True")
except Exception as exc:
    print("T7 contract REJECTED:", exc)
# out-of-range percent must still be rejected
try:
    RevenueRow(
        named_range="model_input_revenue", controller_write=False,
        derived_driver="per_line_cogs_source",
        lever_id="revenue::Retail::Bikes::COGS %", lob="Retail", product="Bikes",
        driver="COGS %", revenue_slot_key="lob_1_product_1",
        value_kind="ratio", input_semantics="percent_of_line_revenue",
        values=[1.6] * 21,
    )
    print("T8 out-of-range ACCEPTED (BAD)")
except Exception:
    print("T8 out-of-range percent rejected -> True")
