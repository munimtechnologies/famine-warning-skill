# Offline tests for famine_skill.py (Apache-2.0). Made with AI agents working in MV2's name.
import famine_skill as fs  # noqa: I001 - import the module under test first

import gzip
import json
import os
import tempfile
import unittest

COLS = ["u", "scale", "scenario", "assistance", "reporting_date", "projection_start",
        "projection_end", "doc", "st", "phase"]


def R(u, scen, rep, s, e, ph, scale="IPC 3.1"):
    return [u, scale, scen, 0, rep, s, e, 0, 0, ph]


def synthetic():
    units = [["XX", "Xland", "admin0"], ["XX2020A01", "Zone A", "fsc_admin_lhz"],
             ["XX2020A02", "Zone B", "fsc_admin_lhz"]]
    rows = [
        # ignored rows
        R(0, "ML", "2026-02", "2026-08-01", "2026-08-31", 4, "IPC Highest Household"),
        R(0, "CS", "2022-02", "2022-02-01", "2022-02-28", 3),          # admin0
        R(2, "CS", "2022-02", "2022-02-01", "2022-02-28", None),       # null phase
        # Zone A
        R(1, "CS", "2022-02", "2022-02-01", "2022-02-28", 2),
        R(1, "ML1", "2022-02", "2022-02-01", "2022-05-31", 2),
        R(1, "ML2", "2022-02", "2022-06-01", "2022-09-30", 3),
        R(1, "ML1", "2022-04", "2022-04-01", "2022-05-31", 2),         # update round
        R(1, "ML2", "2022-04", "2022-06-01", "2022-09-30", 2),
        R(1, "CS", "2022-06", "2022-06-01", "2022-06-30", 3),
        R(1, "CS", "2024-10", "2024-10-01", "2024-10-31", 2),          # irregular from 2022-06
        R(1, "ML1", "2024-10", "2024-10-01", "2025-01-31", 2),
        R(1, "ML2", "2024-10", "2025-02-01", "2025-05-31", 2),
        R(1, "CS", "2025-10", "2025-10-01", "2025-10-31", 3),          # blackout outcome
        R(1, "ML2", "2025-10", "2026-02-01", "2026-05-31", 4),
        R(1, "CS", "2026-02", "2026-02-01", "2026-02-28", 4),          # post outcome
        # Zone B
        R(2, "CS", "2021-10", "2021-10-01", "2021-10-31", 1),
        R(2, "CS", "2022-02", "2022-02-01", "2022-02-28", 1),
        R(2, "CS", "2022-02", "2022-02-01", "2022-02-28", 2),          # duplicate -> max 2
        R(2, "ML2", "2022-02", "2022-06-01", "2022-09-30", 1),
        R(2, "CS", "2022-06", "2022-06-01", "2022-06-30", 1),
        R(2, "ML2", "2022-06", "2022-10-01", "2023-01-31", 2),
        R(2, "CS", "2022-10", "2022-10-01", "2022-10-31", 2),
    ]
    return {"generated_at": "2026-11-19T05:22:47+00:00", "iso3": "XXX", "units": units,
            "docs": ["d"], "statuses": ["Collected"], "columns": COLS, "rows": rows}


M = fs.month_index


class TestParse(unittest.TestCase):
    def test_month_index(self):
        self.assertEqual(M("2026-10"), 2026 * 12 + 9)
        self.assertEqual(M("2026-10-31"), M("2026-10"))
        self.assertEqual(fs.ym(M("2025-01")), "2025-01")

    def test_parse_filters_and_duplicates(self):
        cs, proj, st = fs.parse_country(synthetic())
        self.assertEqual(st["skip_scale"], 1)
        self.assertEqual(st["skip_admin0"], 1)
        self.assertEqual(st["skip_phase"], 1)
        self.assertEqual(st["cs_conflicts"], 1)
        self.assertNotIn("XX", cs)
        self.assertEqual(cs["XX2020A02"][M("2022-02")], 2)
        self.assertEqual(proj["XX2020A01"][M("2022-02")][(M("2022-06"), M("2022-09"), "ML2")], 3)

    def test_pick_projection(self):
        w = {(M("2022-02"), M("2022-05"), "ML1"): 2, (M("2022-06"), M("2022-09"), "ML2"): 3}
        self.assertEqual(fs.pick_projection(w, M("2022-06")), (3, "ML2"))
        self.assertEqual(fs.pick_projection(w, M("2022-03")), (2, "ML1"))
        self.assertEqual(fs.pick_projection(w, M("2023-01")), (None, None))
        self.assertEqual(fs.pick_projection(None, M("2023-01")), (None, None))

    def test_period(self):
        self.assertEqual(fs.period_of(M("2022-02"), M("2022-06")), "pre")
        self.assertEqual(fs.period_of(M("2025-10"), M("2026-02")), "post")
        self.assertEqual(fs.period_of(M("2024-10"), M("2025-10")), "blackout")
        self.assertEqual(fs.period_of(M("2020-10"), M("2021-02")), "other")


