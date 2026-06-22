# M4-CE Draft-Day Accuracy Mode Preflight

## 1. Current Git Status

Preflight start:

```text
git status --short
<empty>

git log -1 --oneline
0327b4c Filter unavailable prospects from market warnings

git tag --points-at HEAD
market-warning-availability-filter-m4-cd
```

Scope: preflight / analysis only. No production code, DB, CSV, frontend, backend implementation, commit, push, or tag.

## 2. Baseline S0 Summary

S0 is current M4-CD default Auto Simulation:

* 30-pick and 60-pick
* prediction-assisted selection ON
* official availability guard ON
* no withdrawn / unavailable players selected
* default Auto Simulation unchanged

| Run | avg abs error vs M4-BX Final Board | Final Board coverage | Top-30 overlap | Full-60 overlap | withdrawn selected | market_top30_missing_warnings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| S0 30 | 5.2963 | 27 | 21 | 27 | 0 | 7 |
| S0 60 | 6.6122 | 49 | 21 | 49 | 0 | 4 |

S0 still under-selects major public-market names: Kingston Flemings, Hannes Steinbach, Christian Anderson, Dailyn Swain, Henri Veesaar, Alex Karaban, Tarris Reed Jr.; Aday Mara is selected but slides to #25.

## 3. Strategy Definitions

| Strategy | Definition | Notes |
| --- | --- | --- |
| S0 baseline | Existing M4-CD Auto Simulation with prediction-assisted selection ON | Production baseline only |
| S1 consensus-priority | For available candidates with ProspectDraftProjection, prioritize lower expected_pick; use range, confidence, team signal, model score as tie-breakers | Most market-board-like; no Final Board hardcoding |
| S2 bounded consensus override | At each pick, allow highest projected available candidate if projected_pick <= current_pick + window, range not severely conflicting, and model score floor passes | Tested +5, +8, +12; all produced same board |
| S3 hybrid final-prediction | Weighted blend of projected_pick priority, range hit, confidence, team projection signal, and model score floor | More conservative than S1/S2 in some slots, but misses several risk players |

All strategies use the M4-CC official availability guard. None hardcode the M4-BX Final Accuracy Board pick-by-pick.

## 4. S0/S1/S2/S3 Comparison Table

| Strategy | 60 avg abs error vs Final Board | Top-30 overlap | Full-60 overlap | withdrawn selected | safety anchors | market-risk improved |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| S0 baseline | 6.6122 | 21 | 49 | 0 | 4/4 | 1/8 |
| S1 consensus-priority | 4.6200 | 24 | 50 | 0 | 4/4 | 8/8 |
| S2 bounded +5 | 4.7200 | 24 | 50 | 0 | 4/4 | 8/8 |
| S2 bounded +8 | 4.7200 | 24 | 50 | 0 | 4/4 | 8/8 |
| S2 bounded +12 | 4.7200 | 24 | 50 | 0 | 4/4 | 8/8 |
| S3 hybrid | 4.9000 | 23 | 50 | 0 | 4/4 | 5/8 |

Best preflight result: S1 consensus-priority. It improves the benchmark error the most, clears withdrawn filtering, keeps all 60-pick safety anchors in range, and improves all 8 market-risk players.

## 5. 30-Pick Result Comparison

S2 +5/+8/+12 produced the same 30-pick board, shown as S2 bounded.

