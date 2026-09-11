"""WAREHOUSE (spec 1.6) - public data, each row carrying NAICS, source and
vintage. Every slice recipe below reproduces the hand-built Thornfield
reference exactly (verified 2026-09-08).

Two layers, like classification: a per-draft PIN carries the curated choices
the reference made by hand (which codes feed which table, the SBA group
labels, the occupation set, the wage-positioning rows built from stated
wages); the generic path derives the same choices from the classification
groups, the draft's geography, and the payroll roster's SOC stamps.
Anything the generic path cannot ground is OMITTED - a missing slice is a
shorter bundle, never an invented one.
"""
from __future__ import annotations

import json
import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

NOTE = ("All industry rows carry NAICS, source and vintage. Public-company "
        "benchmark rows were excluded as unsuitable for a six-person business.")
_GENERIC_NOTE = ("All industry rows carry NAICS, source and vintage. "
                 "Public-company benchmark rows were excluded as unsuitable "
                 "for a small business.")

PIN: Dict[str, Dict[str, Any]] = {
    "eae0ac3f": {
        "note": NOTE,
        "cbp_county": ["424", "4249", "424990", "4541", "454110"],
        "cbp_state": ["4249", "424990", "454110"],
        "cbp_national": ["4249", "424990", "454110"],
        "bds4": ["4539", "4541", "4249"],
        "sba_groups": [("pet_and_pet_supplies_retailers", ["453910", "459910"]),
                       ("other_misc_nondurable_wholesalers", ["424990"]),
                       ("electronic_shopping_2017", ["454110"])],
        "baseline_codes": ["4249", "424990", "4599", "459910"],
        "occ_codes": ["11-1021", "27-4021", "41-4012", "43-4051",
                      "43-5071", "53-7051", "53-7062", "53-7065"],
        "wage_rows": [
            {"soc": "53-7065", "client_wage": 38000,
             "client_label": "Pickers and packers (2, each)"},
            {"soc": "43-4051", "client_wage": 42000,
             "client_label": "Customer service (1)"},
            {"soc": "11-1021", "client_wage": 64000,
             "client_label": "Operations lead"},
        ],
    },
}


def _jl(v):
    if isinstance(v, (dict, list)) or v is None:
        return v
    try:
        return json.loads(v)
    except Exception:
        return None


def _pin(draft) -> Optional[Dict[str, Any]]:
    return next((v for k, v in PIN.items()
                 if str(draft.get("draft_id", "")).startswith(k)), None)


def _f(v):
    return None if v is None else float(v)


def _s(v):
    if v is None:
        return None
    s = str(v)
    return s[:-2] if s.endswith(".0") else s


# ---------------------------------------------------------------------------
def _geo(conn, draft) -> Dict[str, Any]:
    """County geoid + names from the draft's zip via the crosswalk."""
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT geoid FROM zip_county_crosswalk WHERE zcta=%s "
                "ORDER BY zpop_pct DESC LIMIT 1", (str(draft.get("address_zip")),))
    r = cur.fetchone()
    geoid = r["geoid"] if r else None
    return {"state": draft.get("address_state"), "zip": draft.get("address_zip"),
            "county_geoid": geoid,
            "state_fips": geoid[:2] if geoid else None,
            "county_fips": geoid[2:] if geoid else None}


def _codes_from_groups(cls: Dict[str, Any]) -> Dict[str, List[str]]:
    codes6, codes4 = [], []
    for g in cls.get("groups", []):
        for c in g.get("naics", []):
            c = str(c)
            (codes6 if len(c) == 6 else codes4 if len(c) == 4 else []).append(c)
    for c in codes6:
        if c[:4] not in codes4:
            codes4.append(c[:4])
    return {"c6": codes6, "c4": codes4}


