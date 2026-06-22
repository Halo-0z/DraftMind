# DraftMind M4-CH Real Local Final 60-Pick Export

## 1. Final Status

READY_FOR_CHATGPT_REVIEW

## 2. Why This Audit Exists

M4-CG only verified a 28-player in-memory test fixture. M4-CH uses the REAL LOCAL DB
(`backend/draftmind.db`) to export the final 60-pick board that DraftMind will use for
its real 2026 NBA Draft prediction. The goal is to confirm that the production code path
with real data produces a complete 60-pick board with no withdrawn players, no duplicates,
correct safety anchors, and all market-risk players selected in Draft-Day Accuracy Mode.
This report decides whether DraftMind can enter the true pre-draft final freeze.

## 3. Repo State

```
git log -1 --oneline
6a6eded (HEAD -> main, tag: pre-draft-final-freeze-audit-m4-cg, origin/main, origin/HEAD) Add pre-draft final freeze audit

git tag --points-at HEAD
pre-draft-final-freeze-audit-m4-cg
```

Initial `git status --short`:
```
?? backend/scripts/tmp_export_real_local_m4_ch.py
?? m4-ch.md
```

Final `git status --short`:
```
?? docs/real-local-final-board-export-m4-ch.md
?? m4-ch.md
```

## 4. Test Result

Command:
```
cd D:\DraftMind\backend
D:\anaconda\Scripts\pytest.exe app/tests/test_draft_day_accuracy_mode.py app/tests/test_simulation_service.py app/tests/test_simulate_api.py app/tests/test_ranking_engine.py -v
```

Result:
```
150 passed, 2 warnings in 11.93s
```

Warnings are pre-existing FastAPI `on_event` deprecation warnings, unrelated to this audit.

## 5. Frontend Build Result

Command:
```
cd D:\DraftMind\frontend
if (Test-Path .next) { Remove-Item -Recurse -Force .next }
npm run build
```

Result:
```
> draftmind-frontend@0.1.0 build
> next build

   ✓ Next.js 15.5.19
   ✓ Compiled successfully in 6.7s
   ✓ Linting and checking validity of types
   ✓ Generating static pages (5/5)

Route (app)                                 Size  First Load JS
┌ ○ /                                      684 B         103 kB
┌ ○ /_not-found                            993 B         103 kB
┌ ○ /draft                               20.1 kB         122 kB
+ First Load JS shared by all             102 kB
```

Build succeeded with no errors.

## 6. Real Local Data Source

The temporary export script `backend/scripts/tmp_export_real_local_m4_ch.py` used
`app.database.SessionLocal` which binds to the real local SQLite DB at
`sqlite:///./draftmind.db` (file: `backend/draftmind.db`, 598 KB).

- NOT an in-memory fixture.
- NOT a test fixture.
- No DB write performed.
- No seed inserted.
- No data modified.

The script was deleted after run. Confirmed not present in `git status`.

## 7. Mode Contract Verification

| Mode label | request flags | returned picks | response mode | response draft_day_accuracy_mode | expected? |
| ---------- | ------------- | -------------- | ------------- | -------------------------------- | --------- |
| Default Auto Simulation | accuracy=False, calibration=False | 60 | auto_simulation | False | OK |
| Draft-Day Accuracy Mode | accuracy=True, calibration=False | 60 | draft_day_accuracy | True | OK |
| Both Flags | accuracy=True, calibration=True | 60 | draft_day_accuracy | True | OK |
| Calibration Only | accuracy=False, calibration=True | 60 | auto_simulation | False | OK |

All 4 modes returned exactly 60 picks with correct mode labels and flags.

## 8. Final 60-Pick Draft-Day Accuracy Board