| Pick | Team | S0 | S1 | S2 bounded | S3 hybrid |
| ---: | --- | --- | --- | --- | --- |
| 1 | WAS | AJ Dybantsa | AJ Dybantsa | AJ Dybantsa | AJ Dybantsa |
| 2 | UTA | Darryn Peterson | Darryn Peterson | Darryn Peterson | Darryn Peterson |
| 3 | MEM | Cameron Boozer | Cameron Boozer | Cameron Boozer | Cameron Boozer |
| 4 | CHI | Caleb Wilson | Caleb Wilson | Caleb Wilson | Caleb Wilson |
| 5 | LAC | Keaton Wagler | Keaton Wagler | Keaton Wagler | Keaton Wagler |
| 6 | BKN | Darius Acuff Jr. | Darius Acuff Jr. | Darius Acuff Jr. | Darius Acuff Jr. |
| 7 | SAC | Mikel Brown Jr. | Kingston Flemings | Kingston Flemings | Kingston Flemings |
| 8 | ATL | Nate Ament | Aday Mara | Mikel Brown Jr. | Mikel Brown Jr. |
| 9 | DAL | Brayden Burries | Mikel Brown Jr. | Aday Mara | Aday Mara |
| 10 | MIL | Braylon Mullins | Brayden Burries | Nate Ament | Nate Ament |
| 11 | GSW | Yaxel Lendeborg | Nate Ament | Brayden Burries | Brayden Burries |
| 12 | OKC | Cameron Carr | Yaxel Lendeborg | Yaxel Lendeborg | Yaxel Lendeborg |
| 13 | MIA | Jayden Quaintance | Braylon Mullins | Braylon Mullins | Braylon Mullins |
| 14 | CHA | Morez Johnson Jr. | Labaron Philon Jr. | Cameron Carr | Cameron Carr |
| 15 | CHI | Labaron Philon Jr. | Cameron Carr | Labaron Philon Jr. | Labaron Philon Jr. |
| 16 | MEM | Nikolas Khamenia | Hannes Steinbach | Jayden Quaintance | Jayden Quaintance |
| 17 | OKC | Karim Lopez | Karim Lopez | Karim Lopez | Morez Johnson Jr. |
| 18 | CHA | Jasper Johnson | Jayden Quaintance | Hannes Steinbach | Dailyn Swain |
| 19 | TOR | Chris Cenac Jr. | Morez Johnson Jr. | Morez Johnson Jr. | Nikolas Khamenia |
| 20 | SAS | Cayden Boozer | Dailyn Swain | Dailyn Swain | Christian Anderson |
| 21 | DET | Koa Peat | Christian Anderson | Nikolas Khamenia | Bennett Stirtz |
| 22 | PHI | Ebuka Okorie | Nikolas Khamenia | Christian Anderson | Cayden Boozer |
| 23 | ATL | Isaiah Evans | Bennett Stirtz | Chris Cenac Jr. | Isaiah Evans |
| 24 | NYK | Niko Bundalo | Chris Cenac Jr. | Bennett Stirtz | Koa Peat |
| 25 | LAL | Aday Mara | Henri Veesaar | Cayden Boozer | Ebuka Okorie |
| 26 | DEN | Allen Graves | Cayden Boozer | Henri Veesaar | Allen Graves |
| 27 | BOS | Meleek Thomas | Isaiah Evans | Isaiah Evans | Meleek Thomas |
| 28 | MIN | Bennett Stirtz | Jasper Johnson | Koa Peat | Niko Bundalo |
| 29 | CLE | Sergio De Larrea | Koa Peat | Jasper Johnson | Joshua Jefferson |
| 30 | DAL | Joshua Jefferson | Ebuka Okorie | Ebuka Okorie | Tarris Reed Jr. |

30-pick note: S1/S2 do not select Niko Bundalo inside the first 30 in the 30-pick-only run, but in the required 60-pick final-mode run S1/S2 select Niko at #33, inside [24,34]. Since Draft-Day Accuracy Mode is intended for 60-pick final mode, the 60-pick safety table is the primary gate.

## 6. 60-Pick Result Comparison