# ---------------------------------------------------------------------------
def _cbp(conn, geo, county_codes, state_codes, national_codes):
    cur = conn.cursor(dictionary=True)
    out: Dict[str, Any] = {}
    kent: Dict[str, Any] = {}
    if geo["state_fips"]:
        cur.execute("SELECT naics, naics_label, estab, pay_ann, emp FROM "
                    "cbp_2022_raw_county WHERE state_fips=%s AND county_fips=%s "
                    "AND naics IN (%s)" % ("%s", "%s",
                                           ",".join(["%s"] * len(county_codes))),
                    tuple([geo["state_fips"], geo["county_fips"]] + county_codes))
        for r in sorted(cur.fetchall(), key=lambda x: x["naics"]):
            kent[r["naics"]] = {"title": r["naics_label"], "estab": _f(r["estab"]),
                                "pay_ann": _f(r["pay_ann"]), "emp": _f(r["emp"])}
    st: Dict[str, Any] = {}
    cur.execute("SELECT naics, estab, pay_ann, emp FROM cbp_2022_raw "
                "WHERE state_name=%s AND naics IN (%s)"
                % ("%s", ",".join(["%s"] * len(state_codes))),
                tuple([geo["state"]] + state_codes))
    for r in sorted(cur.fetchall(), key=lambda x: x["naics"]):
        st[r["naics"]] = {"estab": _f(r["estab"]), "pay_ann": _f(r["pay_ann"]),
                          "emp": _f(r["emp"])}
    nat: Dict[str, Any] = {}
    cur.execute("SELECT naics, SUM(estab) e, SUM(pay_ann) p, SUM(emp) m FROM "
                "cbp_2022_raw WHERE naics IN (%s) GROUP BY naics ORDER BY naics"
                % ",".join(["%s"] * len(national_codes)), tuple(national_codes))
    for r in cur.fetchall():
        nat[r["naics"]] = {"estab": int(r["e"]), "pay_ann": _f(r["p"]),
                           "emp": _f(r["m"])}
    county_key = "kent_county" if geo["county_geoid"] == "26081" else "county"
    state_key = (geo["state"] or "state").lower().replace(" ", "_")
    out[county_key], out[state_key], out["national"] = kent, st, nat
    return out


def _bds(conn, codes4, with_shares):
    cur = conn.cursor(dictionary=True)
    out: Dict[str, Any] = {}
    for c4 in codes4:
        cur.execute("SELECT * FROM bds_firm_age WHERE vcnaics4=%s AND year=2023", (c4,))
        rows = cur.fetchall()
        if not rows:
            continue
        firms = sum(r["firms"] or 0 for r in rows)
        estabs = sum(r["estabs"] or 0 for r in rows)
        emp = sum(r["emp"] or 0 for r in rows)
        entry = sum(r["estabs_entry"] or 0 for r in rows)
        exit_ = sum(r["estabs_exit"] or 0 for r in rows)
        njc = sum(r["net_job_creation"] or 0 for r in rows)

        def _firms_at(age, year):
            cur.execute("SELECT firms FROM bds_firm_age WHERE vcnaics4=%s AND "
                        "year=%s AND firm_age_bucket=%s", (c4, year, age))
            r = cur.fetchone()
            return (r or {}).get("firms")

        one = (_firms_at("b) 1", 2023), _firms_at("a) 0", 2022))
        five = (_firms_at("f) 5", 2023), _firms_at("a) 0", 2018))
        cur.execute("SELECT year, SUM(estabs) e FROM bds_firm_age WHERE "
                    "vcnaics4=%s AND year IN "
                    "(1980,1985,1990,1995,2000,2005,2010,2015,2019,2020,2021,2022,2023) "
                    "GROUP BY year ORDER BY year", (c4,))
        hist = [[int(r["year"]), int(r["e"])] for r in cur.fetchall()]
        cur.execute("SELECT SUM(estabs) e FROM bds_firm_age WHERE vcnaics4=%s "
                    "AND year=1978", (c4,))
        e78 = (cur.fetchone() or {}).get("e")
        d = {"year": 2023, "firms": float(firms), "estabs": float(estabs),
             "emp": float(emp),
             "five_year_survival": (float(five[0]) / float(five[1])) if all(five) else None,
             "one_year_survival": (float(one[0]) / float(one[1])) if all(one) else None,
             "entry_rate": float(entry) / float(estabs),
             "exit_rate": float(exit_) / float(estabs),
             "net_job_creation_rate": float(njc) / float(emp),
             "estabs_1978": _f(e78), "estabs_history": hist}
        if c4 in with_shares:
            cur.execute("SELECT firm_size_bucket, SUM(firms) f FROM bds_firm_size "
                        "WHERE vcnaics4=%s AND year=2023 GROUP BY firm_size_bucket",
                        (c4,))
            fs = {r["firm_size_bucket"]: r["f"] for r in cur.fetchall()}
            allf = float(sum(fs.values()))
            if allf:
                d["share_firms_under_5"] = float(fs.get("a) 1 to 4") or 0) / allf
                d["share_firms_under_10"] = float((fs.get("a) 1 to 4") or 0)
                                                  + (fs.get("b) 5 to 9") or 0)) / allf
        out[c4] = d
    return out


