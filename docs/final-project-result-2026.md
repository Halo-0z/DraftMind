# DraftMind Final Project Result 2026

## A. Final Status

DraftMind is in its final pre-draft freeze state for the 2026 NBA Draft prediction build.

DraftMind 当前已经进入 2026 NBA Draft 真实选秀预测的 final pre-draft freeze 状态。当前最终预测入口是：

```text
/draft
```

Final frontend defaults:

- 两轮 60 picks
- Draft-Day Accuracy Mode 默认开启
- 预测信息辅助选人默认开启
- 手动锁定顺位默认关闭
- 球探适配诊断默认关闭
- 默认名单模式，分析模式可展开逐签解释

This project is not a classroom demo. It is a pre-draft prediction assistant focused on producing a realistic 2026 NBA Draft board while keeping model decisions explainable and auditable.

## B. What Drives The Simulation

Draft-Day Accuracy Mode is built on DraftMind's own simulation pipeline, with structured draft projection data used as the primary market-priority signal and DraftMind's scoring engine used as fallback/tie-break support. News/RAG signals are read-only explanation context and do not directly determine selected_player.

DraftMind 的真实选秀预测模式，是在 DraftMind 自身模拟系统上，引入结构化市场 projection 数据进行排序优先级调整；新闻和 RAG 只作为解释与证据上下文，不直接决定 selected_player。

Important boundaries:

- `ranking_engine` / `simulation_service` / `draft_day_accuracy` remain the decision path.
- LLM output explains results; it does not select players.
- News, RAG evidence, manual notes, and retrieval scores are read-only explanation context.
- The system does not hardcode the final board into production selection.

## C. Auto Simulation vs Draft-Day Accuracy Mode

| Mode | Purpose | Main signals | Selection behavior |
| ---- | ------- | ------------ | ------------------ |
| Auto Simulation | Internal DraftMind board | `ranking_engine`, talent, fit, pick value, risk | More like a pure model/scouting score board |
| Draft-Day Accuracy Mode | Final public prediction mode | Projection expected pick, projected range, confidence, team signal | Market-priority selection with DraftMind score as fallback/tie-break support |

Auto Simulation mainly follows DraftMind's internal scoring engine. It is useful for comparing the model's own talent / fit / pick-value / risk assessment against the market.

Draft-Day Accuracy Mode is opt-in at the API level, but the final frontend now opens with it enabled because it is the best current prediction view. It emphasizes structured projection data such as `expected_pick`, `draft_range_min/max`, and `confidence`, while still using DraftMind scores for support and tie-breaking.

Draft-Day Accuracy Mode is not news-driven auto-picking. It is not LLM-driven selection. It does not allow RAG or news summaries to directly choose `selected_player`.

## D. Final 60-Pick Board

Corrected final board after M4-CL / M4-CM availability refresh:

```text
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
#13 MIA Cameron Carr
#14 CHA Labaron Philon Jr.
#15 CHI Jayden Quaintance
#16 MEM Karim Lopez
#17 OKC Hannes Steinbach
#18 CHA Morez Johnson Jr.
#19 TOR Dailyn Swain
#20 SAS Christian Anderson
#21 DET Chris Cenac Jr.
#22 PHI Bennett Stirtz
#23 ATL Henri Veesaar
#24 NYK Isaiah Evans
#25 LAL Koa Peat
#26 DEN Ebuka Okorie
#27 BOS Allen Graves
#28 MIN Meleek Thomas
#29 CLE Joshua Jefferson
#30 DAL Alex Karaban
#31 NYK Tarris Reed Jr.
#32 MEM Sergio De Larrea
#33 BKN Ryan Conwell
#34 SAC Zuby Ejiofor
#35 SAS Richie Saunders
#36 LAC Ugonna Onyenso
#37 OKC Baba Miller
#38 CHI Trevon Brazile
#39 HOU Otega Oweh
#40 BOS Nick Martinelli
#41 MIA Jaden Bradley
#42 SAS Jack Kayil
#43 BKN Braden Smith
#44 SAS Emanuel Sharp
#45 SAC Ja'Kobi Gillespie
#46 ORL Milos Uzan
#47 PHX Bruce Thornton
#48 DAL Tyler Nickel
#49 DEN Felix Okpara
#50 TOR Izaiyah Nelson
#51 WAS Maliq Brown
#52 LAC Tamin Lipsey
#53 HOU Tobi Lawal
#54 GSW Mark Mitchell
#55 NYK Keyshawn Hall
#56 CHI Rafael Castro
#57 ATL Tyler Bilodeau
#58 NOP Kylan Boswell
#59 MIN Quadir Copeland
#60 WAS Vsevolod Ishchenko
```

## E. Availability Guards

The final simulation excludes official withdrawn / unavailable players and return-to-school / not-final-entrant players.

Official withdrawn / unavailable:

- Tounde Yessoufou
- Isiah Harwell
- Malachi Moreno
- Bassala Bagayoko
- Luigi Suigo
- Pavle Backo / Bačko
- Francesco Ferrari
- Marc-Owen Fodzo Dada

Return-to-school / not-final-entrant:

- Cayden Boozer
- Braylon Mullins
- Nikolas Khamenia
- Jasper Johnson
- Niko Bundalo

These guards are eligibility / availability guards only. They do not express draft stock, talent opinion, or team-fit opinion.

## F. Known Risk

The largest known final-board debate is:

```text
DAL #9 Aday Mara
```

Aday Mara is the biggest team-fit risk because Dallas has existing frontcourt depth and may more naturally prioritize shooting, guard creation, or wing help. The pick is still a market-priority outcome, not a hardcoded player/team override.

Counterfactual preflight showed that if Dallas skips Aday, the natural result becomes:

```text
#9 DAL Nate Ament
#10 MIL Aday Mara
```

That change only affects #9/#10. DraftMind intentionally does not apply a Dallas-specific hardcode and does not ship an unsafe generic team-fit penalty. The final choice preserves algorithmic consistency and market-priority behavior while documenting the team-fit risk.

## G. Final Validation Checklist

| Check | Result | Notes |
| ----- | ------ | ----- |
| Backend tests result | PASS | `D:\anaconda\python.exe -m pytest app/tests -q` -> 1534 passed, 560 warnings |
| Frontend build result | PASS | `npm run build` -> compiled successfully, 5 static pages generated |
| `/draft` page smoke result | PENDING_LOCAL_CONFIRMATION | Confirm final default view opens correctly |
| Default 60-pick Draft-Day Accuracy result | PENDING_LOCAL_CONFIRMATION | Confirm corrected 60-pick board above |
| Copy full board result | PENDING_LOCAL_CONFIRMATION | Confirm one-click copy includes 60 picks |
| Copy single-pick explanation result | PENDING_LOCAL_CONFIRMATION | Confirm Chinese explanation copy works |
| Git status clean | PENDING_LOCAL_CONFIRMATION | Will become clean after README/doc changes are reviewed and committed |