| Pick | Team | S0 | S1 | S2 bounded | S3 hybrid |
| ---: | --- | --- | --- | --- | --- |
| 1 | WAS | AJ Dybantsa | AJ Dybantsa | AJ Dybantsa | AJ Dybantsa |
| 2 | UTA | Darryn Peterson | Darryn Peterson | Darryn Peterson | Darryn Peterson |
| 3 | MEM | Cameron Boozer | Cameron Boozer | Cameron Boozer | Cameron Boozer |
| 4 | CHI | Caleb Wilson | Caleb Wilson | Caleb Wilson | Caleb Wilson |
| 5 | LAC | Keaton Wagler | Keaton Wagler | Keaton Wagler | Keaton Wagler |
| 6 | BKN | Darius Acuff Jr. | Darius Acuff Jr. | Darius Acuff Jr. | Darius Acuff Jr. |
| 7 | SAC | Mikel Brown Jr. | Kingston Flemings | Kingston Flemings | Kingston Flemings |
| 8 | ATL | Nate Ament | Aday Mara | Mikel Brown Jr. | Mikel Brown Jr. |
| 9 | DAL | Brayden Burries | Mikel Brown Jr. | Aday Mara | Aday Mara |
| 10 | MIL | Braylon Mullins | Brayden Burries | Nate Ament | Nate Ament |
| 11 | GSW | Yaxel Lendeborg | Nate Ament | Brayden Burries | Brayden Burries |
| 12 | OKC | Cameron Carr | Yaxel Lendeborg | Yaxel Lendeborg | Yaxel Lendeborg |
| 13 | MIA | Jayden Quaintance | Braylon Mullins | Braylon Mullins | Braylon Mullins |
| 14 | CHA | Morez Johnson Jr. | Labaron Philon Jr. | Cameron Carr | Cameron Carr |
| 15 | CHI | Labaron Philon Jr. | Cameron Carr | Labaron Philon Jr. | Labaron Philon Jr. |
| 16 | MEM | Nikolas Khamenia | Hannes Steinbach | Jayden Quaintance | Jayden Quaintance |
| 17 | OKC | Karim Lopez | Karim Lopez | Karim Lopez | Morez Johnson Jr. |
| 18 | CHA | Jasper Johnson | Jayden Quaintance | Hannes Steinbach | Dailyn Swain |
| 19 | TOR | Chris Cenac Jr. | Morez Johnson Jr. | Morez Johnson Jr. | Nikolas Khamenia |
| 20 | SAS | Cayden Boozer | Dailyn Swain | Dailyn Swain | Christian Anderson |
| 21 | DET | Koa Peat | Christian Anderson | Nikolas Khamenia | Bennett Stirtz |
| 22 | PHI | Ebuka Okorie | Nikolas Khamenia | Christian Anderson | Cayden Boozer |
| 23 | ATL | Isaiah Evans | Bennett Stirtz | Chris Cenac Jr. | Isaiah Evans |
| 24 | NYK | Niko Bundalo | Chris Cenac Jr. | Bennett Stirtz | Koa Peat |
| 25 | LAL | Aday Mara | Henri Veesaar | Cayden Boozer | Ebuka Okorie |
| 26 | DEN | Allen Graves | Cayden Boozer | Henri Veesaar | Allen Graves |
| 27 | BOS | Meleek Thomas | Isaiah Evans | Isaiah Evans | Meleek Thomas |
| 28 | MIN | Bennett Stirtz | Jasper Johnson | Koa Peat | Niko Bundalo |
| 29 | CLE | Sergio De Larrea | Koa Peat | Jasper Johnson | Joshua Jefferson |
| 30 | DAL | Joshua Jefferson | Ebuka Okorie | Ebuka Okorie | Tarris Reed Jr. |
| 31 | NYK | Ryan Conwell | Allen Graves | Allen Graves | Sergio De Larrea |
| 32 | MEM | Kingston Flemings | Meleek Thomas | Meleek Thomas | Ryan Conwell |
| 33 | BKN | Ugonna Onyenso | Niko Bundalo | Niko Bundalo | Zuby Ejiofor |
| 34 | SAC | Hannes Steinbach | Alex Karaban | Joshua Jefferson | Richie Saunders |
| 35 | SAS | Christian Anderson | Joshua Jefferson | Alex Karaban | Ugonna Onyenso |
| 36 | LAC | Baba Miller | Tarris Reed Jr. | Tarris Reed Jr. | Baba Miller |
| 37 | OKC | Jaxon Kohler | Sergio De Larrea | Sergio De Larrea | Trevon Brazile |
| 38 | CHI | Otega Oweh | Ryan Conwell | Ryan Conwell | Otega Oweh |
| 39 | HOU | Jack Kayil | Zuby Ejiofor | Zuby Ejiofor | Nick Martinelli |
| 40 | BOS | Melvin Council Jr. | Richie Saunders | Richie Saunders | Jaden Bradley |
| 41 | MIA | Nick Martinelli | Ugonna Onyenso | Ugonna Onyenso | Jack Kayil |
| 42 | SAS | Chad Baker-Mazara | Baba Miller | Baba Miller | Braden Smith |
| 43 | BKN | Mark Mitchell | Trevon Brazile | Trevon Brazile | Emanuel Sharp |
| 44 | SAS | Milos Uzan | Otega Oweh | Otega Oweh | Ja'Kobi Gillespie |
| 45 | SAC | Bruce Thornton | Nick Martinelli | Nick Martinelli | Milos Uzan |
| 46 | ORL | Braden Smith | Jaden Bradley | Jaden Bradley | Bruce Thornton |
| 47 | PHX | Felix Okpara | Jack Kayil | Jack Kayil | Tyler Nickel |
| 48 | DAL | Ernest Udeh Jr. | Braden Smith | Braden Smith | Felix Okpara |
| 49 | DEN | Peter Suder | Emanuel Sharp | Emanuel Sharp | Izaiyah Nelson |
| 50 | TOR | Tamin Lipsey | Ja'Kobi Gillespie | Ja'Kobi Gillespie | Maliq Brown |
| 51 | WAS | Maliq Brown | Milos Uzan | Milos Uzan | Tamin Lipsey |
| 52 | LAC | Vsevolod Ishchenko | Bruce Thornton | Bruce Thornton | Tobi Lawal |
| 53 | HOU | Reynan dos Santos | Tyler Nickel | Tyler Nickel | Mark Mitchell |
| 54 | GSW | Josh Dix | Felix Okpara | Felix Okpara | Keyshawn Hall |
| 55 | NYK | Rafael Castro | Izaiyah Nelson | Izaiyah Nelson | Rafael Castro |
| 56 | CHI | Kylan Boswell | Maliq Brown | Maliq Brown | Tyler Bilodeau |
| 57 | ATL | Oscar Cluff | Tamin Lipsey | Tamin Lipsey | Kylan Boswell |
| 58 | NOP | Noam Yaacov | Tobi Lawal | Tobi Lawal | Quadir Copeland |
| 59 | MIN | Graham Ike | Keyshawn Hall | Mark Mitchell | Vsevolod Ishchenko |
| 60 | WAS | Quadir Copeland | Mark Mitchell | Keyshawn Hall | Noam Yaacov |

