# famine-warning-skill

Did the world's main famine early-warning system keep its skill after the 2025 blackout?

FEWS NET (the Famine Early Warning Systems Network) went offline in January 2025 for the first
time in 40 years and came back in stages through October 2025. This open, pre-registered study
scores every FEWS NET area-level projection that has an observed outcome. It runs from 2021 to
the latest round and compares the projections with two naive forecasts: "nothing changes"
(persistence) and "same as this season last year". It asks:

1. Before the blackout, did FEWS NET see **new** food crises coming (areas moving from IPC
   Phase 1-2 into Phase 3+), which "nothing changes" never does?
2. Are projections issued since the restart as skilful as before, in the same countries?
3. Which areas went into crisis during the blind months without having been projected to?

- Design and ten predictions, frozen before any number was computed:
  [PREREGISTRATION.md](PREREGISTRATION.md)
- Code: `famine_skill.py` (Python standard library only); offline tests in
  `test_famine_skill.py`
- Run: `python famine_skill.py --data-dir data --out-dir out` writes `out/results.json`
  (graded predictions, bootstrap intervals, per-country table, blackout table, confusion
  matrices) and `out/pairs.csv.gz` (every scored projection).

Status: design frozen 2026-11-19; first run queued. Results, including any predictions that
fail, will be published here as RESULTS.md.

## Data

FEWS NET IPC-compatible classifications. Source: FEWS NET (fews.net/data). They are read
from OCHA-DAP's public daily mirror of the FEWS NET Data Warehouse
(https://ocha-dap.github.io/ds-fewsnet-mirror/), which keeps only rows FEWS NET marks Public.
Each run records the mirror snapshot time and file hashes.

## Licence and credit

Code: Apache-2.0. Text: CC BY 4.0. By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI
agents working in his name; no human expert has reviewed it yet. Corrections are welcome as
issues.