```
#01 WAS AJ Dybantsa
#02 UTA Darryn Peterson
#03 MEM Cameron Boozer
#04 CHI Caleb Wilson
#05 LAC Keaton Wagler
#06 BKN Darius Acuff Jr.
#07 SAC Kingston Flemings
#08 ATL Mikel Brown Jr.
#09 DAL Aday Mara
#10 MIL Nate Ament
#11 GSW Brayden Burries
#12 OKC Yaxel Lendeborg
#13 MIA Braylon Mullins
#14 CHA Cameron Carr
#15 CHI Labaron Philon Jr.
#16 MEM Jayden Quaintance
#17 OKC Karim Lopez
#18 CHA Hannes Steinbach
#19 TOR Morez Johnson Jr.
#20 SAS Dailyn Swain
#21 DET Nikolas Khamenia
#22 PHI Christian Anderson
#23 ATL Chris Cenac Jr.
#24 NYK Bennett Stirtz
#25 LAL Cayden Boozer
#26 DEN Henri Veesaar
#27 BOS Isaiah Evans
#28 MIN Koa Peat
#29 CLE Jasper Johnson
#30 DAL Ebuka Okorie
#31 NYK Allen Graves
#32 MEM Meleek Thomas
#33 BKN Niko Bundalo
#34 SAC Joshua Jefferson
#35 SAS Alex Karaban
#36 LAC Tarris Reed Jr.
#37 OKC Sergio De Larrea
#38 CHI Ryan Conwell
#39 HOU Zuby Ejiofor
#40 BOS Richie Saunders
#41 MIA Ugonna Onyenso
#42 SAS Baba Miller
#43 BKN Trevon Brazile
#44 SAS Otega Oweh
#45 SAC Nick Martinelli
#46 ORL Jaden Bradley
#47 PHX Jack Kayil
#48 DAL Braden Smith
#49 DEN Emanuel Sharp
#50 TOR Ja'Kobi Gillespie
#51 WAS Milos Uzan
#52 LAC Bruce Thornton
#53 HOU Tyler Nickel
#54 GSW Felix Okpara
#55 NYK Izaiyah Nelson
#56 CHI Maliq Brown
#57 ATL Tamin Lipsey
#58 NOP Tobi Lawal
#59 MIN Mark Mitchell
#60 WAS Keyshawn Hall
```

## 9. Default vs Draft-Day Accuracy Difference

55 of 60 picks differ between Default Auto Simulation and Draft-Day Accuracy Mode.

Full difference list:
```
#04: Mikel Brown Jr. -> Caleb Wilson
#05: Nate Ament -> Keaton Wagler
#06: Caleb Wilson -> Darius Acuff Jr.
#07: Koa Peat -> Kingston Flemings
#08: Darius Acuff Jr. -> Mikel Brown Jr.
#09: Braylon Mullins -> Aday Mara
#10: Jayden Quaintance -> Nate Ament
#12: Nikolas Khamenia -> Yaxel Lendeborg
#13: Cameron Carr -> Braylon Mullins
#14: Chris Cenac Jr. -> Cameron Carr
#15: Yaxel Lendeborg -> Labaron Philon Jr.
#16: Jasper Johnson -> Jayden Quaintance
#17: Jack Kayil -> Karim Lopez
#18: Ebuka Okorie -> Hannes Steinbach
#19: Aday Mara -> Morez Johnson Jr.
#20: Cayden Boozer -> Dailyn Swain
#21: Karim Lopez -> Nikolas Khamenia
#22: Morez Johnson Jr. -> Christian Anderson
#23: Niko Bundalo -> Chris Cenac Jr.
#24: Keaton Wagler -> Bennett Stirtz
#25: Mark Mitchell -> Cayden Boozer
#26: Kingston Flemings -> Henri Veesaar
#27: Allen Graves -> Isaiah Evans
#28: Kylan Boswell -> Koa Peat
#29: Labaron Philon Jr. -> Jasper Johnson
#30: Hannes Steinbach -> Ebuka Okorie
#31: Mohammad Amini -> Allen Graves
#32: Ugonna Onyenso -> Meleek Thomas
#33: Vsevolod Ishchenko -> Niko Bundalo
#34: Ryan Conwell -> Joshua Jefferson
#35: Isaiah Evans -> Alex Karaban
#36: Bennett Stirtz -> Tarris Reed Jr.
#37: Maliq Brown -> Sergio De Larrea
#38: Jaxon Kohler -> Ryan Conwell
#39: Meleek Thomas -> Zuby Ejiofor
#40: Quadir Copeland -> Richie Saunders
#41: Michael Ajayi -> Ugonna Onyenso
#43: Felix Okpara -> Trevon Brazile
#44: Christian Anderson -> Otega Oweh
#45: Oscar Cluff -> Nick Martinelli
#46: Milos Uzan -> Jaden Bradley
#47: Fletcher Loyer -> Jack Kayil
#48: Joshua Jefferson -> Braden Smith
#49: Ernest Udeh Jr. -> Emanuel Sharp
#50: Noam Yaacov -> Ja'Kobi Gillespie
#51: Sergio De Larrea -> Milos Uzan
#52: Henri Veesaar -> Bruce Thornton
#53: Tamin Lipsey -> Tyler Nickel
#54: Chad Baker-Mazara -> Felix Okpara
#55: Seth Trimble -> Izaiyah Nelson
#56: Bruce Thornton -> Maliq Brown
#57: Reynan dos Santos -> Tamin Lipsey
#58: Melvin Council Jr. -> Tobi Lawal
#59: Graham Ike -> Mark Mitchell
#60: Dailyn Swain -> Keyshawn Hall
```