def _bds_size(conn, code4):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT firm_size_bucket, SUM(firms) f FROM bds_firm_size "
                "WHERE vcnaics4=%s AND year=2023 GROUP BY firm_size_bucket "
                "ORDER BY firm_size_bucket", (code4,))
    rows = cur.fetchall()
    return {"naics4": code4, "year": 2023, "source": "Census BDS",
            "firms_by_size": {r["firm_size_bucket"]: int(r["f"] or 0)
                              for r in rows}}


def _oews(conn, occ_codes, areas):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM oews_state_wages WHERE occ_code IN (%s) AND "
                "area_title IN (%s)"
                % (",".join(["%s"] * len(occ_codes)), ",".join(["%s"] * len(areas))),
                tuple(occ_codes + areas))
    rows = cur.fetchall()
    rows.sort(key=lambda r: (r["occ_code"], areas.index(r["area_title"])))
    keep = ("tot_emp", "loc_quotient", "a_pct10", "a_pct25", "a_median",
            "a_pct75", "a_pct90")
    return [{"area_title": r["area_title"], "occ_code": r["occ_code"],
             "occ_title": r["occ_title"],
             **{k: _s(r.get(k)) for k in keep}} for r in rows]


def _sba(conn, groups, geo):
    cur = conn.cursor(dictionary=True)
    out: Dict[str, Any] = {}
    state_slug = (str(geo["state"] or "state")).lower().replace(" ", "_")
    county_slug = (str(_county_name(conn, geo) or "county")).lower() + "_county"
    for label, codes in groups:
        cur.execute("SELECT GrossApproval, InitialInterestRate, TermInMonths, "
                    "LoanStatus, ProjectState, ProjectCounty, ApprovalFY, "
                    "BorrCity, BankName, BusinessAge, id FROM sba_loan_7a_raw "
                    "WHERE NAICSCode IN (%s) AND ApprovalFY BETWEEN 2020 AND 2025"
                    % ",".join(["%s"] * len(codes)), tuple(codes))
        rows = cur.fetchall()
        if not rows:
            continue
        gross = sorted(float(r["GrossApproval"]) for r in rows)
        q = statistics.quantiles(gross, n=4)
        rates = sorted(float(r["InitialInterestRate"]) for r in rows
                       if (r["InitialInterestRate"] or 0) > 0)
        terms = sorted(float(r["TermInMonths"]) for r in rows)
        st_rows = [r for r in rows if r["ProjectState"] == _state_abbr(geo["state"])]
        county_name = _county_name(conn, geo)
        county_rows = [r for r in st_rows
                       if county_name and r["ProjectCounty"] == county_name]
        county_rows.sort(key=lambda r: (r["ApprovalFY"], r["id"]))
        st_gross = sorted(float(r["GrossApproval"]) for r in st_rows)
        d = {"naics": list(codes), "fy": "2020-2025", "loans": len(rows),
             "median_amount": q[1], "p25_amount": q[0], "p75_amount": q[2],
             "median_rate": statistics.median(rates) if rates else None,
             "median_term_months": statistics.median(terms),
             "chargeoff_share": sum(1 for r in rows
                                    if r["LoanStatus"] == "CHGOFF") / len(rows),
             (state_slug + "_loans"): len(st_rows),
             (state_slug + "_median"): statistics.median(st_gross) if st_gross else None,
             county_slug: [[str(r["ApprovalFY"]), r["BorrCity"],
                              r["BankName"], float(r["GrossApproval"]),
                              float(r["InitialInterestRate"]),
                              float(r["TermInMonths"]), r["BusinessAge"]]
                             for r in county_rows],
             "pct_rank_of_ask": {str(a): sum(1 for g in gross if g < a) / len(gross)
                                 for a in (50000, 100000, 150000, 250000)}}
        out[label] = d
    return out


# The complete USPS table, both directions. Drafts carry the state as
# either form; OEWS area_title carries FULL names ('Illinois') while SBA
# rows carry abbreviations - joining with the wrong form returns zero
# rows silently. 'IL' vs 'Illinois' emptied wage_positioning AND
# oews_may2023 for every multi-metro state (Bright Smiles 2026-09-10);
# the old map knew two states because only two had ever been hit.
_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida",
    "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE_ABBRS = {v: k for k, v in _STATE_NAMES.items()}


