# DraftMind M4-CL Return-To-School Availability Guard Patch

## 1. Final Status

READY_FOR_CHATGPT_REVIEW

## 2. Why This Patch Exists

pre-draft-final-freeze-2026 之后发现 final board 里有已返校 / 不在 official final early-entry pool 的球员。本 patch 只修 draftability / availability hard error，不修 team-fit，不改预测算法。

具体问题：M4-CJ 原本发现 Lakers #25 Cayden Boozer 看起来 team-fit 可疑。M4-CK 进一步确认：问题更严重，Cayden Boozer 可能根本不该进入 2026 NBA Draft 可选池。最终 60 picks 里还出现了 Braylon Mullins、Nikolas Khamenia、Jasper Johnson、Niko Bundalo 这类不在 NBA 6/15 final remaining early-entry list 中的 underclass / return-to-school / transfer 类型球员。

本 patch 在 `prospect_availability.py` 中新增一组 return-to-school / not-final-entrant unavailable names，让 availability guard 在 `/api/simulate` 选人前过滤掉这些球员。替代人选由现有 ranking_engine + simulation_service 自然产生，没有 hardcode 任何 replacement pick。

## 3. Repo State

```
git log -1 --oneline
c01db30 (HEAD -> main, tag: real-local-final-board-export-m4-ch, tag: pre-draft-final-freeze-2026, origin/main, origin/HEAD) Add real local final board export

git tag --points-at HEAD
pre-draft-final-freeze-2026
real-local-final-board-export-m4-ch
```

初始 `git status --short`（patch 开始前）：

```
?? m4-cl.md
```

工作区在 patch 开始前是干净的（m4-cl.md 是任务 spec，untracked，不算工作区污染）。

最终 `git status --short`（patch 完成后）：

```
 M backend/app/services/prospect_availability.py
 M backend/app/tests/test_draft_day_accuracy_mode.py
 M backend/app/tests/test_prospect_availability.py
 M backend/app/tests/test_recommend_api.py
 M backend/app/tests/test_simulation_service.py
?? m4-cl.md
?? docs/return-to-school-availability-guard-m4-cl.md
```

## 4. Files Changed

实际修改文件：

| 文件 | 是否在 spec 允许列表 | 说明 |
|------|---------------------|------|
| `backend/app/services/prospect_availability.py` | 是 | 新增 return-to-school unavailable names + 合并 frozenset |
| `backend/app/tests/test_prospect_availability.py` | 是 | 新增 return-to-school / market-risk / filter 测试 |
| `backend/app/tests/test_draft_day_accuracy_mode.py` | 是 | 取消 Niko Bundalo safety anchor，新增 return-to-school 排除测试 |
| `backend/app/tests/test_simulation_service.py` | 否（相关测试） | 18 个测试因 Braylon Mullins / Niko Bundalo 变 unavailable 而失败，需更新 fixture 引用 |
| `backend/app/tests/test_recommend_api.py` | 否（相关测试） | 1 个 smoke 测试因 conftest 只剩 1 个 available prospect 而失败，需调整断言 |
| `docs/return-to-school-availability-guard-m4-cl.md` | 是（可选新增） | 本报告 |

### 为什么改了 test_simulation_service.py 和 test_recommend_api.py

spec 的 "允许改动文件" 列表只列了 `prospect_availability.py`、`test_prospect_availability.py`、`test_draft_day_accuracy_mode.py`。但 spec 第 15 条也说 "只允许改 availability guard 和相关测试"。

availability guard 改了之后，`test_simulation_service.py` 有 18 个测试失败（它们直接引用 Braylon Mullins / Niko Bundalo 作为可选球员），`test_recommend_api.py` 有 1 个 smoke 测试失败（conftest 只剩 1 个 available prospect，`/api/simulate` 只能返回 1 个 pick 而不是 2 个）。

这些是 "相关测试" —— 它们不是测试 availability guard 本身，但它们因为 availability guard 的改变而失败。如果不修它们，spec 第 5 步 "如果任何测试失败，停止并输出 NEEDS_TARGETED_FIX" 会触发，整个 patch 无法 READY。

修改原则：
- `test_simulation_service.py`：把直接引用 Braylon Mullins 的测试改成引用一个 available replacement prospect（"Darryn Peterson"，用 helper 在测试内创建，不改 conftest）；把 Niko Bundalo safety anchor 测试改成 "Niko Bundalo not selected" 测试。
- `test_recommend_api.py`：`test_recommend_does_not_change_simulate` 原本断言 2 picks，现在 conftest 只剩 1 个 available prospect，所以改成断言 1 pick。smoke 意图（recommend path 不破坏 simulate）保留。