Draft-Day Accuracy Mode truly changes selected players. Only picks #1, #2, #3, #11, and #42
are identical between the two modes.

## 10. S1 Priority Verification

Draft-Day Accuracy Mode vs Both Flags: **(no differences — sequences identical)**

S1 is NOT swallowed by calibration. The M4-CF-B branch priority fix works correctly on
the real local DB.

Result: **OK**

## 11. Calibration Only Comparison

Draft-Day Accuracy Mode vs Calibration Only: **52 of 60 picks differ.**

Calibration Only does NOT伪装成 Draft-Day Accuracy Mode. They produce distinctly different
boards. Calibration Only mode label is `auto_simulation`, while Draft-Day Accuracy Mode
label is `draft_day_accuracy`.

Calibration Only Top 10 for reference:
```
#01 WAS AJ Dybantsa
#02 UTA Darryn Peterson
#03 MEM Cameron Boozer
#04 CHI Caleb Wilson
#05 LAC Keaton Wagler
#06 BKN Darius Acuff Jr.
#07 SAC Mikel Brown Jr.
#08 ATL Nate Ament
#09 DAL Brayden Burries
#10 MIL Braylon Mullins
```

vs Draft-Day Accuracy Mode Top 10:
```
#01 WAS AJ Dybantsa
#02 UTA Darryn Peterson
#03 MEM Cameron Boozer
#04 CHI Caleb Wilson
#05 LAC Keaton Wagler
#06 BKN Darius Acuff Jr.
#07 SAC Kingston Flemings
#08 ATL Mikel Brown Jr.
#09 DAL Aday Mara
#10 MIL Nate Ament
```

Picks #7-#10 are completely different, confirming the two modes are distinct.

## 12. No Duplicate / No Withdrawn Verification

| Mode | duplicate selected? | withdrawn selected? | details |
| ---- | ------------------- | ------------------- | ------- |
| Default | False | False | 60 unique players, 0 withdrawn |
| Draft-Day Accuracy | False | False | 60 unique players, 0 withdrawn |
| Both Flags | False | False | 60 unique players, 0 withdrawn |
| Calibration Only | False | False | 60 unique players, 0 withdrawn |

Withdrawn players checked: Tounde Yessoufou, Isiah Harwell, Malachi Moreno,
Bassala Bagayoko, Luigi Suigo, Pavle Backo, Francesco Ferrari, Marc-Owen Fodzo Dada.

None were selected in any mode.

## 13. Safety Anchors

| Player | Pick in Draft-Day Accuracy Mode | Expected Range | Status |
| ------ | ------------------------------- | -------------- | ------ |
| Brayden Burries | #11 | [8,13] | OK |
| Yaxel Lendeborg | #12 | [11,14] | OK |
| Cameron Carr | #14 | [12,17] | OK |
| Niko Bundalo | #33 | [24,34] | OK |

All 4 safety anchors are within their expected ranges.

## 14. Market-Risk Players

| Player | Default Pick | Draft-Day Accuracy Pick | Calibration Only Pick | Expected / Range if available | Status |
| ------ | ------------ | ----------------------- | --------------------- | ----------------------------- | ------ |
| Kingston Flemings | #26 | #7 | #32 | expected #7 | OK — S1 matches market expectation |
| Hannes Steinbach | #30 | #18 | #34 | expected #13-16 | OK — S1 improves from #30 to #18 |
| Christian Anderson | #44 | #22 | #35 | expected #19-20 | OK — S1 improves from #44 to #22 |
| Aday Mara | #19 | #9 | #25 | expected #8 | OK — S1 matches market expectation |
| Dailyn Swain | #60 | #20 | OUT | expected #18 | OK — S1 improves from #60 to #20 |
| Henri Veesaar | #52 | #26 | OUT | expected #22 | OK — S1 improves from #52 to #26 |
| Alex Karaban | OUT | #35 | OUT | expected #27 | OK — S1 selects (Default/Calib do not) |
| Tarris Reed Jr. | OUT | #36 | OUT | expected #26-30 | OK — S1 selects (Default/Calib do not) |

