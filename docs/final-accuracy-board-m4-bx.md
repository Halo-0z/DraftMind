# DraftMind M4-BX — Final Accuracy Board

## 1. Purpose

This document is DraftMind's final accuracy prediction board for the 2026 NBA Draft.

* **DraftMind Auto Simulation** is the system's automatic simulation baseline. It is produced by `ranking_engine` + `simulation_service` + `prediction_calibration` with prediction-assisted selection enabled, running 60 picks / two rounds.
* **Final Accuracy Board** is the final prediction output layer. It is not a re-run of the algorithm.
* The Final Accuracy Board is built by taking the Auto Simulation output as the starting point, then applying human corrections based on:
  * Public mock drafts and big boards (NBA.com, Tankathon, The Ringer, NBADraft.net, RookieScale, ESPN)
  * The official withdrawal / ineligible list
  * Team-specific intel (workouts, visits, reported interest)
* It is **not** the raw `ranking_engine` automatic output.
* It is the board that will be compared against the real NBA Draft results for accuracy evaluation.

## 2. Why not change the algorithm

The M4-BW market anchor preflight investigated whether a "market floor / consensus anchor" could be safely added to `prediction_calibration` to reduce the systematic slides of publicly-supported prospects (Kingston Flemings, Labaron Philon Jr., Christian Anderson, Dailyn Swain, Henri Veesaar, Tarris Reed Jr., etc.).

Preflight conclusion: `DO_NOT_IMPLEMENT`.

* The market anchor boost can pull Kingston / Labaron / Christian / Dailyn / Henri / Tarris back into the first round or into the 60-pick board in 60-pick simulations.
* However, every tested variant (S2-A, S2-B, S2-C, S3) broke the 30-pick safety gate (`risky_change = 0`). The boost strength required to rescue the sliding prospects also displaced safe in-range players (e.g. Niko Bundalo was pushed out of [24,34]).
* The failure pattern matched the previously-failed "soft projection guard" route (risky_change 4-7 vs required 0).
* Therefore the ranking / simulation / calibration code is left unchanged.

Instead of changing the algorithm, the Final Accuracy Board serves as the final prediction layer. The Auto Simulation remains the system's automatic baseline; the Final Accuracy Board applies the human judgment layer on top of it.

## 3. Removed unavailable players

The following players are confirmed withdrawn / ineligible / unavailable for the 2026 NBA Draft and are excluded from the Final Accuracy Board:

* Malachi Moreno
* Bassala Bagayoko
* Marc-Owen Fodzo Dada
* Pavle Backo
* Francesco Ferrari
* Luigi Suigo
* Isiah Harwell
* Tounde Yessoufou

These players were removed from the final board regardless of their DraftMind Auto Simulation position. None of them appear in the 1-60 table below.

## 4. Final Cleaned M4-BX Board