class TestPairs(unittest.TestCase):
    def setUp(self):
        cs, proj, _ = fs.parse_country(synthetic())
        self.pairs, self.upd, self.cnt = fs.build_pairs("XXX", cs, proj)

    def get(self, fnid, o):
        return [p for p in self.pairs if p["fnid"] == fnid and p["origin"] == M(o)]

    def test_counts(self):
        per = [p["period"] for p in self.pairs]
        self.assertEqual(per.count("pre"), 3)
        self.assertEqual(per.count("post"), 1)
        self.assertEqual(per.count("blackout"), 1)
        self.assertEqual(self.cnt["irregular"], 1)
        self.assertEqual(self.cnt["pre_no_projection"], 1)

    def test_pre_pair(self):
        (p,) = self.get("XX2020A01", "2022-02")
        self.assertEqual((p["cs0"], p["pred"], p["out"], p["scen"], p["lead"]), (2, 3, 3, "ML2", 4))
        self.assertIsNone(p["seas"])
        (q,) = self.get("XX2020A02", "2022-06")
        self.assertEqual((q["cs0"], q["pred"], q["out"], q["seas"]), (1, 2, 2, 1))

    def test_blackout_and_post(self):
        (b,) = self.get("XX2020A01", "2024-10")
        self.assertEqual(b["period"], "blackout")
        self.assertEqual((b["cs0"], b["pred"], b["out"], b["lead"]), (2, 2, 3, 12))
        (p,) = self.get("XX2020A01", "2025-10")
        self.assertEqual((p["period"], p["cs0"], p["pred"], p["out"]), ("post", 3, 4, 4))

    def test_update_pairs(self):
        self.assertEqual(len(self.upd), 1)
        u = self.upd[0]
        self.assertEqual((fs.ym(u["origin"]), fs.ym(u["target"]), u["cs0"], u["pred"], u["out"]),
                         ("2022-04", "2022-06", 2, 2, 3))


class TestMetrics(unittest.TestCase):
    def test_sums_and_derive(self):
        cs, proj, _ = fs.parse_country(synthetic())
        pairs, _, _ = fs.build_pairs("XXX", cs, proj)
        d = fs.derive(fs.sums([p for p in pairs if p["period"] == "pre"]))
        self.assertEqual(d["n"], 3)
        self.assertEqual(d["acc"], 1.0)
        self.assertEqual(d["acc_persist"], 0.0)
        self.assertEqual(d["mae_persist"], 1.0)
        self.assertEqual(d["skill_vs_persist"], 1.0)
        self.assertEqual(d["skill_vs_seasonal"], 1.0)
        self.assertEqual((d["new_crisis_events"], d["pod"], d["pofd"], d["peirce"]),
                         (1, 1.0, 0.0, 1.0))
        self.assertIsNone(d["precision_4plus"])

    def test_bootstrap_deterministic(self):
        S = {"A": fs.sums([{"pred": 1, "out": 1, "cs0": 1}]),
             "B": fs.sums([{"pred": 2, "out": 1, "cs0": 1}])}
        f = lambda s: fs.country_mean(S, s, "acc")  # noqa: E731
        ci1 = fs.bootstrap(f, ["A", "B"], b=200)
        ci2 = fs.bootstrap(f, ["A", "B"], b=200)
        self.assertEqual(ci1, ci2)
        self.assertTrue(0.0 <= ci1[0] <= ci1[1] <= 1.0)

    def test_analyse_small_is_not_testable(self):
        cs, proj, _ = fs.parse_country(synthetic())
        pairs, upd, _ = fs.build_pairs("XXX", cs, proj)
        res = fs.analyse(pairs, upd)
        self.assertEqual(sorted(res["hypotheses"]), sorted("F%d" % i for i in range(1, 11)))
        for h in res["hypotheses"].values():
            self.assertEqual(h["verdict"], "not testable")
        self.assertEqual(res["blackout"]["unseen_new_crisis"], 1)
        self.assertEqual(res["countries"]["balanced"], ["XXX"])
        json.dumps(res)


class TestMainOffline(unittest.TestCase):
    def test_main_with_input_dir(self):
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in")
            os.makedirs(inp)
            with open(os.path.join(inp, "index.json"), "w") as f:
                json.dump({"generated_at": "2026-11-19T05:22:47+00:00",
                           "countries": [{"iso3": "XXX"}, {"iso3": "YYY"}]}, f)
            with open(os.path.join(inp, "XXX.json"), "w") as f:
                json.dump(synthetic(), f)
            out = os.path.join(d, "out")
            rc = fs.main(["--data-dir", os.path.join(d, "data"), "--out-dir", out,
                          "--input-dir", inp])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "results.json")) as f:
                res = json.load(f)
            self.assertIn("YYY", res["meta"]["errors"])
            self.assertEqual(res["meta"]["n_pairs"], 5)
            with gzip.open(os.path.join(out, "pairs.csv.gz"), "rt") as f:
                self.assertEqual(len(f.read().strip().splitlines()), 6)


if __name__ == "__main__":
    unittest.main()