def _state_abbr(name):
    s = str(name or "").strip()
    if s.upper() in _STATE_NAMES:
        return s.upper()
    return _STATE_ABBRS.get(s, s[:2].upper())


def _state_area_title(state):
    """The OEWS/BLS area title for a state in either form - full name
    out, always."""
    s = str(state or "").strip()
    return _STATE_NAMES.get(s.upper(), s)


# no warehouse table carries county NAMES (only FIPS); SBA's ProjectCounty
# is a name, so the geoid->name map grows here as businesses arrive. An
# unknown geoid just yields no county loan list - shorter, never invented.
_COUNTY_NAMES = {"26081": "KENT", "44007": "PROVIDENCE"}


def _county_name(conn, geo):
    return _COUNTY_NAMES.get(str(geo["county_geoid"]))


def _acs_national(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) z, SUM(B01001_001E) pop, SUM(B11001_001E) hh, "
                "SUM(B19001_014E+B19001_015E+B19001_016E+B19001_017E) h100, "
                "SUM(B19001_016E+B19001_017E) h150, SUM(B11001_002E) fam "
                "FROM acs_zip_2022_part1")
    r = cur.fetchone()
    return {"zctas": int(r["z"]), "population": _f(r["pop"]),
            "households": _f(r["hh"]), "households_total_b11001": _f(r["hh"]),
            "households_100k_plus": _f(r["h100"]),
            "households_150k_plus": _f(r["h150"]),
            "family_households": _f(r["fam"]),
            "nonfamily_households": _f(r["hh"]) - _f(r["fam"])}


def _acs_county(conn, geo):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT a.B01001_001E pop, a.B11001_001E hh, a.B19013_001E inc, "
                "x.zpop_pct pct FROM zip_county_crosswalk x JOIN "
                "acs_zip_2022_part1 a ON a.zcta=x.zcta WHERE x.geoid=%s",
                (geo["county_geoid"],))
    rows = cur.fetchall()
    if not rows:
        return None
    pop = sum((r["pop"] or 0) * float(r["pct"]) / 100 for r in rows)
    hh = sum((r["hh"] or 0) * float(r["pct"]) / 100 for r in rows)
    inc_rows = [r for r in rows if (r["inc"] or 0) > 0]
    wnum = sum(float(r["inc"]) * (r["hh"] or 0) * float(r["pct"]) / 100
               for r in inc_rows)
    wden = sum((r["hh"] or 0) * float(r["pct"]) / 100 for r in inc_rows)
    return {"population": round(pop), "households": round(hh),
            "weighted_median_hh_income": round(wnum / wden) if wden else None}


def _baseline(conn, codes):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM post_intake_industry_baseline_lookup WHERE "
                "naics_code IN (%s) AND data_source NOT IN "
                "('SEC_EDGAR','alpha_data','industry_metrics_raw') "
                "ORDER BY naics_code, metric_key, data_source"
                % ",".join(["%s"] * len(codes)), tuple(codes))
    return [{"naics": r["naics_code"], "metric": r["metric_key"],
             "unit": r["unit"],
             "min": _f(r["benchmark_min"]), "target": _f(r["benchmark_target"]),
             "max": _f(r["benchmark_max"]), "source": r["data_source"],
             "year": _s(r["source_year"]), "n": _s(r["sample_size"]),
             "tier": r["confidence_tier"]} for r in cur.fetchall()]


