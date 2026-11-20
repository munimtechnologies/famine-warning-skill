# Offline tests for elnino.py (Apache-2.0). Made with AI agents working in MV2's name.
import elnino as en  # noqa: I001 - import the module under test first

import gzip
import json
import os
import tempfile
import unittest

import famine_skill as fs

COLS = ["u", "scale", "scenario", "assistance", "reporting_date", "projection_start",
        "projection_end", "doc", "st", "phase"]
M = fs.month_index


def R(u, scen, rep, s, e, ph):
    return [u, "IPC 3.1", scen, 0, rep, s, e, 0, 0, ph]


def synthetic():
    units = [["XX", "Xland", "admin0"], ["Z1", "Zone 1", "fsc_admin_lhz"],
             ["Z2", "Zone 2", "fsc_admin_lhz"]]
    rows = [
        # Z1: one pre-blackout pair (2 -> projected 3 -> 3)
        R(1, "CS", "2023-02", "2023-02-01", "2023-02-28", 2),
        R(1, "ML2", "2023-02", "2023-06-01", "2023-09-30", 3),
        R(1, "CS", "2023-06", "2023-06-01", "2023-06-30", 3),
        # Z1: El Nino season pairs (2 -> 3 -> 3) and (3 -> 3 -> 2)
        R(1, "CS", "2026-10", "2026-10-01", "2026-10-31", 2),
        R(1, "ML1", "2026-10", "2026-10-01", "2027-01-31", 2),
        R(1, "ML2", "2026-10", "2027-02-01", "2027-05-31", 3),
        R(1, "CS", "2027-02", "2027-02-01", "2027-02-28", 3),
        R(1, "ML2", "2027-02", "2027-06-01", "2027-09-30", 3),
        R(1, "CS", "2027-06", "2027-06-01", "2027-06-30", 2),
        # Z2: season pair (1 -> 1 -> 1), then an irregular 12-month gap to 2028-02
        R(2, "CS", "2026-10", "2026-10-01", "2026-10-31", 1),
        R(2, "ML2", "2026-10", "2027-02-01", "2027-05-31", 1),
        R(2, "CS", "2027-02", "2027-02-01", "2027-02-28", 1),
        R(2, "CS", "2028-02", "2028-02-01", "2028-02-29", 3),
    ]
    return {"generated_at": "2026-11-20T05:00:00+00:00", "units": units, "docs": ["d"],
            "statuses": ["Collected"], "columns": COLS, "rows": rows}


def parsed(iso):
    cs, proj, _ = fs.parse_country(synthetic())
    pairs, _, _ = fs.build_pairs(iso, cs, proj)
    return {k: dict(v) for k, v in cs.items()}, proj, pairs