没有改 `conftest.py`、`ranking_engine.py`、`simulation_service.py`、`draft_day_accuracy.py`、`seed_db.py`、DB、CSV、frontend。

## 5. Availability Guard Update

### 新增 unavailable names（return-to-school / not-final-entrant）

在 `backend/app/services/prospect_availability.py` 中新增：

```python
_RETURN_TO_SCHOOL_OR_NOT_FINAL_EARLY_ENTRY_2026_RAW: tuple[str, ...] = (
    "Cayden Boozer",
    "Braylon Mullins",
    "Nikolas Khamenia",
    "Jasper Johnson",
    "Niko Bundalo",
)
```

这些球员来源类型：
- return to school
- not in NBA 6/15 final remaining early-entry list
- not draftable for 2026 final board

### 已有 withdrawn names 仍保留

```python
_OFFICIAL_WITHDRAWN_2026_RAW: tuple[str, ...] = (
    "Tounde Yessoufou",
    "Isiah Harwell",
    "Malachi Moreno",
    "Bassala Bagayoko",
    "Marc-Owen Fodzo Dada",
    "Pavle Backo",  # Pavle Bačko
    "Francesco Ferrari",
    "Luigi Suigo",
)
```

### 合并 frozenset

```python
_UNAVAILABLE_2026: frozenset[str] = (
    _OFFICIAL_WITHDRAWN_2026
    | _RETURN_TO_SCHOOL_OR_NOT_FINAL_EARLY_ENTRY_2026
)
```

`is_officially_unavailable_for_draft` 现在检查 `_UNAVAILABLE_2026`（合并集），而不是只检查 `_OFFICIAL_WITHDRAWN_2026`。Guard 仍然 scoped to `draft_year == 2026`。

### Niko Bundalo safety anchor 已取消

Niko Bundalo 现在被视为 not draftable / unavailable，所以他在 `test_draft_day_accuracy_mode.py` 里的 safety anchor `[24, 34]` 已取消。`_SAFETY_ANCHOR_SPECS` 从 4 条减为 3 条：

- Brayden Burries [8, 13]
- Yaxel Lendeborg [11, 14]
- Cameron Carr [12, 17]

原 `test_niko_bundalo_range_24_34` 被替换为 `test_niko_bundalo_not_selected`（断言 `pick is None`）。

## 6. Test Results

### 1. availability + draft_day_accuracy tests

```
cd D:\DraftMind\backend
D:\anaconda\Scripts\pytest.exe app/tests/test_prospect_availability.py app/tests/test_draft_day_accuracy_mode.py -v

======================= 78 passed, 2 warnings in 6.78s ========================
```

汇总：78 passed, 0 failed, 0 error, 2 warnings

### 2. targeted backend suite

```
cd D:\DraftMind\backend
D:\anaconda\Scripts\pytest.exe app/tests/test_draft_day_accuracy_mode.py app/tests/test_simulation_service.py app/tests/test_simulate_api.py app/tests/test_ranking_engine.py -v

====================== 154 passed, 2 warnings in 13.26s =======================
```

汇总：154 passed, 0 failed, 0 error, 2 warnings

### 3. full backend suite

```
cd D:\DraftMind\backend
D:\anaconda\Scripts\pytest.exe app/tests -v

===================== 1534 passed, 560 warnings in 23.73s =====================
```

汇总：1534 passed, 0 failed, 0 error, 560 warnings（全部是 DeprecationWarning，与本次 patch 无关）

## 7. Frontend Build Result

```
cd D:\DraftMind\frontend
npm run build

> draftmind-frontend@0.1.0 build
> next build

   ✓ Compiled successfully in 1700ms
   ✓ Generating static pages (5/5)

Route (app)                                 Size  First Load JS
┌ ○ /                                      684 B         103 kB
├ ○ /_not-found                            993 B         103 kB
├ ○ /draft                               20.1 kB         122 kB
+ First Load JS shared by all             102 kB
```

Build 成功，无 error。本次未改 frontend 源码。

## 8. Real Local 60-Pick Smoke

使用真实本地 DB（`backend/draftmind.db`，598KB），不写 DB，不 seed。临时脚本 `scripts/tmp_verify_m4_cl_availability_patch.py` 运行后已删除。

### 4 种模式总览