## 7. Market-Risk Player Movement Table

| Player | S0 60 | S1 60 | S2 60 | S3 60 | M4-BX Final Board | S1 assessment |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Kingston Flemings | 32 | 7 | 7 | 7 | 7 | fixed |
| Hannes Steinbach | 34 | 16 | 18 | not selected | 13 | materially improved |
| Christian Anderson | 35 | 21 | 22 | 20 | 19 | materially improved |
| Aday Mara | 25 | 8 | 9 | 9 | 8 | fixed |
| Dailyn Swain | not selected | 20 | 20 | 18 | 18 | materially improved |
| Henri Veesaar | not selected | 25 | 26 | not selected | 22 | materially improved |
| Alex Karaban | not selected | 34 | 35 | not selected | 27 | improved into 60 |
| Tarris Reed Jr. | not selected | 36 | 36 | 30 | 26 | improved into 60 |

S1 improves all 8 market-risk players versus S0. S3 only improves 5/8 because Hannes, Henri, and Alex remain unselected.

## 8. Safety Anchor Table

Primary gate uses the 60-pick final-mode run.

| Anchor | Required range | S0 | S1 | S2 | S3 | S1 pass |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Brayden Burries | [8,13] | 9 | 10 | 11 | 11 | yes |
| Yaxel Lendeborg | [11,14] | 11 | 12 | 12 | 12 | yes |
| Cameron Carr | [12,17] | 12 | 15 | 14 | 14 | yes |
| Niko Bundalo | [24,34] | 24 | 33 | 33 | 28 | yes |