class TestHelpers(unittest.TestCase):
    def setUp(self):
        self.cs, self.proj, self.pairs = parsed("ZMB")
        self.season = [p for p in self.pairs if en.in_season(p)]

    def test_groups(self):
        self.assertEqual(len(en.NAMED), 22)
        self.assertIn("SOM", en.NAMED)
        self.assertNotIn("AFG", en.NAMED)

    def test_season_pairs(self):
        got = sorted((p["cs0"], p["pred"], p["out"]) for p in self.season)
        self.assertEqual(got, [(1, 1, 1), (2, 3, 3), (3, 3, 2)])
        pre = [p for p in self.pairs if p["period"] == "pre"]
        self.assertEqual([(p["cs0"], p["pred"], p["out"]) for p in pre], [(2, 3, 3)])

    def test_det_and_change(self):
        self.assertEqual(en.det_counts(self.season), (1, 1))
        self.assertEqual(en.mean_change(self.season), 0.0)
        self.assertIsNone(en.mean_change([]))

    def test_shares(self):
        cbc = {"ZMB": self.cs}
        self.assertEqual(en.share3(cbc, ["ZMB"], M("2027-11"), M("2028-03")), (1, 1.0))
        self.assertEqual(en.share3(cbc, ["ZMB"], M("2030-01"), M("2030-02")), (0, None))
        self.assertEqual(en.matched_change3(cbc, ["ZMB"], M("2026-09"), M("2026-11"),
                                            M("2027-01"), M("2027-03")), (2, 0.5))
        self.assertEqual(en.any_phase(cbc, "ZMB", M("2027-01"), M("2027-06"), 3), (3, True))
        self.assertEqual(en.any_phase(cbc, "ZMB", M("2027-01"), M("2027-06"), 5), (3, False))
        self.assertEqual(en.any_phase(cbc, "SOM", M("2027-01"), M("2027-06"), 5), (0, False))

    def test_did_and_boot(self):
        self.assertEqual(en.did({"A": 1.0, "B": 0.0}, {"A": 0.0, "B": 0.0}, ["A"], ["B"]), 1.0)
        self.assertIsNone(en.did({"A": 1.0}, {"A": 0.0}, ["A"], ["B"]))
        f = lambda a, b: en.did({"A": 1.0, "B": 0.0}, {"A": 0.0, "B": 0.0}, a, b)  # noqa: E731
        c1 = en.strat_boot(f, ["A", "B"], ["A", "B"], reps=200)
        c2 = en.strat_boot(f, ["A", "B"], ["A", "B"], reps=200)
        self.assertEqual(c1, c2)
        self.assertTrue(-1.0 <= c1[0] <= c1[1] <= 1.0)

    def test_frozen_check_detects_change(self):
        cs, proj, _ = fs.parse_country(synthetic())
        rows = en.freeze_rows("ZMB", cs, proj)
        d = tempfile.mkdtemp()
        path = os.path.join(d, "f.csv.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write("iso3,fnid,round,scenario,start,end,phase\n")
            for r in rows:
                ph = 4 if (r[1], r[3]) == ("Z1", "ML2") and r[2] == "2026-10" else r[6]
                f.write(",".join(str(x) for x in r[:6]) + ",%d\n" % ph)
        fc = en.frozen_check(rows, path)
        self.assertEqual((fc["frozen"], fc["current"], fc["changed_phase"]), (3, 3, 1))
        self.assertEqual(fc["changed_examples"], ["ZMB|Z1|2026-10|ML2|2027-02|2027-05"])

    def test_freeze_rows(self):
        cs, proj, _ = fs.parse_country(synthetic())
        rows = en.freeze_rows("ZMB", cs, proj)
        self.assertEqual(len(rows), 10)
        self.assertNotIn("2023-02", {r[2] for r in rows})
        self.assertIn(("ZMB", "Z1", "2026-10", "ML2", "2027-02", "2027-05", 3), rows)
        self.assertIn(("ZMB", "Z2", "2028-02", "CS", "2028-02", "2028-02", 3), rows)


class TestAnalyse(unittest.TestCase):
    def test_small_sample(self):
        cs, _, pz = parsed("ZMB")
        _, _, ps = parsed("SOM")
        res = en.analyse(pz + ps, {"ZMB": cs, "SOM": cs})
        H = res["hypotheses"]
        self.assertEqual(sorted(H), sorted("E%d" % i for i in range(1, 10)))
        for k in ("E1", "E2", "E3", "E4", "E5", "E6", "E8", "E9"):
            self.assertEqual(H[k]["verdict"], "not testable", k)
        self.assertEqual(H["E7"]["verdict"], "true")
        self.assertEqual(H["E7"]["observations"], 3)
        self.assertEqual(res["countries"]["named_season"], ["SOM", "ZMB"])
        self.assertEqual(res["regions"]["southern_africa"]["season"]["n"], 3)
        self.assertEqual(res["regions"]["southern_africa"]["season"]["det_hits"], 1)
        self.assertEqual(res["regions"]["bimodal_east_africa"]["reference"]["n"], 1)
        self.assertEqual(res["regions"]["control"]["season"]["n"], 0)
        json.dumps(res)


class TestMainOffline(unittest.TestCase):
    def run_main(self, extra):
        d = tempfile.mkdtemp()
        inp = os.path.join(d, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "index.json"), "w") as f:
            json.dump({"generated_at": "2026-11-20T05:00:00+00:00",
                       "countries": [{"iso3": "ZMB"}, {"iso3": "QQQ"}]}, f)
        with open(os.path.join(inp, "ZMB.json"), "w") as f:
            json.dump(synthetic(), f)
        out = os.path.join(d, "out")
        rc = en.main(["--data-dir", os.path.join(d, "data"), "--out-dir", out,
                      "--input-dir", inp] + extra)
        self.assertEqual(rc, 0)
        return out

    def test_freeze(self):
        out = self.run_main(["--freeze"])
        with gzip.open(os.path.join(out, "frozen_2026-10.csv.gz"), "rt") as f:
            lines = f.read().strip().splitlines()
        self.assertEqual(len(lines), 11)
        self.assertEqual(lines[0], "iso3,fnid,round,scenario,start,end,phase")
        with open(os.path.join(out, "freeze_meta.json")) as f:
            meta = json.load(f)
        self.assertEqual(meta["frozen_rows"], 10)
        self.assertIn("QQQ", meta["errors"])
        self.assertEqual(meta["frozen_rounds"], ["2026-10", "2027-02", "2027-06", "2028-02"])

    def test_grade(self):
        fz = os.path.join(self.run_main(["--freeze"]), "frozen_2026-10.csv.gz")
        out = self.run_main(["--frozen", fz])
        with open(os.path.join(out, "elnino_results.json")) as f:
            res = json.load(f)
        self.assertEqual(res["meta"]["mode"], "grade")
        fc = res["meta"]["frozen_check"]
        self.assertEqual((fc["frozen"], fc["current"], fc["missing_now"], fc["new_now"],
                          fc["changed_phase"]), (3, 3, 0, 0, 0))
        self.assertEqual(res["hypotheses"]["E7"]["verdict"], "not testable")
        self.assertEqual(res["regions"]["southern_africa"]["season"]["n"], 3)


if __name__ == "__main__":
    unittest.main()
