#!/usr/bin/env python3
# famine-warning-skill: did the world's main famine early-warning system keep its skill
# after the 2025 blackout, and does it see NEW food crises coming better than "nothing changes"?
# Copyright 2026 Munim, Inc. (MV2). Licensed under the Apache License, Version 2.0 (Apache-2.0).
# Made with AI agents working in MV2's name. Standard library only.
"""Score FEWS NET's area-level food-insecurity projections against what happened next.

Data: FEWS NET's IPC-compatible classifications (Source: FEWS NET, fews.net/data), read from
OCHA-DAP's public daily mirror of the FEWS NET Data Warehouse
(https://ocha-dap.github.io/ds-fewsnet-mirror/data/classification/<ISO3>.json).

Design (frozen in PREREGISTRATION.md before any accuracy was computed):
- Unit = one FEWS NET area (FNID). For each area, consecutive current-situation (CS)
  classifications o -> t form a pair. The forecast is the projection (ML1/ML2) issued in round o
  whose window contains month t; the outcome is the CS phase at t.
- Baselines: persistence (CS at o) and seasonal persistence (CS at t - 12 months).
- Periods: pre (o >= 2021-01, t <= 2024-12), post (o >= 2025-07), blackout (o <= 2024-12,
  t >= 2025-07; forecast = the last pre-blackout projection with the latest-ending window).
- Pre and post pairs more than 6 months apart are 'irregular' and excluded.
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
import urllib.request
from collections import defaultdict

__version__ = "0.1.0"

MIRROR = "https://ocha-dap.github.io/ds-fewsnet-mirror/data"
UA = "famine-warning-skill/%s (MV2, Munim, Inc.; mv2@munimtech.com)" % __version__
SCALES = ("IPC 3.0", "IPC 3.1")
SEED = 20261119
B = 2000
PRE_FIRST = "2021-01"
PRE_LAST = "2024-12"
POST_FIRST = "2025-07"
MAX_GAP = 6
UPD_MAX_LEAD = 3

# minimum samples for a hypothesis to be graded (else "not testable")
MIN_PAIRS = 500
MIN_COUNTRIES = 10
MIN_EVENTS = 20
MIN_PRED4 = 20
MIN_BLACKOUT3 = 50


def month_index(ym):
    """'YYYY-MM' or 'YYYY-MM-DD' -> months since year 0."""
    return int(ym[0:4]) * 12 + int(ym[5:7]) - 1


def ym(idx):
    return "%04d-%02d" % (idx // 12, idx % 12 + 1)


PRE_FIRST_I = month_index(PRE_FIRST)
PRE_LAST_I = month_index(PRE_LAST)
POST_FIRST_I = month_index(POST_FIRST)


# ----------------------------------------------------------------------------- parsing

def parse_country(doc):
    """Decode one mirror file.

    Returns (cs, proj, stats):
      cs[fnid][month] = phase (max over duplicate rows)
      proj[fnid][round_month][(start_m, end_m, scenario)] = phase (max over duplicates)
    Only IPC 3.0/3.1 rows of non-admin0 units with an integer phase 1..5 are kept.
    """
    cols = doc["columns"]
    ix = {c: i for i, c in enumerate(cols)}
    units = doc["units"]
    stats = defaultdict(int)
    cs = defaultdict(dict)
    proj = defaultdict(lambda: defaultdict(dict))
    for row in doc["rows"]:
        stats["rows"] += 1
        if row[ix["scale"]] not in SCALES:
            stats["skip_scale"] += 1
            continue
        u = units[row[ix["u"]]]
        fnid = u[0]
        utype = u[2] if len(u) > 2 else ""
        if utype == "admin0":
            stats["skip_admin0"] += 1
            continue
        ph = row[ix["phase"]]
        if isinstance(ph, bool) or not isinstance(ph, (int, float)) or int(ph) != ph \
                or not 1 <= ph <= 5:
            stats["skip_phase"] += 1
            continue
        ph = int(ph)
        scen = row[ix["scenario"]]
        mi = month_index(row[ix["reporting_date"]])
        if scen == "CS":
            old = cs[fnid].get(mi)
            if old is not None and old != ph:
                stats["cs_conflicts"] += 1
            cs[fnid][mi] = max(ph, old or 0)
            stats["cs_rows"] += 1
        elif scen in ("ML1", "ML2"):
            key = (month_index(row[ix["projection_start"]]),
                   month_index(row[ix["projection_end"]]), scen)
            d = proj[fnid][mi]
            old = d.get(key)
            if old is not None and old != ph:
                stats["proj_conflicts"] += 1
            d[key] = max(ph, old or 0)
            stats["proj_rows"] += 1
        else:
            stats["skip_scenario"] += 1
    return cs, proj, stats


def pick_projection(windows, t):
    """Among {(start, end, scen): phase} pick the window containing month t
    (latest start, then ML2 over ML1, then highest phase). Returns (phase, scen) or (None, None)."""
    best = None
    for (s, e, scen), ph in (windows or {}).items():
        if s <= t <= e:
            k = (s, scen == "ML2", ph)
            if best is None or k > best[0]:
                best = (k, ph, scen)
    if best is None:
        return None, None
    return best[1], best[2]


def last_pregap_projection(rounds):
    """rounds = {round_month: {(s, e, scen): phase}}. Use the latest round <= PRE_LAST and,
    within it, the window ending latest (then ML2, then highest phase)."""
    pre = [r for r in rounds if r <= PRE_LAST_I and rounds[r]]
    if not pre:
        return None, None, None
    r = max(pre)
    best = None
    for (s, e, scen), ph in rounds[r].items():
        k = (e, scen == "ML2", ph)
        if best is None or k > best[0]:
            best = (k, ph, scen)
    return best[1], best[2], r


def period_of(o, t):
    if o >= PRE_FIRST_I and t <= PRE_LAST_I:
        return "pre"
    if o >= POST_FIRST_I:
        return "post"
    if o <= PRE_LAST_I and t >= POST_FIRST_I:
        return "blackout"
    return "other"


def build_pairs(iso3, cs, proj):
    """Return (pairs, update_pairs, counts) for one country."""
    pairs, upd = [], []
    counts = defaultdict(int)
    for fnid in sorted(cs):
        series = cs[fnid]
        months = sorted(series)
        prounds = proj.get(fnid, {})
        for i in range(len(months) - 1):
            o, t = months[i], months[i + 1]
            per = period_of(o, t)
            if per == "other":
                counts["other"] += 1
                continue
            if per in ("pre", "post") and t - o > MAX_GAP:
                counts["irregular"] += 1
                continue
            if per == "blackout":
                pred, scen, r = last_pregap_projection(prounds)
            else:
                pred, scen = pick_projection(prounds.get(o), t)
                r = o
            if pred is None:
                counts[per + "_no_projection"] += 1
                continue
            counts[per] += 1
            pairs.append({"iso3": iso3, "fnid": fnid, "origin": o, "target": t,
                          "period": per, "cs0": series[o], "out": series[t], "pred": pred,
                          "scen": scen, "seas": series.get(t - 12), "lead": t - r})
        # secondary: monthly-update projections (rounds without a CS for this area)
        for r in sorted(prounds):
            if r in series:
                continue
            nxt = [m for m in months if m > r]
            prv = [m for m in months if m < r]
            if not nxt or not prv:
                continue
            t, p = nxt[0], prv[-1]
            if t - r > UPD_MAX_LEAD or r - p > MAX_GAP:
                continue
            per = period_of(r, t)
            if per not in ("pre", "post") or (per == "pre" and p < PRE_FIRST_I):
                continue
            pred, scen = pick_projection(prounds[r], t)
            if pred is None:
                continue
            upd.append({"iso3": iso3, "fnid": fnid, "origin": r, "target": t, "period": per,
                        "cs0": series[p], "out": series[t], "pred": pred, "scen": scen,
                        "seas": series.get(t - 12), "lead": t - r})
    return pairs, upd, counts


# ----------------------------------------------------------------------------- metrics

KEYS = ("n", "hit", "abs_f", "hit_p", "abs_p", "bias", "n_s", "abs_f_s", "abs_s",
        "ev", "ev_hit", "non", "non_fa", "p4", "p4_hit", "o4", "o4_hit")


def sums(pairs):
    s = dict.fromkeys(KEYS, 0)
    for p in pairs:
        pr, o, c = p["pred"], p["out"], p["cs0"]
        s["n"] += 1
        s["hit"] += int(pr == o)
        s["abs_f"] += abs(pr - o)
        s["hit_p"] += int(c == o)
        s["abs_p"] += abs(c - o)
        s["bias"] += pr - o
        if p.get("seas") is not None:
            s["n_s"] += 1
            s["abs_f_s"] += abs(pr - o)
            s["abs_s"] += abs(p["seas"] - o)
        if c <= 2:
            if o >= 3:
                s["ev"] += 1
                s["ev_hit"] += int(pr >= 3)
            else:
                s["non"] += 1
                s["non_fa"] += int(pr >= 3)
        if pr >= 4:
            s["p4"] += 1
            s["p4_hit"] += int(o >= 4)
        if o >= 4:
            s["o4"] += 1
            s["o4_hit"] += int(pr >= 4)
    return s


def add_sums(list_of_sums):
    tot = dict.fromkeys(KEYS, 0)
    for s in list_of_sums:
        for k in KEYS:
            tot[k] += s[k]
    return tot


def derive(s):
    def r(a, b):
        return s[a] / s[b] if s[b] else None
    m = {"n": s["n"], "acc": r("hit", "n"), "acc_persist": r("hit_p", "n"),
         "mae": r("abs_f", "n"), "mae_persist": r("abs_p", "n"), "bias": r("bias", "n"),
         "n_seasonal": s["n_s"], "mae_on_seasonal": r("abs_f_s", "n_s"),
         "mae_seasonal": r("abs_s", "n_s"), "new_crisis_events": s["ev"],
         "pod": r("ev_hit", "ev"), "pofd": r("non_fa", "non"),
         "precision_4plus": r("p4_hit", "p4"), "recall_4plus": r("o4_hit", "o4"),
         "n_pred_4plus": s["p4"], "n_out_4plus": s["o4"]}
    m["skill_vs_persist"] = (m["mae_persist"] - m["mae"]) if s["n"] else None
    m["skill_vs_seasonal"] = (m["mae_seasonal"] - m["mae_on_seasonal"]) if s["n_s"] else None
    m["peirce"] = (m["pod"] - m["pofd"]) if (m["pod"] is not None and m["pofd"] is not None) \
        else None
    return m


def country_mean(per_country, countries, metric):
    vals = []
    for c in countries:
        v = derive(per_country[c])[metric]
        if v is not None:
            vals.append(v)
    return sum(vals) / len(vals) if vals else None


def pooled(per_country, countries, metric):
    return derive(add_sums([per_country[c] for c in countries]))[metric]


def bootstrap(fn, countries, b=B, seed=SEED):
    """Percentile 95% CI of fn(sample) over country resamples. None if too many undefined."""
    if not countries:
        return None
    rng = random.Random(seed)
    vals = []
    k = len(countries)
    for _ in range(b):
        samp = [countries[rng.randrange(k)] for _ in range(k)]
        v = fn(samp)
        if v is not None:
            vals.append(v)
    if len(vals) < 0.9 * b:
        return None
    vals.sort()
    return [vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]]


def confusion(pairs, key="pred"):
    m = [[0] * 5 for _ in range(5)]
    for p in pairs:
        m[p[key] - 1][p["out"] - 1] += 1
    return m


def _r(x, nd=4):
    return None if x is None else round(x, nd)


# ----------------------------------------------------------------------------- analysis

def analyse(pairs, upd):
    by = {"pre": defaultdict(list), "post": defaultdict(list), "blackout": defaultdict(list)}
    for p in pairs:
        by[p["period"]][p["iso3"]].append(p)
    S = {per: {c: sums(v) for c, v in d.items()} for per, d in by.items()}
    pre_c = sorted(c for c in S["pre"] if S["pre"][c]["n"] > 0)
    post_c = sorted(c for c in S["post"] if S["post"][c]["n"] > 0)
    bal = sorted(set(pre_c) & set(post_c))

    def summary(per, countries):
        if not countries:
            return None
        out = {"countries": len(countries),
               "pooled": {k: _r(v) for k, v in
                          derive(add_sums([S[per][c] for c in countries])).items()}}
        out["country_mean"] = {m: _r(country_mean(S[per], countries, m)) for m in
                               ("acc", "acc_persist", "mae", "mae_persist", "bias",
                                "skill_vs_persist", "skill_vs_seasonal", "peirce")}
        return out

    res = {"periods": {
        "pre_all": summary("pre", pre_c), "post_all": summary("post", post_c),
        "pre_balanced": summary("pre", bal), "post_balanced": summary("post", bal)},
        "countries": {"pre": pre_c, "post": post_c, "balanced": bal}}

    # per-country table
    table = []
    for c in sorted(set(pre_c) | set(post_c)):
        row = {"iso3": c}
        for per in ("pre", "post"):
            if c in S[per]:
                d = derive(S[per][c])
                for m in ("n", "acc", "acc_persist", "skill_vs_persist", "bias",
                          "new_crisis_events", "pod", "pofd"):
                    row[per + "_" + m] = _r(d[m])
        table.append(row)
    res["per_country"] = table

    # blackout descriptives
    bl = [p for d in by["blackout"].values() for p in d]
    b3 = [p for p in bl if p["out"] >= 3]
    b4 = [p for p in bl if p["out"] >= 4]
    unseen3 = [p for p in b3 if p["cs0"] <= 2 and p["pred"] <= 2]
    res["blackout"] = {
        "pairs": len(bl), "countries": len(by["blackout"]),
        "origin_months": sorted({ym(p["origin"]) for p in bl}),
        "target_months": sorted({ym(p["target"]) for p in bl}),
        "out3plus": len(b3), "unseen_new_crisis": len(unseen3),
        "unseen_share": _r(len(unseen3) / len(b3)) if b3 else None,
        "out4plus": len(b4), "out4plus_pred_le3": sum(1 for p in b4 if p["pred"] <= 3),
        "pooled": {k: _r(v) for k, v in derive(sums(bl)).items()} if bl else None,
        "unseen_by_country": dict(sorted(_count(unseen3).items()))}

    # secondary: update projections
    res["update_projections"] = {}
    for per in ("pre", "post"):
        u = [p for p in upd if p["period"] == per and p["iso3"] in bal]
        res["update_projections"][per] = {k: _r(v) for k, v in derive(sums(u)).items()} \
            if u else None

    res["confusion"] = {per: {"fewsnet": confusion([p for d in by[per].values() for p in d]),
                              "persistence": confusion([p for d in by[per].values() for p in d],
                                                       "cs0")}
                        for per in ("pre", "post", "blackout")}
    res["hypotheses"] = grade(S, pre_c, bal, res)
    return res


def _count(ps):
    d = defaultdict(int)
    for p in ps:
        d[p["iso3"]] += 1
    return d


def grade(S, pre_c, bal, res):
    H = {}
    pre_n = sum(S["pre"][c]["n"] for c in pre_c)
    post_n = sum(S["post"][c]["n"] for c in bal)
    pre_ok = pre_n >= MIN_PAIRS and len(pre_c) >= MIN_COUNTRIES
    cmp_ok = post_n >= MIN_PAIRS and len(bal) >= MIN_COUNTRIES

    def ev(per, cs_):
        return sum(S[per][c]["ev"] for c in cs_)

    def p4(per, cs_):
        return sum(S[per][c]["p4"] for c in cs_)

    def nt(why):
        return {"verdict": "not testable", "why": why}

    def cm(per, cs_, m):
        return lambda samp: country_mean(S[per], samp, m)

    def pl(per, m):
        return lambda samp: pooled(S[per], samp, m)

    def diff(f_post, f_pre):
        def f(samp):
            a, b = f_post(samp), f_pre(samp)
            return None if a is None or b is None else a - b
        return f

    # F1
    if pre_ok:
        v = country_mean(S["pre"], pre_c, "acc")
        H["F1"] = {"value": _r(v), "ci": bootstrap(cm("pre", pre_c, "acc"), pre_c),
                   "verdict": "true" if v is not None and v >= 0.70 else "false"}
    else:
        H["F1"] = nt("pre pairs %d, countries %d" % (pre_n, len(pre_c)))
    # F2, F3
    for hid, m in (("F2", "skill_vs_persist"), ("F3", "skill_vs_seasonal")):
        if pre_ok:
            v = country_mean(S["pre"], pre_c, m)
            ci = bootstrap(cm("pre", pre_c, m), pre_c)
            ok = v is not None and v > 0 and ci is not None and ci[0] > 0
            H[hid] = {"value": _r(v), "ci": ci, "verdict": "true" if ok else "false"}
        else:
            H[hid] = nt("pre sample too small")
    # F4
    if pre_ok and ev("pre", pre_c) >= MIN_EVENTS:
        v = pooled(S["pre"], pre_c, "peirce")
        ci = bootstrap(pl("pre", "peirce"), pre_c)
        H["F4"] = {"value": _r(v), "ci": ci, "events": ev("pre", pre_c),
                   "verdict": "true" if v is not None and v > 0 and ci and ci[0] > 0
                   else "false"}
    else:
        H["F4"] = nt("pre new-crisis events %d" % ev("pre", pre_c))
    # F5, F6, F10 (balanced panel, country means)
    if cmp_ok:
        f = diff(cm("post", bal, "acc"), cm("pre", bal, "acc"))
        v = f(bal)
        H["F5"] = {"value": _r(v), "ci": bootstrap(f, bal),
                   "verdict": "true" if v is not None and abs(v) <= 0.05 else "false"}
        f = diff(cm("post", bal, "skill_vs_persist"), cm("pre", bal, "skill_vs_persist"))
        v = f(bal)
        H["F6"] = {"value": _r(v), "ci": bootstrap(f, bal),
                   "verdict": "true" if v is not None and v < 0 else "false"}
        bpre = country_mean(S["pre"], bal, "bias")
        bpost = country_mean(S["post"], bal, "bias")
        H["F10"] = {"pre": _r(bpre), "post": _r(bpost),
                    "ci_pre": bootstrap(cm("pre", bal, "bias"), bal),
                    "ci_post": bootstrap(cm("post", bal, "bias"), bal),
                    "verdict": "true" if bpre is not None and bpost is not None
                    and bpre > 0 and bpost > 0 else "false"}
    else:
        for hid in ("F5", "F6", "F10"):
            H[hid] = nt("balanced countries %d, post pairs %d" % (len(bal), post_n))
    # F7
    if cmp_ok and ev("pre", bal) >= MIN_EVENTS and ev("post", bal) >= MIN_EVENTS:
        f = diff(pl("post", "peirce"), pl("pre", "peirce"))
        v = f(bal)
        H["F7"] = {"value": _r(v), "ci": bootstrap(f, bal),
                   "events_pre": ev("pre", bal), "events_post": ev("post", bal),
                   "verdict": "true" if v is not None and v <= -0.05 else "false"}
    else:
        H["F7"] = nt("events pre %d post %d" % (ev("pre", bal), ev("post", bal)))
    # F8
    if cmp_ok and p4("pre", bal) >= MIN_PRED4 and p4("post", bal) >= MIN_PRED4:
        a = pooled(S["pre"], bal, "precision_4plus")
        b = pooled(S["post"], bal, "precision_4plus")
        H["F8"] = {"pre": _r(a), "post": _r(b),
                   "ci_pre": bootstrap(pl("pre", "precision_4plus"), bal),
                   "ci_post": bootstrap(pl("post", "precision_4plus"), bal),
                   "verdict": "true" if a is not None and b is not None and a < 0.5 and b < 0.5
                   else "false"}
    else:
        H["F8"] = nt("projected 4+ pre %d post %d" % (p4("pre", bal), p4("post", bal)))
    # F9
    bo = res["blackout"]
    if bo["out3plus"] >= MIN_BLACKOUT3:
        H["F9"] = {"value": bo["unseen_share"], "out3plus": bo["out3plus"],
                   "verdict": "true" if bo["unseen_share"] >= 0.10 else "false"}
    else:
        H["F9"] = nt("blackout areas at phase 3+: %d" % bo["out3plus"])
    return H


# ----------------------------------------------------------------------------- I/O

def fetch(url, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retry any network error
            last = e
            time.sleep(10 * (k + 1))
    raise RuntimeError("fetch failed %s: %s" % (url, last))


def load_country(iso3, ddir, input_dir=None):
    if input_dir:
        path = os.path.join(input_dir, iso3 + ".json")
        with open(path, "rb") as f:
            raw = f.read()
    else:
        path = os.path.join(ddir, iso3 + ".json")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, "rb") as f:
                raw = f.read()
        else:
            raw = fetch("%s/classification/%s.json" % (MIRROR, iso3))
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, path)
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest(), len(raw)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--input-dir", default=None,
                    help="read index.json and <ISO3>.json from here instead of the mirror")
    ap.add_argument("--countries", default="", help="comma-separated ISO3 subset")
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    t0 = time.time()
    if a.input_dir:
        with open(os.path.join(a.input_dir, "index.json"), "rb") as f:
            idx_raw = f.read()
    else:
        idx_raw = fetch(MIRROR + "/index.json")
    index = json.loads(idx_raw.decode("utf-8"))
    snap = (index.get("generated_at") or "undated")[:10]
    ddir = os.path.join(a.data_dir, "fewsnet-mirror-" + snap)
    os.makedirs(ddir, exist_ok=True)
    with open(os.path.join(ddir, "index.json"), "wb") as f:
        f.write(idx_raw)
    want = {c.strip().upper() for c in a.countries.split(",") if c.strip()}
    meta = {"version": __version__, "source": MIRROR, "index_generated_at":
            index.get("generated_at"), "index_sha256": hashlib.sha256(idx_raw).hexdigest(),
            "files": {}, "errors": {}, "parse": {}, "pair_counts": {}}
    pairs, upd = [], []
    for c in index.get("countries", []):
        iso = c["iso3"]
        if want and iso not in want:
            continue
        try:
            doc, sha, size = load_country(iso, ddir, a.input_dir)
        except Exception as e:  # noqa: BLE001 - record and continue
            meta["errors"][iso] = str(e)[:300]
            continue
        meta["files"][iso] = {"sha256": sha, "bytes": size, "generated_at":
                              doc.get("generated_at")}
        cs, proj, st = parse_country(doc)
        del doc
        p, u, cnt = build_pairs(iso, cs, proj)
        meta["parse"][iso] = dict(st)
        meta["pair_counts"][iso] = dict(cnt)
        pairs.extend(p)
        upd.extend(u)
        print("%s rows=%d pairs=%d upd=%d %s" % (iso, st["rows"], len(p), len(u), dict(cnt)),
              flush=True)
    res = analyse(pairs, upd)
    meta["seconds"] = round(time.time() - t0, 1)
    meta["n_pairs"] = len(pairs)
    meta["n_update_pairs"] = len(upd)
    res["meta"] = meta
    with open(os.path.join(a.out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["iso3", "fnid", "period", "origin", "target", "lead", "scenario", "cs0",
                "pred", "out", "seasonal"])
    for p in pairs:
        w.writerow([p["iso3"], p["fnid"], p["period"], ym(p["origin"]), ym(p["target"]),
                    p["lead"], p["scen"], p["cs0"], p["pred"], p["out"],
                    "" if p["seas"] is None else p["seas"]])
    with gzip.open(os.path.join(a.out_dir, "pairs.csv.gz"), "wt", encoding="utf-8",
                   newline="") as f:
        f.write(buf.getvalue())
    for hid in sorted(res["hypotheses"], key=lambda h: int(h[1:])):
        print(hid, json.dumps(res["hypotheses"][hid]), flush=True)
    print("done: %d pairs, %d update pairs, %d countries with errors, %.0fs" % (
        len(pairs), len(upd), len(meta["errors"]), meta["seconds"]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