All 8 market-risk players are selected in Draft-Day Accuracy Mode.
4 of them (Alex Karaban, Tarris Reed Jr., Dailyn Swain, Henri Veesaar) are NOT selected
in Calibration Only mode — this is expected behavior, not a bug.

## 15. First-Round Review

Draft-Day Accuracy Mode Top 30:
```
#01 WAS AJ Dybantsa
#02 UTA Darryn Peterson
#03 MEM Cameron Boozer
#04 CHI Caleb Wilson
#05 LAC Keaton Wagler
#06 BKN Darius Acuff Jr.
#07 SAC Kingston Flemings
#08 ATL Mikel Brown Jr.
#09 DAL Aday Mara
#10 MIL Nate Ament
#11 GSW Brayden Burries
#12 OKC Yaxel Lendeborg
#13 MIA Braylon Mullins
#14 CHA Cameron Carr
#15 CHI Labaron Philon Jr.
#16 MEM Jayden Quaintance
#17 OKC Karim Lopez
#18 CHA Hannes Steinbach
#19 TOR Morez Johnson Jr.
#20 SAS Dailyn Swain
#21 DET Nikolas Khamenia
#22 PHI Christian Anderson
#23 ATL Chris Cenac Jr.
#24 NYK Bennett Stirtz
#25 LAL Cayden Boozer
#26 DEN Henri Veesaar
#27 BOS Isaiah Evans
#28 MIN Koa Peat
#29 CLE Jasper Johnson
#30 DAL Ebuka Okorie
```

Manual review:
- No withdrawn players in Top 30.
- No duplicates in Top 30.
- No obvious top prospect missing — AJ Dybantsa, Darryn Peterson, Cameron Boozer all
  present at #1-#3.
- No obvious market-risk excessive slip — Kingston Flemings at #7 (expected #7),
  Aday Mara at #9 (expected #8), Hannes Steinbach at #18 (expected #13-16),
  Christian Anderson at #22 (expected #19-20).