| 模式 | total_picks | duplicates | unavailable_selected | mode 字段 |
|------|-------------|------------|----------------------|-----------|
| Default Auto Simulation | 60 | NONE | NONE | auto_simulation |
| Draft-Day Accuracy Mode | 60 | NONE | NONE | draft_day_accuracy |
| Both Flags | 60 | NONE | NONE | draft_day_accuracy |
| Calibration Only | 60 | NONE | NONE | auto_simulation |

### S1 == Both Flags

Draft-Day Accuracy Mode 与 Both Flags 的 selected player sequence 完全一致（60/60 picks 相同）。S1 consensus-priority 逻辑未被 calibration 吞掉。

### Safety Anchors（S1）

| Anchor | 期望范围 | 实际 pick | 结果 |
|--------|---------|-----------|------|
| Brayden Burries | [8, 13] | #11 | OK |
| Yaxel Lendeborg | [11, 14] | #12 | OK |
| Cameron Carr | [12, 17] | #13 | OK |

Niko Bundalo safety anchor 已取消（他现在 unavailable）。

### Replacement Picks（S1）

原问题球员被过滤后，由现有算法自然产生的 replacement：

| 原签位 | 原球员（已 unavailable） | 新球员（S1 自然产生） |
|--------|------------------------|---------------------|
| #13 | Braylon Mullins | Cameron Carr |
| #21 | Nikolas Khamenia | Chris Cenac Jr. |
| #25 | Cayden Boozer | Koa Peat |
| #29 | Jasper Johnson | Joshua Jefferson |
| #33 | Niko Bundalo | Ryan Conwell |

这些 replacement 不是 hardcode 的，是 ranking_engine + simulation_service 在过滤掉 unavailable 球员后自然选出的。

### Market-Risk Players（S1）

| Player | S1 pick |
|--------|---------|
| Kingston Flemings | #7 |
| Aday Mara | #9 |
| Hannes Steinbach | #17 |
| Christian Anderson | #20 |
| Dailyn Swain | #19 |
| Henri Veesaar | #23 |
| Alex Karaban | #30 |
| Tarris Reed Jr. | #31 |

8 个 market-risk players 全部仍在 S1 board 上（没有被加入 unavailable，因为目前没有代码/数据明确证据）。其中 none 被官方确认 unavailable。

### Draft-Day Accuracy Mode 完整 60-pick board

```
#01 WAS -> AJ Dybantsa (score=77.7)
#02 UTA -> Darryn Peterson (score=66.6)
#03 MEM -> Cameron Boozer (score=68.8)
#04 CHI -> Caleb Wilson (score=64.0)
#05 LAC -> Keaton Wagler (score=55.4)
#06 BKN -> Darius Acuff Jr. (score=58.9)
#07 SAC -> Kingston Flemings (score=55.2)
#08 ATL -> Mikel Brown Jr. (score=69.1)
#09 DAL -> Aday Mara (score=57.1)
#10 MIL -> Nate Ament (score=68.1)
#11 GSW -> Brayden Burries (score=61.1)
#12 OKC -> Yaxel Lendeborg (score=61.0)
#13 MIA -> Cameron Carr (score=61.1)
#14 CHA -> Labaron Philon Jr. (score=57.5)
#15 CHI -> Jayden Quaintance (score=62.0)
#16 MEM -> Karim Lopez (score=59.3)
#17 OKC -> Hannes Steinbach (score=56.9)
#18 CHA -> Morez Johnson Jr. (score=61.6)
#19 TOR -> Dailyn Swain (score=54.6)
#20 SAS -> Christian Anderson (score=63.4)
#21 DET -> Chris Cenac Jr. (score=61.6)
#22 PHI -> Bennett Stirtz (score=61.0)
#23 ATL -> Henri Veesaar (score=55.7)
#24 NYK -> Isaiah Evans (score=61.2)
#25 LAL -> Koa Peat (score=65.4)
#26 DEN -> Ebuka Okorie (score=62.5)
#27 BOS -> Allen Graves (score=64.2)
#28 MIN -> Meleek Thomas (score=58.7)
#29 CLE -> Joshua Jefferson (score=57.5)
#30 DAL -> Alex Karaban (score=54.1)
#31 NYK -> Tarris Reed Jr. (score=55.7)
#32 MEM -> Sergio De Larrea (score=60.2)
#33 BKN -> Ryan Conwell (score=57.5)
#34 SAC -> Zuby Ejiofor (score=55.7)
#35 SAS -> Richie Saunders (score=58.5)
#36 LAC -> Ugonna Onyenso (score=60.3)
#37 OKC -> Baba Miller (score=60.0)
#38 CHI -> Trevon Brazile (score=51.5)
#39 HOU -> Otega Oweh (score=65.9)
#40 BOS -> Nick Martinelli (score=55.7)
#41 MIA -> Jaden Bradley (score=54.0)
#42 SAS -> Jack Kayil (score=61.0)
#43 BKN -> Braden Smith (score=53.3)
#44 SAS -> Emanuel Sharp (score=53.3)
#45 SAC -> Ja'Kobi Gillespie (score=53.8)
#46 ORL -> Milos Uzan (score=60.4)
#47 PHX -> Bruce Thornton (score=60.1)
#48 DAL -> Tyler Nickel (score=50.5)
#49 DEN -> Felix Okpara (score=59.3)
#50 TOR -> Izaiyah Nelson (score=57.0)
#51 WAS -> Maliq Brown (score=64.0)
#52 LAC -> Tamin Lipsey (score=56.4)
#53 HOU -> Tobi Lawal (score=62.7)
#54 GSW -> Mark Mitchell (score=59.9)
#55 NYK -> Keyshawn Hall (score=54.0)
#56 CHI -> Rafael Castro (score=51.6)
#57 ATL -> Tyler Bilodeau (score=53.6)
#58 NOP -> Kylan Boswell (score=61.5)
#59 MIN -> Quadir Copeland (score=60.9)
#60 WAS -> Vsevolod Ishchenko (score=67.3)
```

