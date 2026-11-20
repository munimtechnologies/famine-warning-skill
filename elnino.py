#!/usr/bin/env python3
# famine-warning-skill, step 2: a prospective, pre-registered test of FEWS NET's forecasts for
# the very strong 2026-27 El Nino, frozen before any of the forecast months had happened.
# Copyright 2026 Munim, Inc. (MV2). Licensed under the Apache License, Version 2.0 (Apache-2.0).
# Made with AI agents working in MV2's name. Standard library only.
"""Score FEWS NET's 2026-27 El Nino season projections against what happens (PREREG-2.md).

Two modes:
  --freeze   save every FEWS NET projection and classification from round 2026-10 on, with
             file hashes, as a public record of what was forecast before the outcomes existed.
  (default)  grade predictions E1-E9 once the outcome rounds (2027-02 ... 2028-02) exist.

Pairs and metrics come from famine_skill.py (step 1): an area's consecutive current-situation
(CS) classifications o -> t, the projection issued at o whose window contains t, and the
persistence baseline CS(o).
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import random
import sys
import time
from collections import defaultdict

import famine_skill as fs

__version__ = "0.2.0"

M = fs.month_index
S_FIRST_I = M("2026-10")   # first origin round of the El Nino season
S_LAST_I = M("2027-10")    # last origin round
T_LAST_I = M("2028-03")    # last target month
FREEZE_FROM_I = M("2026-10")

# Countries FEWS NET's 2026-27 El Nino special report (6 Oct 2026) names, by region.
GROUPS = {
    "southern_africa": ["AGO", "LSO", "MDG", "MOZ", "MWI", "ZMB", "ZWE"],
    "unimodal_east_africa": ["ETH", "SDN", "SSD", "UGA"],
    "bimodal_east_africa": ["KEN", "SOM"],
    "west_africa": ["BFA", "MLI", "NER", "TCD"],
    "latin_america_caribbean": ["COL", "GTM", "HND", "HTI"],
    "south_asia": ["PAK"],
}
NAMED = sorted({c for v in GROUPS.values() for c in v})

MIN_S_PAIRS = 300
MIN_S_COUNTRIES = 10
MIN_EVENTS = 20
MIN_DET = 30
MIN_AREAS = 50
MIN_MATCHED = 30
MIN_CONTROL = 5


def in_season(p):
    return p["period"] == "post" and S_FIRST_I <= p["origin"] <= S_LAST_I \
        and p["target"] <= T_LAST_I


def det_counts(pairs):
    """Deterioration calls (projection above the current phase) and how many came true."""
    calls = [p for p in pairs if p["pred"] > p["cs0"]]
    return len(calls), sum(1 for p in calls if p["out"] > p["cs0"])


def mean_change(pairs):
    return sum(p["out"] - p["cs0"] for p in pairs) / len(pairs) if pairs else None


def first_cs_in(series, a, b):
    ms = [m for m in sorted(series) if a <= m <= b]
    return series[ms[0]] if ms else None


def share3(cs_by_country, countries, a, b):
    """Share of areas at Phase 3+ in their first CS classification within months a..b."""
    n = k = 0
    for c in countries:
        for series in cs_by_country.get(c, {}).values():
            v = first_cs_in(series, a, b)
            if v is not None:
                n += 1
                k += int(v >= 3)
    return n, (k / n if n else None)


def matched_change3(cs_by_country, countries, a1, b1, a2, b2):
    """Change in the share of areas at Phase 3+ between two windows, same areas only."""
    n = d = 0
    for c in countries:
        for series in cs_by_country.get(c, {}).values():
            v1, v2 = first_cs_in(series, a1, b1), first_cs_in(series, a2, b2)
            if v1 is not None and v2 is not None:
                n += 1
                d += int(v2 >= 3) - int(v1 >= 3)
    return n, (d / n if n else None)


def any_phase(cs_by_country, iso, a, b, phase):
    """(number of CS observations of country iso within a..b, any of them >= phase)."""
    n, found = 0, False
    for series in cs_by_country.get(iso, {}).values():
        for m, v in series.items():
            if a <= m <= b:
                n += 1
                found = found or v >= phase
    return n, found


def _avg(d, keys):
    vals = [d[c] for c in keys if d.get(c) is not None]
    return sum(vals) / len(vals) if vals else None


def did(mc_s, mc_r, named, control):
    """(named - control) mean phase change in the season minus the same in the reference."""
    parts = [_avg(mc_s, named), _avg(mc_s, control), _avg(mc_r, named), _avg(mc_r, control)]
    if any(x is None for x in parts):
        return None
    return (parts[0] - parts[1]) - (parts[2] - parts[3])


def strat_boot(fn, a, b, reps=fs.B, seed=fs.SEED):
    """Percentile 95% CI of fn(sample_a, sample_b), resampling the two lists separately."""
    if not a or not b:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        sa = [a[rng.randrange(len(a))] for _ in a]
        sb = [b[rng.randrange(len(b))] for _ in b]
        v = fn(sa, sb)
        if v is not None:
            vals.append(v)
    if len(vals) < 0.9 * reps:
        return None
    vals.sort()
    return [vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]]


def _r(x, nd=4):
    return None if x is None else round(x, nd)


def analyse(pairs, cs_by_country):
    S, R = defaultdict(list), defaultdict(list)
    for p in pairs:
        if in_season(p):
            S[p["iso3"]].append(p)
        elif p["period"] == "pre":
            R[p["iso3"]].append(p)
    SS = {c: fs.sums(v) for c, v in S.items()}
    RS = {c: fs.sums(v) for c, v in R.items()}
    named_s = sorted(c for c in SS if c in NAMED)
    named_bal = sorted(c for c in named_s if c in RS)
    control_s = sorted(c for c in SS if c not in NAMED)
    control_bal = sorted(c for c in control_s if c in RS)
    DS = {c: det_counts(v) for c, v in S.items()}
    DR = {c: det_counts(v) for c, v in R.items()}
    MC_S = {c: mean_change(v) for c, v in S.items()}
    MC_R = {c: mean_change(v) for c, v in R.items()}

    def det_prec(D, cs_):
        calls = sum(D[c][0] for c in cs_ if c in D)
        return sum(D[c][1] for c in cs_ if c in D) / calls if calls else None

    res = {"countries": {"named_season": named_s, "named_balanced": named_bal,
                         "control_season": control_s, "control_balanced": control_bal}}

    # descriptive table by region (season and reference)
    table = {}
    for g, members in list(GROUPS.items()) + [("control", control_s)]:
        row = {}
        for tag, P, D in (("season", S, DS), ("reference", R, DR)):
            ps = [p for c in members for p in P.get(c, [])]
            d = fs.derive(fs.sums(ps))
            calls, hits = det_counts(ps)
            row[tag] = {"n": d["n"], "acc": _r(d["acc"]), "acc_persist": _r(d["acc_persist"]),
                        "skill_vs_persist": _r(d["skill_vs_persist"]), "bias": _r(d["bias"]),
                        "mean_change": _r(mean_change(ps)), "det_calls": calls,
                        "det_hits": hits, "new_crisis_events": d["new_crisis_events"],
                        "pod": _r(d["pod"]), "pofd": _r(d["pofd"])}
        table[g] = row
    res["regions"] = table

    H = {}

    def nt(why):
        return {"verdict": "not testable", "why": why}

    s_n = sum(SS[c]["n"] for c in named_s)
    s_ok = s_n >= MIN_S_PAIRS and len(named_s) >= MIN_S_COUNTRIES
    bal_n = sum(SS[c]["n"] for c in named_bal)
    bal_ok = bal_n >= MIN_S_PAIRS and len(named_bal) >= MIN_S_COUNTRIES

    # E1 deterioration calls come true at least half the time
    calls = sum(DS[c][0] for c in named_s)
    if calls >= MIN_DET:
        v = det_prec(DS, named_s)
        H["E1"] = {"value": _r(v), "calls": calls,
                   "ci": fs.bootstrap(lambda s: det_prec(DS, s), named_s),
                   "reference": _r(det_prec(DR, named_bal)),
                   "verdict": "true" if v is not None and v >= 0.5 else "false"}
    else:
        H["E1"] = nt("deterioration calls %d" % calls)
    # E2 beat persistence in the season; E8 over-projection in the season
    if s_ok:
        v = fs.country_mean(SS, named_s, "skill_vs_persist")
        ci = fs.bootstrap(lambda s: fs.country_mean(SS, s, "skill_vs_persist"), named_s)
        H["E2"] = {"value": _r(v), "ci": ci,
                   "verdict": "true" if v is not None and v > 0 and ci and ci[0] > 0
                   else "false"}
        v = fs.country_mean(SS, named_s, "bias")
        H["E8"] = {"value": _r(v),
                   "ci": fs.bootstrap(lambda s: fs.country_mean(SS, s, "bias"), named_s),
                   "verdict": "true" if v is not None and v > 0 else "false"}
    else:
        H["E2"] = nt("season pairs %d, countries %d" % (s_n, len(named_s)))
        H["E8"] = nt("season pairs %d, countries %d" % (s_n, len(named_s)))
    # E3 skill vs persistence higher in the El Nino season than in 2021-2024, same countries
    if bal_ok:
        def f3(s):
            a = fs.country_mean(SS, s, "skill_vs_persist")
            b = fs.country_mean(RS, s, "skill_vs_persist")
            return None if a is None or b is None else a - b
        v = f3(named_bal)
        H["E3"] = {"value": _r(v), "ci": fs.bootstrap(f3, named_bal),
                   "verdict": "true" if v is not None and v > 0 else "false"}
    else:
        H["E3"] = nt("balanced countries %d, pairs %d" % (len(named_bal), bal_n))
    # E4 new-crisis detection better than chance in the season
    ev = sum(SS[c]["ev"] for c in named_s)
    if s_ok and ev >= MIN_EVENTS:
        v = fs.pooled(SS, named_s, "peirce")
        ci = fs.bootstrap(lambda s: fs.pooled(SS, s, "peirce"), named_s)
        H["E4"] = {"value": _r(v), "ci": ci, "events": ev,
                   "verdict": "true" if v is not None and v > 0 and ci and ci[0] > 0
                   else "false"}
    else:
        H["E4"] = nt("season new-crisis events %d" % ev)
    # E5 'widespread Crisis' in Southern Africa, Nov 2027 - Mar 2028
    sa = GROUPS["southern_africa"]
    n5, sh5 = share3(cs_by_country, sa, M("2027-11"), M("2028-03"))
    n5r, sh5r = share3(cs_by_country, sa, M("2023-11"), M("2024-03"))
    if n5 >= MIN_AREAS:
        H["E5"] = {"value": _r(sh5), "areas": n5, "after_2023_24_el_nino": _r(sh5r),
                   "areas_2023_24": n5r,
                   "verdict": "true" if sh5 >= 0.30 else "false"}
    else:
        H["E5"] = nt("Southern Africa areas with a CS in Nov 2027-Mar 2028: %d" % n5)
    # E6 El Nino countries worsen more than the other FEWS NET countries (diff-in-diff)
    if len(named_bal) >= MIN_S_COUNTRIES and len(control_bal) >= MIN_CONTROL:
        v = did(MC_S, MC_R, named_bal, control_bal)
        H["E6"] = {"value": _r(v),
                   "ci": strat_boot(lambda a, b: did(MC_S, MC_R, a, b), named_bal, control_bal),
                   "verdict": "true" if v is not None and v >= 0.10 else "false"}
    else:
        H["E6"] = nt("named balanced %d, control balanced %d" % (len(named_bal),
                                                                 len(control_bal)))
    # E7 no Famine (Phase 5) classification in Somalia, Jan-Jun 2027
    n7, f7 = any_phase(cs_by_country, "SOM", M("2027-01"), M("2027-06"), 5)
    H["E7"] = nt("no Somalia CS in Jan-Jun 2027") if n7 == 0 else \
        {"observations": n7, "phase5_found": f7, "verdict": "false" if f7 else "true"}
    # E9 more of unimodal East Africa in Crisis+ in mid-2027 than in mid-2026, same areas
    n9, d9 = matched_change3(cs_by_country, GROUPS["unimodal_east_africa"],
                             M("2026-05"), M("2026-08"), M("2027-05"), M("2027-08"))
    if n9 >= MIN_MATCHED:
        H["E9"] = {"value": _r(d9), "areas": n9,
                   "verdict": "true" if d9 > 0 else "false"}
    else:
        H["E9"] = nt("matched areas %d" % n9)
    res["hypotheses"] = H
    return res


def freeze_rows(iso3, cs, proj):
    rows = []
    for fnid, rounds in proj.items():
        for r, wins in rounds.items():
            if r < FREEZE_FROM_I:
                continue
            for (s, e, scen), ph in wins.items():
                rows.append((iso3, fnid, fs.ym(r), scen, fs.ym(s), fs.ym(e), ph))
    for fnid, series in cs.items():
        for m, ph in series.items():
            if m >= FREEZE_FROM_I:
                rows.append((iso3, fnid, fs.ym(m), "CS", fs.ym(m), fs.ym(m), ph))
    return sorted(rows)


def _proj_key(row):
    return tuple(row[:6])


def frozen_check(current_rows, frozen_path):
    """Compare round-2026-10 projections now with the frozen copy."""
    def sel(rows):
        return {_proj_key(r): int(r[6]) for r in rows
                if r[2] == "2026-10" and r[3] in ("ML1", "ML2")}
    with gzip.open(frozen_path, "rt", encoding="utf-8") as f:
        rd = csv.reader(f)
        next(rd)
        frozen = sel([tuple(r) for r in rd])
    now = sel(current_rows)
    changed = sorted("|".join(k) for k in frozen if k in now and now[k] != frozen[k])
    return {"frozen": len(frozen), "current": len(now),
            "missing_now": sum(1 for k in frozen if k not in now),
            "new_now": sum(1 for k in now if k not in frozen),
            "changed_phase": len(changed), "changed_examples": changed[:50]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--input-dir", default=None)
    ap.add_argument("--countries", default="")
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--frozen", default="frozen_2026-10.csv.gz",
                    help="frozen copy to check round-2026-10 projections against (grade mode)")
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    t0 = time.time()
    if a.input_dir:
        with open(os.path.join(a.input_dir, "index.json"), "rb") as f:
            idx_raw = f.read()
    else:
        idx_raw = fs.fetch(fs.MIRROR + "/index.json")
    index = json.loads(idx_raw.decode("utf-8"))
    snap = (index.get("generated_at") or "undated")[:10]
    ddir = os.path.join(a.data_dir, "fewsnet-mirror-" + snap)
    os.makedirs(ddir, exist_ok=True)
    want = {c.strip().upper() for c in a.countries.split(",") if c.strip()}
    meta = {"version": __version__, "famine_skill_version": fs.__version__,
            "mode": "freeze" if a.freeze else "grade", "source": fs.MIRROR,
            "index_generated_at": index.get("generated_at"),
            "index_sha256": hashlib.sha256(idx_raw).hexdigest(), "files": {}, "errors": {}}
    pairs, cs_by_country, frozen = [], {}, []
    for c in index.get("countries", []):
        iso = c["iso3"]
        if want and iso not in want:
            continue
        try:
            doc, sha, size = fs.load_country(iso, ddir, a.input_dir)
        except Exception as e:  # noqa: BLE001 - record and continue
            meta["errors"][iso] = str(e)[:300]
            continue
        meta["files"][iso] = {"sha256": sha, "bytes": size,
                              "generated_at": doc.get("generated_at")}
        cs, proj, _ = fs.parse_country(doc)
        del doc
        frozen.extend(freeze_rows(iso, cs, proj))
        if a.freeze:
            continue
        p, _, _ = fs.build_pairs(iso, cs, proj)
        pairs.extend(p)
        cs_by_country[iso] = {k: dict(v) for k, v in cs.items()}
        print("%s pairs=%d" % (iso, len(p)), flush=True)
    meta["seconds"] = round(time.time() - t0, 1)
    if a.freeze:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["iso3", "fnid", "round", "scenario", "start", "end", "phase"])
        w.writerows(frozen)
        data = buf.getvalue().encode("utf-8")
        with gzip.open(os.path.join(a.out_dir, "frozen_2026-10.csv.gz"), "wb") as f:
            f.write(data)
        meta["frozen_rows"] = len(frozen)
        meta["frozen_csv_sha256"] = hashlib.sha256(data).hexdigest()
        meta["frozen_rounds"] = sorted({r[2] for r in frozen})
        with open(os.path.join(a.out_dir, "freeze_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1, sort_keys=True)
        print("frozen %d rows, rounds %s" % (len(frozen), meta["frozen_rounds"]), flush=True)
        return 0
    if a.frozen and os.path.exists(a.frozen):
        meta["frozen_check"] = frozen_check(frozen, a.frozen)
    else:
        meta["frozen_check"] = "frozen copy not found: %s" % a.frozen
    res = analyse(pairs, cs_by_country)
    res["meta"] = meta
    with open(os.path.join(a.out_dir, "elnino_results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    for hid in sorted(res["hypotheses"], key=lambda h: int(h[1:])):
        print(hid, json.dumps(res["hypotheses"][hid]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