| Pick | Team | Player             | Source basis                                                                | Confidence | Difference from DraftMind                               |
| ---- | ---- | ------------------ | --------------------------------------------------------------------------- | ---------- | ------------------------------------------------------- |
| 1    | WAS  | AJ Dybantsa        | NBA.com consensus #1                                                        | High       | Same                                                    |
| 2    | UTA  | Darryn Peterson    | NBA.com consensus #2 / late #1 buzz                                         | High       | Same                                                    |
| 3    | MEM  | Cameron Boozer     | NBA.com consensus #3                                                        | High       | Same                                                    |
| 4    | CHI  | Caleb Wilson       | NBA.com consensus #4                                                        | High       | Same                                                    |
| 5    | LAC  | Keaton Wagler      | NBA.com consensus top-5                                                     | High       | Same                                                    |
| 6    | BKN  | Darius Acuff Jr.   | NBA.com consensus #6-7                                                      | High       | Same                                                    |
| 7    | SAC  | Kingston Flemings  | Strong top-10 support: Tankathon / The Ringer / recent scouting             | Medium     | Moved up from DraftMind #35                             |
| 8    | ATL  | Aday Mara          | NBA.com common #8 / first-round support                                     | Medium     | Moved up from DraftMind #25                             |
| 9    | DAL  | Mikel Brown Jr.    | Consensus lottery guard                                                     | Medium     | Slightly moved down from DraftMind #7                   |
| 10   | MIL  | Brayden Burries    | Stable top-10 / Warriors range support                                      | Medium     | Same                                                    |
| 11   | GSW  | Yaxel Lendeborg    | The Ringer / Tankathon first-round support                                  | Medium     | Same                                                    |
| 12   | OKC  | Cameron Carr       | Tankathon / RookieScale mid-first support                                   | Medium     | Slightly moved up from DraftMind #13                    |
| 13   | MIA  | Hannes Steinbach   | Warriors workout + mid-first board support                                  | Medium     | Moved up from DraftMind #34                             |
| 14   | CHA  | Morez Johnson Jr.  | NBA.com consensus lottery support; displaced Labaron from consensus lottery | Medium     | Moved up from DraftMind #22                             |
| 15   | CHI  | Nate Ament         | Consensus top-10/lottery-adjacent but volatile                              | Medium     | Moved down from DraftMind #8                            |
| 16   | MEM  | Labaron Philon Jr. | Tankathon / NBADraft.net mid-first; not stable consensus lottery            | Medium     | Moved up from DraftMind #40                             |
| 17   | OKC  | Jayden Quaintance  | First-round big profile / consensus support                                 | Medium     | Moved down from DraftMind #14                           |
| 18   | CHA  | Dailyn Swain       | Recent Sixers #22 mocks; firm first-round support                           | Medium     | Added from external consensus / unselected by DraftMind |
| 19   | TOR  | Christian Anderson | NBA.com profile / top-30 board support                                      | Medium     | Moved up from DraftMind #49                             |
| 20   | SAS  | Chris Cenac Jr.    | First-round upside big, but raw                                             | Medium     | Slightly moved down from DraftMind #19                  |
| 21   | DET  | Karim Lopez        | Remaining eligible international; first-round/early-second support          | Medium     | Moved down from DraftMind #17                           |
| 22   | PHI  | Henri Veesaar      | Tankathon/RookieScale late-first support                                    | Medium     | Added from external consensus / unselected by DraftMind |
| 23   | ATL  | Joshua Jefferson   | Late-first / early-second support; Sixers range discussion                  | Medium     | Moved up from DraftMind #41                             |
| 24   | NYK  | Bennett Stirtz     | Productive guard, late-first/early-second range                             | Medium     | Moved up from DraftMind #29                             |
| 25   | LAL  | Koa Peat           | First-round profile, but not locked                                         | Medium     | Moved down from DraftMind #21                           |
| 26   | DEN  | Tarris Reed Jr.    | Tankathon #31 / Knicks profile says strong value near #31                   | Medium     | Added from external consensus / unselected by DraftMind |
| 27   | BOS  | Alex Karaban       | The Ringer #30 area / Spurs workout                                         | Medium     | Added from external consensus / unselected by DraftMind |
| 28   | MIN  | Niko Bundalo       | Late-first variance / upside forward                                        | Low        | Same                                                    |
| 29   | CLE  | Nick Martinelli    | Scoring-forward board support                                               | Low        | Added from external consensus                           |
| 30   | DAL  | Mark Mitchell      | Physical forward, second-round but draftable                                | Low        | Moved up from DraftMind #43                             |
| 31   | NYK  | Sergio de Larrea   | NBA official remaining international                                        | Low        | Slightly moved down from DraftMind #30                  |
| 32   | MEM  | Meleek Thomas      | Late-first / early-second guard support                                     | Low        | Moved down from DraftMind #27                           |
| 33   | BKN  | Isaiah Evans       | Duke scoring wing / second-round support                                    | Low        | Moved down from DraftMind #24                           |
| 34   | SAC  | Braylon Mullins    | Shooter/guard, late-first to second support                                 | Low        | Moved down from DraftMind #12                           |
| 35   | SAS  | Allen Graves       | Big/forward prospect, second-round support                                  | Low        | Moved down from DraftMind #26                           |
| 36   | LAC  | Zuby Ejiofor       | Productive frontcourt second-round profile                                  | Low        | Low-confidence external consensus addition              |
| 37   | OKC  | Nikolas Khamenia   | DraftMind selected around #16; external range lower                         | Low        | Moved down from DraftMind #16                           |
| 38   | CHI  | Cayden Boozer      | Name/profile support, second-round range                                    | Low        | Low-confidence external consensus addition              |
| 39   | HOU  | Jaxon Kohler       | ESPN/RookieScale top-100 fringe                                             | Low        | Low-confidence external consensus addition              |
| 40   | BOS  | Ryan Conwell       | Shooting/scoring guard, second-round profile                                | Low        | Moved down from DraftMind #32                           |
| 41   | MIA  | Maliq Brown        | Duke role-player profile, second-round support                              | Low        | Low-confidence external consensus addition              |
| 42   | SAS  | Braden Smith       | Veteran guard production, second-round support                              | Low        | Low-confidence external consensus addition              |
| 43   | BKN  | Jack Kayil         | NBA official remaining international                                        | Low        | Low-confidence external consensus addition              |
| 44   | SAS  | Ugonna Onyenso     | Rim-protection profile                                                      | Low        | Low-confidence external consensus addition              |
| 45   | SAC  | Baba Miller        | Size/upside second-round profile                                            | Low        | Low-confidence external consensus addition              |
| 46   | ORL  | Otega Oweh         | Productive guard/wing, second-round profile                                 | Low        | Low-confidence external consensus addition              |
| 47   | PHX  | Trevon Brazile     | Athletic forward, second-round profile                                      | Low        | Low-confidence external consensus addition              |
| 48   | DAL  | Ja'Kobi Gillespie  | Guard depth, second-round profile                                           | Low        | Low-confidence external consensus addition              |
| 49   | DEN  | Melvin Council Jr. | ESPN/RookieScale top-100 fringe                                             | Low        | Moved up from DraftMind #59                             |
| 50   | TOR  | Jaden Bradley      | Guard depth, second-round profile                                           | Low        | Low-confidence external consensus addition              |
| 51   | WAS  | Mohammad Amini     | NBA official remaining international                                        | Low        | Low-confidence external consensus addition              |
| 52   | LAC  | Vsevolod Ishchenko | NBA official remaining international                                        | Low        | Low-confidence external consensus addition              |
| 53   | HOU  | Bruce Thornton     | Veteran guard, late-second support                                          | Low        | Low-confidence external consensus addition              |
| 54   | GSW  | Tamin Lipsey       | Defensive guard, late-second support                                        | Low        | Low-confidence external consensus addition              |
| 55   | NYK  | Kylan Boswell      | Guard depth, late-second support                                            | Low        | Low-confidence external consensus addition              |
| 56   | CHI  | Felix Okpara       | Rim-runner / defensive big profile                                          | Low        | Low-confidence external consensus addition              |
| 57   | ATL  | Keyshawn Hall      | Wing/forward depth profile                                                  | Low        | Low-confidence external consensus addition              |
| 58   | NO   | Rafael Castro      | Frontcourt depth profile                                                    | Low        | Low-confidence external consensus addition              |
| 59   | MIN  | Quadir Copeland    | Late-second / fringe wing                                                   | Low        | Low-confidence external consensus addition              |
| 60   | WAS  | Noam Yaacov        | International late-second flyer                                             | Low        | Low-confidence external consensus addition              |

