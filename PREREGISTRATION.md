# Pre-registration: famine-warning-skill, step 1

**Frozen 2026-11-19, before any accuracy, error or skill number was computed.**
By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in his name; no human
expert has reviewed this design yet. Code: `famine_skill.py` v0.1.0 (Apache-2.0).

## The question

FEWS NET, the U.S.-funded Famine Early Warning Systems Network, classifies food insecurity for
about 40 countries on the five-phase IPC scale (1 Minimal ... 5 Famine) and projects it 1 to 8
months ahead. Aid agencies, donors and anticipatory-action triggers rely on those projections.
In January 2025 a stop-work order took FEWS NET offline for the first time in its 40-year
history. It came back in stages from mid-2025, with full country reporting by October 2025.

We ask three questions:

1. **Skill beyond "nothing changes".** Before the blackout (2021-2024), did FEWS NET's projections
   beat two naive forecasts: persistence (the phase stays as it is now) and seasonal
   persistence (the phase is what it was in the same month a year earlier)? Did they detect
   **new crises** (areas going from Phase 1-2 into Phase 3+), which persistence by construction never
   does?
2. **After the restart.** Are the projections issued since the 2025 restart as skilful as
   before, in the same countries?
3. **The blind months.** How many of the areas in Phase 3+ when FEWS NET came back had been
   in Phase 1-2 before the blackout, and had also not been projected to reach Phase 3+?

## Prior work, and why this is new

- Backer and Billing (Global Food Security 29, 2021): FEWS NET projections in Africa
  2009-2020 were 84% accurate, less accurate at severe phases, with a lean toward
  over-projection.
- Bertetti, Capra, Calzadilla and Agnolucci (SSRN 5088067, 2025): 78% accuracy overall, with
  large differences across regions and periods.
- Seyffer et al. (AGILE GIScience Series 7:17, 2026): FEWS NET vs IPC in Somalia 2017-2025;
  projections matched later assessments 61.8% (FEWS NET) and 64.5% (IPC) of the time.
  The 2025 outage is the motivation, but projections issued after the restart are not
  evaluated.

As far as we could find (searches on 2026-11-19), no study scores projections issued after
the 2025 restart, measures what the blackout months missed, or reports FEWS NET's skill
against persistence and seasonal persistence on new crises across all its countries.
Accuracy alone can mislead: if most areas stay in the same phase, "nothing changes" is also
right most of the time.

## Data

- FEWS NET IPC-compatible area classifications (Source: FEWS NET, fews.net/data), read from
  OCHA-DAP's public daily mirror of the FEWS NET Data Warehouse:
  `https://ocha-dap.github.io/ds-fewsnet-mirror/data/index.json` and
  `.../classification/<ISO3>.json` (only rows FEWS NET marks Public). The job records the
  mirror's `generated_at` and the SHA-256 of every file.
- **What we looked at before freezing this:** the mirror's index (countries, round months,
  row counts; it shows no round from 2025-01 to 2025-07 in any country, and most countries
  resuming in 2025-10), the first 15 rows of Lesotho's file, and about 1,000 rows of Somalia's
  file from the 2026-07 to 2026-10 rounds. We used them only to learn the format: CS rows
  appear only in outlook rounds (e.g. Feb, Jun, Oct), and monthly update rounds carry ML1/ML2
  only. We computed no accuracy or skill number.

## Design (as coded in famine_skill.py)

- **Rows kept:** scale "IPC 3.0" or "IPC 3.1"; scenario CS, ML1 or ML2; integer phase 1-5;
  every unit except the admin0 row (and so no "IPC Highest Household" rows). Rows with the
  "!" assistance flag count at their phase. If the same area, scenario, round and window
  appear twice with different phases, the higher phase is used (conflicts are counted).
- **Pairs:** for each area (FNID), consecutive months with a CS classification, o then t.
  The outcome is CS at t. The FEWS NET forecast is the projection issued in round o whose
  window contains t. If two windows do, the one starting later wins, then ML2, then the higher
  phase. Areas are matched on the exact FNID only.
- **Baselines:** persistence = CS at o; seasonal persistence = CS at t minus 12 months (only
  where it exists).