`market_top30_missing_warnings` (S1): `[]`（空，无 warning）

## 9. Boundary Verification

逐条确认：

- ✅ no commit
- ✅ no push
- ✅ no tag
- ✅ no DB change（未运行 seed_db.py，未写 draftmind.db）
- ✅ no CSV change
- ✅ no seed change（未改 seed_db.py）
- ✅ no ranking_engine change（未改 ranking_engine.py）
- ✅ no simulation_service change（未改 simulation_service.py）
- ✅ no draft_day_accuracy scoring/order formula change（未改 draft_day_accuracy.py）
- ✅ no frontend source change（未改 frontend/*，只跑了 build smoke）
- ✅ no Final Accuracy Board production read（未读 docs/final-accuracy-board-m4-bx.md）
- ✅ no hardcoded replacement pick（replacement 由现有算法自然产生）
- ✅ no team-fit patch（未碰 team-fit 逻辑）
- ✅ temporary script deleted（`scripts/tmp_verify_m4_cl_availability_patch.py` 已删除，不在 git status）
- ✅ no `if team == Lakers` / `if team == Dallas` override
- ✅ no `if player == Cayden then Lakers 改选谁` override
- ✅ `pre-draft-final-freeze-2026` tag 未被修改/删除/重打

## 10. Final Git Status

```
git status --short
 M backend/app/services/prospect_availability.py
 M backend/app/tests/test_draft_day_accuracy_mode.py
 M backend/app/tests/test_prospect_availability.py
 M backend/app/tests/test_recommend_api.py
 M backend/app/tests/test_simulation_service.py
?? m4-cl.md
?? docs/return-to-school-availability-guard-m4-cl.md

git diff --stat
 backend/app/services/prospect_availability.py     |  43 ++++-
 backend/app/tests/test_draft_day_accuracy_mode.py | 196 ++++++++++++++++++++--
 backend/app/tests/test_prospect_availability.py   | 125 +++++++++++++-
 backend/app/tests/test_recommend_api.py           |  16 +-
 backend/app/tests/test_simulation_service.py      | 176 ++++++++++++++-----
 5 files changed, 491 insertions(+), 65 deletions(-)
```

## 11. Recommendation

Recommended commit message:
```
Add return-to-school availability guard
```

Recommended tag:
```
return-to-school-availability-guard-m4-cl
```

Do not commit, push, or tag. Final decision belongs to ChatGPT.

### 额外说明

本次实际改了 5 个文件，比 spec "允许改动文件" 列表多了 2 个：
- `backend/app/tests/test_simulation_service.py`
- `backend/app/tests/test_recommend_api.py`

原因：availability guard 改变后，这 2 个测试文件里的测试因为引用了现已 unavailable 的球员（Braylon Mullins / Niko Bundalo）而失败。它们是 "相关测试"（spec 第 15 条）。修改原则是更新测试 fixture 引用和断言，不改测试意图，不改被测代码。

如果 ChatGPT 认为这 2 个文件不应改，可以把它们 revert，然后 full backend suite 会有 19 个 failure（18 in test_simulation_service.py + 1 in test_recommend_api.py），状态应改为 NEEDS_TARGETED_FIX。