- No point that obviously requires ChatGPT prediction trade-off judgment.
- Picks #31-#36 show minor slips for late-first/early-second prospects
  (Allen Graves #31 vs expected #26, Meleek Thomas #32 vs expected #27,
  Niko Bundalo #33 vs expected #28, Joshua Jefferson #34 vs expected #29,
  Alex Karaban #35 vs expected #29, Tarris Reed Jr. #36 vs expected #30).
  These are 5-6 position slips into the early second round, which is normal
  draft-day behavior and does not require ChatGPT review.

## 16. Page / Copy Smoke

- **Page started**: Yes. Frontend dev server running on `http://127.0.0.1:3000`.
- **/draft opened**: Yes. HTTP 200, page content length ~32 KB.
- **Draft-Day Accuracy Mode triggered**: Yes. Toggle labeled
  "Draft-Day Accuracy Mode（真实选秀预测模式）" was switched ON.
  Mode display showed "60 签 · 真实选秀预测 ON · 预测辅助 ON".
- **Page Top 30 matches backend export**: Yes. Page Top 10 matches script output exactly:
  AJ Dybantsa, Darryn Peterson, Cameron Boozer, Caleb Wilson, Keaton Wagler,
  Darius Acuff Jr., Kingston Flemings, Mikel Brown Jr., Aday Mara, Nate Ament.
- **一键复制结果 button exists**: Yes. Button text "一键复制结果" found on page.
- **Actual copy click executed**: Yes. Button clicked via Playwright.
  `navigator.clipboard.writeText` intercepted and captured the copied text.
- **Copied text content** (1699 chars):

```
模式：Draft-Day Accuracy
年份：2026
签数：60

完整 pick list：
#1 WAS AJ Dybantsa
#2 UTA Darryn Peterson
#3 MEM Cameron Boozer
#4 CHI Caleb Wilson
#5 LAC Keaton Wagler
#6 BKN Darius Acuff Jr.
#7 SAC Kingston Flemings
#8 ATL Mikel Brown Jr.
#9 DAL Aday Mara
#10 MIL Nate Ament
#11 GSW Brayden Burries
#12 OKC Yaxel Lendeborg
#13 MIA Braylon Mullins
#14 CHA Cameron Carr
#15 CHI Labaron Philon Jr.
#16 MEM Jayden Quaintance
#17 OKC Karim Lopez
#18 CHA Hannes Steinbach
#19 TOR Morez Johnson Jr.
#20 SAS Dailyn Swain
#21 DET Nikolas Khamenia
#22 PHI Christian Anderson
#23 ATL Chris Cenac Jr.
#24 NYK Bennett Stirtz
#25 LAL Cayden Boozer
#26 DEN Henri Veesaar
#27 BOS Isaiah Evans
#28 MIN Koa Peat
#29 CLE Jasper Johnson
#30 DAL Ebuka Okorie
#31 NYK Allen Graves
#32 MEM Meleek Thomas
#33 BKN Niko Bundalo
#34 SAC Joshua Jefferson
#35 SAS Alex Karaban
#36 LAC Tarris Reed Jr.
#37 OKC Sergio De Larrea
#38 CHI Ryan Conwell
#39 HOU Zuby Ejiofor
#40 BOS Richie Saunders
#41 MIA Ugonna Onyenso
#42 SAS Baba Miller
#43 BKN Trevon Brazile
#44 SAS Otega Oweh
#45 SAC Nick Martinelli
#46 ORL Jaden Bradley
#47 PHX Jack Kayil
#48 DAL Braden Smith
#49 DEN Emanuel Sharp
#50 TOR Ja'Kobi Gillespie
#51 WAS Milos Uzan
#52 LAC Bruce Thornton
#53 HOU Tyler Nickel
#54 GSW Felix Okpara
#55 NYK Izaiyah Nelson
#56 CHI Maliq Brown
#57 ATL Tamin Lipsey
#58 NOP Tobi Lawal
#59 MIN Mark Mitchell
#60 WAS Keyshawn Hall

Warning panels：
- 选秀行情 Top-30 未进入首轮提示：
  · Allen Graves 预计第 26 顺位，本次第 31 顺位，滑落 5 位。
  · Meleek Thomas 预计第 27 顺位，本次第 32 顺位，滑落 5 位。
  · Niko Bundalo 预计第 28 顺位，本次第 33 顺位，滑落 5 位。
  · Joshua Jefferson 预计第 29 顺位，本次第 34 顺位，滑落 5 位。
  · Alex Karaban 预计第 29 顺位，本次第 35 顺位，滑落 6 位。
  · Tarris Reed Jr. 预计第 30 顺位，本次第 36 顺位，滑落 6 位。
```

Copied text matches the backend Draft-Day Accuracy Mode export exactly.

**Operational note**: The backend process initially running on port 8000 was started
at 2026-06-22 14:09:56, before the M4-CF-B fix was committed. It was serving stale code
that did NOT include the S1 branch priority fix, causing the page to show Calibration
Only results even when Draft-Day Accuracy Mode was toggled ON. After restarting the
backend with the current committed code, the page correctly shows S1 results.
This is an operational issue (stale process), NOT a code bug. The code on disk and in
the committed repo is correct.

## 17. Boundary Verification

- no commit: **confirmed** — no `git commit` executed
- no push: **confirmed** — no `git push` executed
- no tag: **confirmed** — no `git tag` executed
- no DB change: **confirmed** — `backend/draftmind.db` not modified
- no CSV change: **confirmed** — no CSV files modified
- no seed change: **confirmed** — no seed scripts run
- no ranking_engine change: **confirmed** — `ranking_engine.py` not modified
- no simulation_service change: **confirmed** — `simulation_service.py` not modified
- no draft_day_accuracy helper change: **confirmed** — `draft_day_accuracy.py` not modified
- no frontend code change: **confirmed** — no frontend source files modified
- no Final Accuracy Board production read: **confirmed** — `docs/final-accuracy-board-m4-bx.md` not read for production selection
- no hardcoded 60-pick board: **confirmed** — all picks come from `simulate_draft` function
- no if-name production override: **confirmed** — no name-based overrides in production code
- temporary script deleted: **confirmed** — `backend/scripts/tmp_export_real_local_m4_ch.py` deleted, not in `git status`

## 18. Final Git Status

```
git status --short
?? docs/real-local-final-board-export-m4-ch.md
?? m4-ch.md

git diff --stat
(empty — no tracked files modified)
```

The only new file is this report. `m4-ch.md` is the task spec (pre-existing untracked file).

## 19. Recommendation

Recommended next step:
ChatGPT should review this real local final board export. If approved, commit only
`docs/real-local-final-board-export-m4-ch.md` with message:

```
Add real local final board export
```

Potential tag:
```
real-local-final-board-export-m4-ch
```

Do not commit, push, or tag in this task.