- **Periods:** pre = o from 2021-01 and t by 2024-12; post = o from 2025-07; blackout = o by
  2024-12 and t from 2025-07. In pre and post, pairs more than 6 months apart are excluded as
  irregular. For blackout pairs the forecast is the last pre-blackout projection: from the
  latest round up to 2024-12 that has projections for the area, the window ending latest.
- **Balanced panel:** countries with at least one pre pair and one post pair. All before/after
  comparisons use it.
- **Metrics:** exact accuracy; mean absolute phase error (MAE); skill vs persistence =
  MAE(persistence) - MAE(FEWS NET), so positive means FEWS NET is better; the same against
  seasonal persistence on pairs where it exists; bias = mean(projected - observed). New-crisis
  detection is computed among pairs with CS at o of 2 or less: event = CS at t of 3 or more.
  POD is the share of events projected at 3+, POFD the share of non-events projected at 3+, and
  Peirce = POD - POFD. Precision at 4+ is the share of projections at 4+ that came true at 4+.
- **Weighting:** "country-mean" averages each country's metric with equal weight per country.
  "Pooled" sums over all pairs.
- **Uncertainty:** cluster bootstrap over countries, 2,000 resamples, seed 20261119,
  percentile 95% intervals. Differences use the same resample for both periods.
- **Minimum samples:** pre needs at least 500 pairs and 10 countries; comparisons need at
  least 500 post pairs and 10 balanced countries. Peirce tests need at least 20 events in each
  period used, F8 at least 20 projections at 4+, and F9 at least 50 blackout areas at 3+.
  Below these thresholds a prediction is graded "not testable".
- **Secondary (not graded):** projections from the monthly update rounds, with lead 1-3 months
  to the next CS, by period; confusion matrices; a per-country table; the list of unseen
  new crises by country.

## Predictions (with our probabilities that each comes out true)

| ID | Prediction | Rule | P |
|---|---|---|---|
| F1 | Pre-blackout projections were accurate at least 70% of the time | country-mean accuracy, pre, all countries, >= 0.70 | .75 |
| F2 | Pre-blackout, FEWS NET beat persistence | country-mean skill vs persistence > 0 and its 95% CI above 0 | .55 |
| F3 | Pre-blackout, FEWS NET beat seasonal persistence | country-mean skill vs seasonal persistence > 0 and CI above 0 | .60 |
| F4 | Pre-blackout, FEWS NET detected new crises better than chance | pooled Peirce > 0 and CI above 0 | .85 |
| F5 | After the restart, accuracy is within 5 points of before | balanced panel, abs(post - pre) country-mean accuracy <= 0.05 | .55 |
| F6 | After the restart, skill vs persistence fell | balanced panel, post - pre country-mean skill < 0 (point estimate; CI reported) | .50 |
| F7 | After the restart, new-crisis detection fell by at least 0.05 | balanced panel, pooled Peirce post - pre <= -0.05 | .40 |
| F8 | Projections of Emergency (4+) came true less than half the time, before and after | pooled precision at 4+ < 0.5 in both periods, balanced panel | .60 |
| F9 | The blind months hid many new crises | among blackout areas at 3+ when FEWS NET returned, share that were at 1-2 before and not projected at 3+: >= 0.10 | .35 |
| F10 | FEWS NET leans toward over-projection, before and after | balanced panel country-mean bias > 0 in both periods | .70 |

## What would be remarkable

If FEWS NET beats persistence on new crises before the blackout but not after, that is the
first evidence that the 2025 shutdown damaged the world's main famine early-warning system,
and it would show where. If skill held, that is also news: the restarted system can be trusted
as before, with numbers to show it. Either way, the blackout table lists the areas that went
into crisis while nobody was publishing.

## Limits we know now

- The CS classification at t is FEWS NET's own later judgement, not an independent
  measurement of hunger. Humanitarian aid that arrived because of a projection can make it
  look wrong, as Backer and Billing showed.
- The post-restart period is short: about three outlook cycles (Oct 2025 to Oct 2026).
- The mirror is a third-party copy of the FEWS NET Data Warehouse, and it keeps only Public
  rows.
- Areas whose FNID changed between rounds are dropped, not re-mapped.