## 5. Major corrections vs Auto Simulation

* **Removed unavailable players**: 8 withdrawn / ineligible prospects (listed in section 3) are excluded from the final board.
* **Moved up** (DraftMind auto simulation significantly undervalued):
  * Kingston Flemings (#35 → #7)
  * Aday Mara (#25 → #8)
  * Hannes Steinbach (#34 → #13)
  * Morez Johnson Jr. (#22 → #14)
  * Labaron Philon Jr. (#40 → #16)
  * Christian Anderson (#49 → #19)
  * Joshua Jefferson (#41 → #23)
  * Bennett Stirtz (#29 → #24)
  * Mark Mitchell (#43 → #30)
  * Melvin Council Jr. (#59 → #49)
* **Added from external consensus / unselected by DraftMind**:
  * Dailyn Swain
  * Henri Veesaar
  * Tarris Reed Jr.
  * Alex Karaban
* **Moved down** (DraftMind auto simulation overvalued):
  * Mikel Brown Jr. (#7 → #9, slight)
  * Nate Ament (#8 → #15)
  * Jayden Quaintance (#14 → #17)
  * Chris Cenac Jr. (#19 → #20, slight)
  * Karim Lopez (#17 → #21)
  * Koa Peat (#21 → #25)
  * Nikolas Khamenia (#16 → #37)
  * Sergio de Larrea (#30 → #31, slight)
  * Meleek Thomas (#27 → #32)
  * Isaiah Evans (#24 → #33)
  * Braylon Mullins (#12 → #34)
  * Allen Graves (#26 → #35)
  * Ryan Conwell (#32 → #40)
* **Low-confidence second round** (picks 31-60): mostly external consensus additions where DraftMind had no strong auto simulation signal; confidence is Low and these picks are expected to have higher variance against real draft results.

## 6. Final status

```text
READY_AS_FINAL_ACCURACY_BOARD
```