S1 passes all 60-pick safety anchors. In 30-pick-only S1, Niko is not selected in the first 30, but he appears at #33 in the intended 60-pick Draft-Day Accuracy Mode.

## 9. Withdrawn / Unavailable Check

| Strategy | withdrawn selected count | Reintroduced Tounde/Isiah/Malachi/Bassala/Luigi/Pavle/Francesco/Marc-Owen |
| --- | ---: | --- |
| S0 | 0 | no |
| S1 | 0 | no |
| S2 +5/+8/+12 | 0 | no |
| S3 | 0 | no |

M4-CC availability guard remains active in every strategy.

## 10. Comparison To M4-BX Final Accuracy Board

M4-BX was used only as a benchmark, not as a hardcoded source of picks.

| Strategy | 60 avg abs error vs M4-BX | Better than S0 | Notes |
| --- | ---: | --- | --- |
| S0 | 6.6122 | baseline | Existing Auto Simulation |
| S1 | 4.6200 | yes | Best benchmark result |
| S2 +5/+8/+12 | 4.7200 | yes | Slightly worse than S1 |
| S3 | 4.9000 | yes | Safer-looking first round, but misses several risk names |

S1 is closest to the Final Accuracy Board while remaining algorithmic: it uses projection rank/range/confidence plus model score tie-breakers, not a pick-by-pick final board lookup.

## 11. Recommended Strategy

Recommendation: implement an optional `draft_day_accuracy_mode` based on S1 consensus-priority.

Final conclusion:

```text
RECOMMEND_IMPLEMENT_DRAFT_DAY_ACCURACY_MODE
```

Why S1:

1. Best 60-pick benchmark error against M4-BX Final Accuracy Board.
2. Improves all 8 specified market-risk players.
3. No withdrawn / unavailable players selected.
4. All 60-pick safety anchors remain in range.
5. Removes market_top30_missing_warnings in 60-pick run by selecting all projected top-30 available players.
6. Does not modify default Auto Simulation because it should be a new opt-in mode.

## 12. Minimal Production Implementation Plan If Recommended

Keep implementation small and isolated:

1. Add an optional request flag such as `draft_day_accuracy_mode: bool = False`.
2. Default stays `False`; current Auto Simulation remains unchanged.
3. When enabled, apply S1 selection policy only in the auto-pick branch after official availability filtering.
4. Candidate priority:
   * available and has ProspectDraftProjection first
   * lower `expected_pick` first
   * projected-range fit as tie-breaker
   * TeamPickProjection signal as tie-breaker
   * projection confidence and model final_score as final tie-breakers
5. Keep official withdrawal guard mandatory in this mode.
6. Do not change `ranking_engine`, talent_score, final_score, prediction_calibration formulas, DB, CSV, RAG, LLM, or frontend default behavior.
7. Add tests proving default mode output remains unchanged when the flag is omitted.

## 13. Why This Is Algorithmic And Not Hardcoded Final Board

S1 does not read `docs/final-accuracy-board-m4-bx.md` during selection. The preflight script only used M4-BX as a benchmark after producing strategy outputs.

The S1 selection policy is data-driven:

* It reads existing ProspectDraftProjection records.
* It filters official withdrawn players using M4-CC availability guard.
* It ranks available candidates by external expected_pick and projection range.
* It uses team projection, confidence, and model score as tie-breakers.
* It does not encode team/pick/player rows from M4-BX.

Main risk: because the strategy strongly follows the local projection board, stale or wrong projection data will directly affect output. This is acceptable only as an opt-in draft-day accuracy mode, not as a replacement for default Auto Simulation.

## 14. Final Git Status

Pending cleanup of temporary script / JSON. Expected final status after cleanup:

```text
?? m4-ce.md
```

