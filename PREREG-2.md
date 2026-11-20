# Pre-registration: famine-warning-skill, step 2 (prospective)

## Will FEWS NET's forecasts for the 2026-27 El Nino come true?

**Frozen 2026-11-20, before any of the outcome months existed.** The first outcome round
(February 2027) is about three months away; the last (February 2028) about fifteen.
By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name; no human
expert has reviewed this design yet. Code: `elnino.py` v0.2.0, which reuses the parsing,
pairing and metrics of `famine_skill.py` v0.1.0 (step 1). Apache-2.0.

## Why this test

A very strong El Nino (Nino-3.4 index of 2 C or more by September 2026) is under way, the
strongest since 2015/16 and compared by forecasters with 1997/98. On 6 October 2026 FEWS NET
published a global special report
([fews.net/global/special-report/october-2026](https://fews.net/global/special-report/october-2026)).
It says the worst hunger will come in the lean seasons of 2027, months after the rains fail, and that:

- Unimodal East Africa (Ethiopia, Sudan, South Sudan, Karamoja in Uganda) and Southern Africa are
  of highest concern, with drought the main driver of 2027 needs.
- In Southern Africa (Angola, Lesotho, Madagascar, Malawi, Mozambique, Zambia, Zimbabwe)
  "widespread Crisis (IPC Phase 3) outcomes are likely" in the November 2027-March 2028 lean season.
- Southern Somalia faces a risk of Famine (IPC Phase 5) from 1997/98-scale flooding, which is
  "not the most likely scenario"; needs peak October-December 2026.
- Kenya, Burkina Faso, Chad, Mali, Niger, Colombia, Guatemala, Haiti, Honduras and Pakistan are
  named with peak-need months in 2027.

Early warnings are usually judged after the fact, by people who already know what happened.
Here the forecasts, the scoring rules and our own expectations are fixed in public before the
outcomes exist, so hindsight cannot shape the result. The test also asks the question that
matters for anticipatory action: in a year with a strong, predictable climate signal, does the
early-warning system add more over "nothing changes" than it does in an ordinary year?

## Prior work

Step 1 of this repository (PREREGISTRATION.md, results pending) and the studies it cites
(Backer and Billing 2021; Bertetti et al. 2025; Seyffer et al. 2026) score FEWS NET after
the fact. Studies of El Nino and food security (e.g. the 2015/16 Southern Africa drought
literature) measure impacts, not the skill of the warnings. In searches on 2026-11-20 we found
no prospective, pre-registered scoring of a FEWS NET El Nino outlook, and no comparison of its
skill in an El Nino season with its skill in ordinary years.

## Data and the public record of the forecasts

- FEWS NET IPC-compatible area classifications (Source: FEWS NET, fews.net/data), from
  OCHA-DAP's public daily mirror of the FEWS NET Data Warehouse
  (`https://ocha-dap.github.io/ds-fewsnet-mirror/data/`), as in step 1.
- **Freeze.** `python elnino.py --freeze` saves every projection (ML1, ML2) and classification
  (CS) from round 2026-10 onward for all mirror countries to `frozen_2026-10.csv.gz`, with the
  SHA-256 of every mirror file (`freeze_meta.json`). It is run once now and committed here; the
  grading run checks that the projections it scores for round 2026-10 match the frozen copy
  and reports any that FEWS NET later changed.
- **What we looked at before freezing this:** FEWS NET's special report and its summary; the
  mirror's index (which countries exist and their latest round, 2026-10 for all 22 named
  countries). We looked at no 2026-10 projection or classification values.

## Design (as coded in elnino.py)

- **Pairs, forecasts, baseline, metrics:** exactly as in step 1 (`famine_skill.build_pairs`):
  consecutive CS classifications of the same area o -> t, at most 6 months apart; the FEWS NET
  forecast is the projection issued in round o whose window contains t; persistence = CS at o.
- **El Nino season:** pairs with origin from 2026-10 to 2027-10 and target by 2028-03.
- **Reference:** step 1's pre-blackout pairs (origin from 2021-01, target by 2024-12).
- **Named countries (22):** the countries above, grouped as in the report.
  **Control:** every other mirror country with season pairs.
- **Deterioration call:** projection above the current phase (pred > CS at o); it comes true if
  the outcome is also above the current phase.
- **Uncertainty:** cluster bootstrap over countries, 2,000 resamples, seed 20261119; for E6 the
  named and control countries are resampled separately.
- **Minimum samples** (else "not testable"): 300 season pairs in 10 named countries (E2, E3, E4,
  E8; E3 on countries with both season and reference pairs); 30 deterioration calls (E1); 20
  new-crisis events (E4); 50 Southern African areas with a CS in Nov 2027-Mar 2028 (E5); 10
  named and 5 control countries with both periods (E6); 30 matched areas (E9).

## Predictions (with our probabilities that each comes out true)

| ID | Prediction | Rule | P |
|---|---|---|---|
| E1 | FEWS NET's deterioration calls in the El Nino season come true at least half the time | pooled share, named countries, >= 0.50 | .45 |
| E2 | In the El Nino season FEWS NET beats persistence | country-mean MAE skill vs persistence > 0, 95% CI above 0 | .55 |
| E3 | Its skill over persistence is higher in the El Nino season than in 2021-2024, same countries | country-mean skill, season minus reference, > 0 | .60 |
| E4 | It detects new crises (Phase 1-2 to 3+) better than chance in the season | pooled Peirce > 0, CI above 0 | .75 |
| E5 | "Widespread Crisis" in Southern Africa comes true | share of the 7 countries' areas at Phase 3+ in their first CS of Nov 2027-Mar 2028 >= 0.30 | .45 |
| E6 | Named countries worsen more than the other FEWS NET countries, relative to 2021-2024 | difference-in-differences of mean phase change >= +0.10 | .50 |
| E7 | No Somali area is classified in Famine (Phase 5) in Jan-Jun 2027 | no CS = 5 for SOM in 2027-01..2027-06 | .85 |
| E8 | FEWS NET still over-projects in the El Nino season | country-mean bias (projected minus observed) > 0 | .60 |
| E9 | More of unimodal East Africa is in Crisis or worse in mid-2027 than in mid-2026 | same areas, share at 3+ in first CS of May-Aug 2027 minus May-Aug 2026, > 0 | .65 |

E5 also reports the same share after the 2023/24 El Nino (Nov 2023-Mar 2024) for context; it
is not graded.

## Schedule

- Interim grading after the June 2027 round is public (E7, E9, and E1-E4/E8 on the pairs then
  available, labelled interim).
- Final grading after the February 2028 round is public (all of E1-E9).
- If FEWS NET stops publishing, every affected prediction is graded "not testable" and that
  is reported.

## What would be remarkable

If FEWS NET's skill over "nothing changes" rises sharply in the El Nino year (E3) and its
Southern Africa call comes true (E5), that is direct, hindsight-free evidence that the world's
main famine early-warning system delivers most when a predictable climate shock arrives, the
case for funding it. If its deterioration calls mostly fail (E1 false) while it keeps
over-projecting (E8), that is equally important for the anticipatory-action triggers that use
these projections.

## Limits we know now

- Outcomes are FEWS NET's own later classifications, and humanitarian aid triggered by the
  warnings can make a correct warning look wrong.
- The named countries were chosen by FEWS NET for El Nino exposure, so E6 measures the
  El Nino year together with any other shocks those countries share.
- FEWS NET's continued funding is not certain; coverage may shrink.
- Areas whose FNID changes are dropped, as in step 1.