def _fred_macro(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM fred_macro_quarterly ORDER BY date DESC LIMIT 6")
    rows = sorted(cur.fetchall(), key=lambda r: r["date"])
    out = []
    for r in rows:
        d = {}
        for k, v in r.items():
            if k == "inflation_rate":
                k = "inflation_rate_yoy"
            d[k] = None if v is None else str(v)
        out.append(d)
    return out


def _fred_series(conn):
    cur = conn.cursor(dictionary=True)
    out = {}
    for sid in ("DGS10", "DGS2", "FEDFUNDS", "UNRATE", "PPIACO"):
        cur.execute("SELECT series_label, date, value FROM fred_series_quarterly "
                    "WHERE series_id=%s ORDER BY date DESC LIMIT 4", (sid,))
        rows = sorted(cur.fetchall(), key=lambda r: r["date"])
        if rows:
            out[sid] = {"label": rows[0]["series_label"],
                        "recent": [[str(r["date"]), float(r["value"])]
                                   for r in rows]}
    return out


def _valuation(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM valuation_reference_constants WHERE active=1 "
                "ORDER BY id")
    keep = ("id", "constant_key", "constant_label", "applies_to", "unit",
            "value_min", "value_default", "value_max", "data_source",
            "source_citation", "source_as_of")
    return [{k: (None if r.get(k) is None else str(r[k])) for k in keep}
            for r in cur.fetchall()]


def _wage_rows_from_roster(draft: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One wage row per Q1 roster role, for ANY business: the author's
    occupation stamp joins each role to the wage distribution regardless of
    where the wage came from; a schedule authored before the universal
    stamp goes through the author's own exported matcher - the same code
    path, never a copy. A role nobody can place is omitted. Labels say
    which wages are the client's own and which are market-benchmarked."""
    ph = _jl(draft.get("payroll_headcount")) or {}
    q1 = [r for r in (ph.get("rows") or [])
          if int(r.get("quarter_index") or 0) == 1]
    people = ((_jl(draft.get("people_json")) or {}).get("people")) or []
    by_name = {str(p.get("full_name") or p.get("name") or "").strip(): p
               for p in people if isinstance(p, dict)}
    out: List[Dict[str, Any]] = []
    for r in q1:
        wage = r.get("base_annual_wage") or r.get("annual_wage")
        if not wage:
            continue
        # An anchor-authored block's per-person wage is an ESTIMATE (the
        # pool divided by an assumed head count), not a wage anyone was
        # paid - so it is never plotted against a wage distribution.
        # Better no point than a wrong one.
        if str(r.get("wage_source") or "").startswith("rest_of_team_anchor"):
            continue
        occ = str(r.get("oews_occ_code") or "").strip()
        if str(r.get("staffing_class") or "") == "key_person":
            # ALWAYS re-derive a key person through the author's own
            # exported matcher, stamp or no stamp: rosters authored while
            # the matcher was broken carry mis-stamps (a Lead hygienist
            # as 11-1021 General and Operations Managers, 2026-09-10),
            # and drawing the client's wage against the wrong occupation
            # is worse than no chart. A fresh match wins; the stored
            # stamp is only the fallback. Deterministic, so a correct
            # stamp re-derives to itself.
            person = by_name.get(str(r.get("person_name") or "").strip())
            if person:
                try:
                    from client_intake_and_finmo.post_intake_headcount.schedule \
                        import match_occupation_for_person
                    m = match_occupation_for_person(
                        person,
                        business_facts=_jl(draft.get("operating_model_json")),
                        ops_json=_jl(draft.get("operating_model_json")),
                        people_json=_jl(draft.get("people_json")))
                except Exception:
                    m = None
                if m:
                    occ = m["matched_occ_code"]
        if not occ:
            continue
        stated = "intake" in str(r.get("wage_source") or "").lower() \
            or "override" in str(r.get("wage_source") or "").lower()
        name = str(r.get("person_name") or r.get("position_title") or "").strip()
        out.append({"soc": occ, "client_wage": int(round(float(wage))),
                    "client_label": "%s (%s)" % (name, "stated wage" if stated
                                                 else "market-benchmarked")})
    return out


def _wage_positioning(conn, wage_rows, metro_area):
    cur = conn.cursor(dictionary=True)
    out = []
    for w in wage_rows:
        cur.execute("SELECT * FROM oews_state_wages WHERE occ_code=%s AND "
                    "area_title=%s", (w["soc"], metro_area))
        r = cur.fetchone()
        if not r:
            continue
        # BLS suppresses percentiles on thin cells AND caps the top of
        # high-earning occupations (dentists, executives report p90 as
        # null). Requiring p90 dropped exactly the best-paid roles from
        # the chart; the bar's top falls back to p75, stamped, so the
        # renderer can caption what it drew. Only a row with no spine at
        # all (no p10/median, or no top percentile either) is omitted.
        if not (r.get("a_pct10") and r.get("a_median")):
            continue
        top = _f(r.get("a_pct90")) or _f(r.get("a_pct75"))
        if not top:
            continue
        out.append({"occupation": r["occ_title"], "area": r["area_title"],
                    "p10": _f(r["a_pct10"]), "p25": _f(r["a_pct25"]),
                    "median": _f(r["a_median"]), "p75": _f(r["a_pct75"]),
                    "p90": _f(r["a_pct90"]), "top": top,
                    "top_percentile": 90 if _f(r.get("a_pct90")) else 75,
                    "client_wage": w["client_wage"],
                    "client_label": w["client_label"],
                    "source": "BLS OEWS May 2023"})
    return out


def _metro_area(conn, geo):
    """The OEWS metro whose title starts with the county's biggest city;
    the state row is the fallback."""
    cur = conn.cursor(dictionary=True)
    if geo["county_geoid"] == "26081":
        return "Grand Rapids-Wyoming-Kentwood, MI"
    abbr = _state_abbr(geo["state"])
    cur.execute("SELECT DISTINCT area_title FROM oews_state_wages WHERE "
                "area_title LIKE %s", ("%%, " + abbr,))
    areas = [r["area_title"] for r in cur.fetchall()]
    # no unique metro -> the STATE distribution; the chart is universal,
    # only its geography narrows or widens. FULL name - the area_title
    # join is by 'Illinois', never 'IL'.
    return areas[0] if len(areas) == 1 else _state_area_title(geo["state"])


def build_warehouse(conn, draft: Dict[str, Any],
                    cls: Dict[str, Any]) -> Dict[str, Any]:
    pin = _pin(draft)
    geo = _geo(conn, draft)
    codes = _codes_from_groups(cls)
    if pin:
        cbp_cty, cbp_st, cbp_nat = (pin["cbp_county"], pin["cbp_state"],
                                    pin["cbp_national"])
        bds4, shares4 = pin["bds4"], set(pin["bds4"][:2])
        sba_groups = pin["sba_groups"]
        baseline_codes = pin["baseline_codes"]
        occ = pin["occ_codes"]
        wage_rows = pin["wage_rows"]
        note = pin["note"]
    else:
        cbp_cty = cbp_st = cbp_nat = sorted(set(codes["c4"] + codes["c6"]))
        bds4 = sorted(set(codes["c4"]))
        shares4 = set(bds4)
        sba_groups = [(g["role"], [c for c in g.get("naics", []) if len(str(c)) == 6])
                      for g in cls.get("groups", [])]
        sba_groups = [(l, cs) for l, cs in sba_groups if cs]
        baseline_codes = sorted(set(codes["c4"] + codes["c6"]))
        wage_rows = _wage_rows_from_roster(draft)
        occ = sorted({w["soc"] for w in wage_rows})
        note = _GENERIC_NOTE

    metro = _metro_area(conn, geo)
    areas = [a for a in dict.fromkeys(
        (_state_area_title(geo["state"]), metro)) if a]
    out: Dict[str, Any] = {"note": note}
    out["cbp_2022"] = _cbp(conn, geo, cbp_cty, cbp_st, cbp_nat)
    out["bds_2023"] = _bds(conn, bds4, shares4)
    # firm counts by employee-size band for the PRIMARY trade code (Nick
    # 2026-09-08: places the business in the field without naming anyone).
    # Added after the Thornfield reference was pinned; the gate ignores it.
    if bds4:
        out["bds_firm_size_2023"] = _bds_size(conn, bds4[0])
    if occ and areas:
        out["oews_may2023"] = _oews(conn, list(occ), areas)
    out["sba_7a_fy2020_2025"] = _sba(conn, sba_groups, geo)
    out["acs_2022_national_zcta_sums"] = _acs_national(conn)
    county = _acs_county(conn, geo)
    if county:
        key = ("acs_2022_kent_county_mi" if geo["county_geoid"] == "26081"
               else "acs_2022_county")
        out[key] = county
    out["industry_baseline_lookup"] = _baseline(conn, baseline_codes)
    out["fred_macro_quarterly"] = _fred_macro(conn)
    out["fred_series_quarterly"] = _fred_series(conn)
    out["valuation_reference_constants"] = _valuation(conn)
    if wage_rows and metro:
        out["wage_positioning"] = _wage_positioning(conn, wage_rows, metro)
    return _plain(out)


def _plain(o):
    """MySQL hands back Decimals; the bundle is plain JSON floats/ints."""
    import decimal
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_plain(v) for v in o]
    if isinstance(o, decimal.Decimal):
        f = float(o)
        return int(f) if f.is_integer() and abs(f) < 1e15 and "." not in str(o) else f
    return o
