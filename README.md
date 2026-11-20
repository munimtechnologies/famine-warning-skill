# famine-warning-skill

Did the world's main famine early-warning system keep its skill after the 2025 blackout, and
will its forecasts for the 2026-27 El Nino come true?

FEWS NET (the Famine Early Warning Systems Network) went offline in January 2025 for the first
time in 40 years and came back in stages through October 2025. This open, pre-registered study
scores FEWS NET's area-level projections against two naive forecasts: "nothing changes"
(persistence) and "same as this season last year".

**Step 1 (retrospective).** Scores every projection with an observed outcome, 2021 to the latest
round. It asks:

1. Before the blackout, did FEWS NET see **new** food crises coming (areas moving from IPC
   Phase 1-2 into Phase 3+), which "nothing changes" never does?
2. Are projections issued since the restart as skilful as before, in the same countries?
3. Which areas went into crisis during the blind months without having been projected to?

**Step 2 (prospective).** A very strong El Nino is under way, and FEWS NET's October 2026
special report warns of widespread Crisis in Southern Africa and peak needs across East and
West Africa, Central America and Pakistan in 2027. Step 2 fixes, before any outcome exists, how
those forecasts will be scored, and asks whether FEWS NET adds more over "nothing changes" in an
El Nino year than in ordinary years.

- Step 1 design and ten predictions: [PREREGISTRATION.md](PREREGISTRATION.md)
  (code `famine_skill.py`, tests `test_famine_skill.py`)
- Step 2 design and nine predictions: [PREREG-2.md](PREREG-2.md)
  (code `elnino.py`, tests `test_elnino.py`)
- Run step 1: `python famine_skill.py --data-dir data --out-dir out` writes `out/results.json`
  and `out/pairs.csv.gz`.
- Step 2: `python elnino.py --freeze --out-dir out` saves the current FEWS NET projections as a
  public record; `python elnino.py --out-dir out` grades E1-E9 once outcomes exist.

Status: step 1 frozen 2026-11-19, first run queued. Step 2 frozen 2026-11-20; interim grading
after the June 2027 round, final grading after the February 2028 round. All results, including
predictions that fail, will be published here.

## Data

FEWS NET IPC-compatible classifications. Source: FEWS NET (fews.net/data). They are read
from OCHA-DAP's public daily mirror of the FEWS NET Data Warehouse
(https://ocha-dap.github.io/ds-fewsnet-mirror/), which keeps only rows FEWS NET marks Public.
Each run records the mirror snapshot time and file hashes.

## Licence and credit

Code: Apache-2.0. Text: CC BY 4.0. By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI
agents working in his name; no human expert has reviewed it yet. Corrections are welcome as
issues.
