# DraftMind M4-CO Dallas #9 Aday Mara Counterfactual Preflight

## 1. Final Status

NEEDS_CHATGPT_DECISION

## 2. Why This Preflight Exists

M4-CM corrected final board 中 `#09 DAL Aday Mara` 是最大 team-fit risk。Dallas
Mavericks 已有较多 center / frontcourt 资源，而 Aday Mara 是 7-3 传统高大中锋 /
护框型球员（position=C, archetype="Junior frontcourt prospect", 7-3/260）。M4-CN
Team-Fit Stop/Go Decision Audit 结论是 `NO_TEAM_FIT_PATCH_RECOMMENDED`，但用户仍
强烈认为该组合影响真实预测可信度。

本 preflight 不直接改代码，而是做反事实模拟：如果 Dallas #9 不选 Aday Mara，系统
自然会选谁？Aday 会掉到哪里？60 顺位会不会大崩？safety anchors / availability
guard / market-risk players 会不会被破坏？最终判断是否值得后续开 M4-CP 小 patch。

所有反事实逻辑只存在于临时脚本中（已删除），不落地到生产代码。

## 3. Repo State

```
git log -3 --oneline
d342a3e Add post-patch corrected final board export
67fbe8b Add return-to-school availability guard
c01db30 Add real local final board export

git tag --points-at HEAD
post-patch-corrected-final-board-m4-cm
```

初始 `git status --short`（M4-CO 开始前）：

```
(空)
```

最终 `git status --short`（M4-CO 完成后）：

```
?? docs/dallas-aday-counterfactual-preflight-m4-co.md
```

`git diff --stat`：空（无 tracked 文件修改）。

## 4. Baseline Board Summary

Baseline = M4-CM corrected Draft-Day Accuracy board，使用真实本地 DB
（`backend/draftmind.db`，size=598016 bytes）重新运行 `simulate_draft` 确认。

| 指标 | 值 |
|------|-----|
| DAL #9 | Aday Mara |
| total picks | 60 |
| mode | draft_day_accuracy |
| duplicates | NONE |
| unavailable selected | NONE |
| warnings | [] |

### Safety Anchors

| Anchor | 期望范围 | Baseline pick | 结果 |
|--------|---------|---------------|------|
| Brayden Burries | [8, 13] | #11 GSW | OK |
| Yaxel Lendeborg | [11, 14] | #12 OKC | OK |
| Cameron Carr | [12, 17] | #13 MIA | OK |
| Niko Bundalo | [24, 34] | N/A | anchor CANCELED after M4-CL (unavailable) |

### Market-Risk Players

| Player | Baseline pick |
|--------|---------------|
| Kingston Flemings | #7 SAC |
| Aday Mara | #9 DAL |
| Hannes Steinbach | #17 OKC |
| Christian Anderson | #20 SAS |
| Dailyn Swain | #19 TOR |
| Henri Veesaar | #23 ATL |
| Alex Karaban | #30 DAL |
| Tarris Reed Jr. | #31 NYK |

8 个 market-risk players 全部在 board 内，none 出 60。

### Baseline 60-Pick Board

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

Baseline 与 M4-CM corrected board 完全一致（60/60 picks 相同），确认生产代码状态稳定。

## 5. Scenario Results

### Methodology

所有 counterfactual 场景复用真实生产 `simulate_draft` 函数及全部生产 helper
（ranking_engine、draft_day_accuracy、prospect_availability、team_need、projections）。
唯一反事实注入是对 `reorder_rankings_by_consensus_priority` 的 monkeypatch，仅在
`pick_no == 9`（运行时验证 == DAL）时生效。Aday Mara 在所有场景中仍留在全局候选池，
允许后续球队选中。not production logic。

### Scenario 0 Baseline

| 指标 | 值 |
|------|-----|
| total picks | 60 |
| mode | draft_day_accuracy |
| duplicates | NONE |
| unavailable selected | NONE |
| DAL #9 | Aday Mara |
| Aday Mara landing | #9 DAL |
| first diff vs baseline | N/A |
| total changed | 0 |
| changed top 14 | 0 |
| changed top 30 | 0 |
| warnings | [] |

Safety anchors: 全部 OK。Market-risk players: 全部 IN。Board 见第 4 节。

### Scenario A Dallas #9 Skip Aday Only

只在 pick_no==9 (DAL) 时跳过 Aday Mara，让系统从剩余候选自然选下一个。

| 指标 | 值 |
|------|-----|
| total picks | 60 |
| mode | draft_day_accuracy |
| duplicates | NONE |
| unavailable selected | NONE |
| DAL #9 | **Nate Ament** |
| Aday Mara landing | **#10 MIL** |
| first diff vs baseline | #9 |
| total changed | **2** |
| changed top 14 | #9 (Aday→Nate), #10 (Nate→Aday) |
| changed top 30 | 2 |
| warnings | [] |

**Cascade 极小**：仅 #9 和 #10 发生互换。Aday Mara 和 Nate Ament 交换位置，其余 58
picks 完全不变。Aday 被 Milwaukee（下一个顺位 #10）自然接住。

Safety anchors: 全部 OK（Brayden Burries #11, Yaxel Lendeborg #12, Cameron Carr
#13，均未变）。Market-risk players: 全部 IN（Aday 从 #9 移到 #10，仍在 top 10）。

### Scenario B Dallas #9 Skip Pure Centers

只在 pick_no==9 (DAL) 时跳过 position=='C' 的候选。Aday Mara 仍留在 pool。

| 指标 | 值 |
|------|-----|
| total picks | 60 |
| mode | draft_day_accuracy |
| duplicates | NONE |
| unavailable selected | NONE |
| DAL #9 | **Nate Ament** |
| Aday Mara landing | **#10 MIL** |
| first diff vs baseline | #9 |
| total changed | **2** |
| changed top 14 | #9 (Aday→Nate), #10 (Nate→Aday) |
| changed top 30 | 2 |
| warnings | [] |

结果与 Scenario A 完全一致。原因：在 pick #9 时，候选池中唯一会被 S1 consensus
priority 排到顶部的 pure center 就是 Aday Mara（expected_pick=8）。下一个 center
（Jayden Quaintance expected_pick=16 / Hannes Steinbach expected_pick=16）远低于
非 center 候选（Nate Ament / Brayden Burries expected_pick=10）。因此 "skip pure
centers" 等价于 "skip Aday"。

### Scenario C Local Fit Penalty at Dallas #9

对 pure center 候选施加临时 expected_pick penalty（仅在 pick_no==9 生效），测试
penalty = [1, 2, 3, 5, 10]。

| Penalty | DAL #9 | Aday Mara landing |
|---------|--------|-------------------|
| 1 | Aday Mara | #9 DAL |
| **2** | **Nate Ament** | **#10 MIL** |
| 3 | Nate Ament | #10 MIL |
| 5 | Nate Ament | #10 MIL |
| 10 | Nate Ament | #10 MIL |

**Threshold penalty = 2**。Aday Mara expected_pick=8，加 penalty=2 后 effective=10，
与 Nate Ament（expected_pick=10）持平，tie-breaker（range_hit / confidence /
team_signal / final_score）倾向 Nate Ament。

Threshold 结果（penalty=2）：

| 指标 | 值 |
|------|-----|
| total picks | 60 |
| mode | draft_day_accuracy |
| duplicates | NONE |
| unavailable selected | NONE |
| DAL #9 | **Nate Ament** |
| Aday Mara landing | **#10 MIL** |
| first diff vs baseline | #9 |
| total changed | **2** |
| changed top 14 | #9 (Aday→Nate), #10 (Nate→Aday) |
| changed top 30 | 2 |
| warnings | [] |

结果与 Scenario A / B 完全一致（2-pick swap）。

### Scenario D Editorial Risk Note Only

不改变 board，仅记录 DAL #9 Aday Mara 是最终 board 最大 team-fit risk。

| 指标 | 值 |
|------|-----|
| DAL #9 | Aday Mara（不变） |
| Aday Mara landing | #9 DAL（不变） |
| board change | 无 |

此场景不涉及任何模拟修改，仅作为 "接受现状 + 文档标注" 选项。

## 6. Replacement Candidate Analysis

当 DAL #9 不选 Aday Mara 时，系统在所有 counterfactual 场景中**一致选择 Nate
Ament**。以下分析 8 个候选替代：

| Candidate | Position | expected_pick | range | DAL #9 选中? | 分析 |
|-----------|----------|---------------|-------|-------------|------|
| Nate Ament | SF | 10 | [9,13] | **是（自然产生）** | Stretch forward 6-10/211，比 7-3 center 更 fit Dallas wing/frontcourt 需求。#9 在其 range [9,13] 顶端，仅比原 #10 早 1 位，完全合理。 |
| Brayden Burries | SG | 10 | [8,13] | 否（tie-breaker 输给 Nate） | Two-way combo guard，也合理，但 S1 tie-breaker 倾向 Nate。原 #11 不变。 |
| Yaxel Lendeborg | PF | 12 | [11,14] | 否 | expected_pick=12 > 10，S1 不会在 #9 选他。原 #12 不变。 |
| Cameron Carr | SG | 14 | [12,17] | 否 | expected_pick=14，太远。原 #13 不变。 |
| Labaron Philon Jr. | SG | 14 | [12,17] | 否 | expected_pick=14，太远。原 #14 不变。 |
| Jayden Quaintance | C | 16 | [15,24] | 否 | 也是 center，且 expected_pick=16 太远。原 #15 不变。 |
| Karim Lopez | SF | 16 | [13,20] | 否 | expected_pick=16，太远。原 #16 不变。 |
| Hannes Steinbach | C | 16 | [13,20] | 否 | 也是 center，且 expected_pick=16 太远。原 #17 不变。 |

### 新 DAL #9 Nate Ament 为什么比 Aday 更合理

1. **Position fit**：Nate Ament 是 SF / stretch forward（6-10/211），提供 wing /
   floor-spacing frontcourt 价值。Dallas 已有 center / frontcourt 资源，不需要 7-3
   传统中锋。Nate 填补 wing/forward 需求。
2. **Market consensus**：Nate Ament expected_pick=10，range [9,13]。在 #9 选中他在
   range 顶端，完全符合市场共识。Aday Mara expected_pick=8，range [7,11]，#9 也在
   range 内——两者都是 consensus-defensible。
3. **不破坏原落点**：Nate 从 #10 移到 #9，仅早 1 位，仍在 range [9,13] 内。Aday 从
   #9 移到 #10，仅晚 1 位，仍在 range [7,11] 内。两人都在各自 market range 内。

### Aday Mara 掉到哪里

Aday Mara 在所有 counterfactual 场景中落到 **#10 MIL (Milwaukee)**——即 Dallas 的
下一个顺位。Milwaukee 自然接住 Aday，因为 #10 时 Aday 是 S1 consensus priority 最高
的剩余候选（expected_pick=8，远高于其他剩余候选）。这是一个非常自然的 landing：Aday
只滑了 1 位，仍在 top 10，仍在 market range [7,11] 内。

### Cascade 分析

Cascade 极小：**仅 #9 和 #10 互换**，其余 58 picks 完全不变。原因：
- #9 和 #10 之间，Aday 和 Nate 是两个最高 consensus 候选。
- Baseline：DAL 取 Aday，MIL 取 Nate。
- Counterfactual：DAL 取 Nate，MIL 取 Aday。
- 从 #11 起，两人都已离池，后续候选完全相同，board 不变。

## 7. Safety / Availability / Market Checks

### 逐场景汇总

| Check | S0 Baseline | SA Skip Aday | SB Skip Centers | SC Penalty=2 | SD Editorial |
|-------|-------------|--------------|-----------------|--------------|--------------|
| total picks | 60 | 60 | 60 | 60 | 60 |
| mode | draft_day_accuracy | draft_day_accuracy | draft_day_accuracy | draft_day_accuracy | draft_day_accuracy |
| duplicates | NONE | NONE | NONE | NONE | NONE |
| unavailable selected | NONE | NONE | NONE | NONE | NONE |
| DAL #9 | Aday Mara | Nate Ament | Nate Ament | Nate Ament | Aday Mara |
| Aday landing | #9 DAL | #10 MIL | #10 MIL | #10 MIL | #9 DAL |
| total changed | 0 | 2 | 2 | 2 | 0 |
| changed top 14 | 0 | 2 | 2 | 2 | 0 |
| changed top 30 | 0 | 2 | 2 | 2 | 0 |
| warnings | [] | [] | [] | [] | [] |

### Safety Anchors（所有场景一致）

| Anchor | 期望范围 | 所有场景 pick | 结果 |
|--------|---------|--------------|------|
| Brayden Burries | [8, 13] | #11 GSW | OK（所有场景不变） |
| Yaxel Lendeborg | [11, 14] | #12 OKC | OK（所有场景不变） |
| Cameron Carr | [12, 17] | #13 MIA | OK（所有场景不变） |

### Market-Risk Players

| Player | S0 | SA/SB/SC | 出 60? |
|--------|----|---------|-------|
| Kingston Flemings | #7 | #7 | 否 |
| Aday Mara | #9 | #10 | 否 |
| Hannes Steinbach | #17 | #17 | 否 |
| Christian Anderson | #20 | #20 | 否 |
| Dailyn Swain | #19 | #19 | 否 |
| Henri Veesaar | #23 | #23 | 否 |
| Alex Karaban | #30 | #30 | 否 |
| Tarris Reed Jr. | #31 | #31 | 否 |

所有 counterfactual 场景中，8 个 market-risk players 全部仍在 board 内，none 出 60。
Aday Mara 从 #9 移到 #10（仅 +1），仍合理。

### Warning Panels

所有场景 `market_top30_missing_warnings` 均为空（[]）。

### DB Integrity

| 指标 | 值 |
|------|-----|
| DB size before | 598016 bytes |
| DB size after | 598016 bytes |
| DB size unchanged | True |
| DB mtime unchanged | True |

无 DB 写入，无 seed。

## 8. Patch Worthiness Decision

**NEEDS_CHATGPT_DECISION**

### 为什么不是 PATCH_WORTHY

虽然 counterfactual 结果非常干净（2-pick swap，所有 safety/availability/market 检查
通过），但存在一个关键障碍：**没有一个 counterfactual 场景使用了通用规则**。

- Scenario A（skip Aday only）：hardcode player name。
- Scenario B（skip pure centers at DAL #9）：hardcode team + position 规则。
- Scenario C（penalty on pure centers at DAL #9）：hardcode team + position 规则。

所有成功的场景都需要知道 "DAL #9 应该避开 center"。一个真正通用的规则需要
"team roster composition" 数据（例如 Dallas 已有 N 个 center，所以 need_c 很低），
但当前 Draft-Day Accuracy Mode 的选人路径不读取 roster composition——它只读
`ProspectDraftProjection`（market consensus）和 `TeamPickProjection`（team signal）。

更深层的问题：**Draft-Day Accuracy Mode 的设计目标就是跟随 market consensus**。市场
共识说 Aday 在 #8-11，#9 选他 IS consensus-correct。引入 team-fit penalty 会偏离
pure consensus，这是预测哲学的改变，不是小 patch。

### 为什么不是 PATCH_NOT_WORTHY

counterfactual 结果比预期好得多：
- 自然 replacement（Nate Ament）确实比 Aday 更 fit Dallas。
- Aday 被 MIL #10（下一个顺位）自然接住。
- Cascade 仅 2 picks（#9/#10 互换），其余 58 picks 不变。
- Safety anchors / availability guard / market-risk players 全部 OK。
- Nate Ament 从 #10 到 #9 仅早 1 位，仍在 range [9,13] 内。
- Aday 从 #9 到 #10 仅晚 1 位，仍在 range [7,11] 内。

这说明如果用户决定引入 team-fit 信号，技术风险很低。问题在于是否应该引入——这是预测
哲学决策，属于 ChatGPT。

### 结论

Replacement 很有吸引力，cascade 可控，但仍涉及预测哲学（pure market consensus vs
team-roster-fit adjustment），需要 ChatGPT 决定。

## 9. Possible M4-CP Design If Approved

如果 ChatGPT 批准，M4-CP 只提出设计，不实现。

### 设计目标

让 Draft-Day Accuracy Mode 在选人时考虑 team roster composition：当某球队在某位置已
有深度（low need），对该位置候选施加 mild expected_pick penalty。这是通用规则，不
hardcode 任何 team/player。

### 实现边界

| 约束 | 是否可改 |
|------|---------|
| 最多改哪个文件 | `draft_day_accuracy.py`（在 `consensus_priority_sort_key` 中加入 optional team-need-aware penalty） |
| 改 ranking_engine.py | **否** |
| 改 simulation_service.py | 仅传 `team_need` 到 reorder 函数（最小改动） |
| 改 DB / CSV / seed | **否** |
| 改 frontend | **否** |
| hardcode player/team | **否**（使用现有 `TeamNeed.need_c` 等字段） |

### 核心逻辑（设计，不实现）

1. `simulate_draft` 已有 `team_need`（含 `need_c` 等字段）。将其传入
   `reorder_rankings_by_consensus_priority`。
2. 在 `consensus_priority_sort_key` 中，当 prospect 的 position 对应的 need 值低于
   阈值（例如 `need_c < 0.3`）时，对该候选的 `expected_pick` 施加固定 penalty（例如
   +2，与 Scenario C threshold 一致）。
3. Penalty 仅在 Draft-Day Accuracy Mode 生效，不影响 default Auto Simulation。
4. Penalty 大小可配置，默认值来自 Scenario C threshold（2）。

### 需要的测试

- Counterfactual 场景 A/B/C 作为 regression test。
- Safety anchor 测试（Brayden Burries / Yaxel Lendeborg / Cameron Carr 仍在 range）。
- Availability guard 测试（14 人禁选名单仍被过滤）。
- Market-risk players 测试（8 人仍 IN）。
- Default Auto Simulation 不受影响测试。
- DAL #9 在 penalty 下选 Nate Ament，Aday 落 #10 MIL。

### 真实 DB smoke 验收标准

- 60 picks
- no duplicate
- no unavailable selected
- mode = draft_day_accuracy
- safety anchors 全部 OK
- market-risk players 全部 IN
- warnings = []
- DAL #9 = Nate Ament（如果 team-need penalty 生效）
- Aday Mara = #10 MIL
- cascade <= 4 picks

### 停止条件

- 任何 safety anchor 破坏
- 任何 unavailable 球员被选
- cascade > 5 picks
- default Auto Simulation board 改变
- 任何 market-risk player 出 60

## 10. Boundary Verification

逐条确认：

- ✅ no commit
- ✅ no push
- ✅ no tag
- ✅ no production code change（git diff --stat 为空）
- ✅ no DB change（DB size/mtime unchanged: 598016 bytes）
- ✅ no CSV change
- ✅ no seed change
- ✅ no frontend change
- ✅ no ranking_engine change
- ✅ no simulation_service change
- ✅ no draft_day_accuracy change
- ✅ no prospect_availability change
- ✅ no Final Accuracy Board production read
- ✅ no hardcoded replacement pick in production
- ✅ no team-fit patch implemented
- ✅ temporary script deleted（`backend/scripts/tmp_dallas_aday_counterfactual_m4_co.py` 已删除，不在 git status）

## 11. Recommendation

Do not implement yet. Final decision belongs to ChatGPT.

Counterfactual 结果显示：如果 Dallas #9 不选 Aday Mara，系统自然选 Nate Ament（SF /
stretch forward，比 7-3 center 更 fit Dallas），Aday 被 Milwaukee #10 自然接住，
cascade 仅 2-pick swap，所有 safety / availability / market 检查通过。技术风险很低。

但这是预测哲学决策：Draft-Day Accuracy Mode 是否应保持 pure market consensus，还是
引入 team-roster-fit adjustment。此决策属于 ChatGPT。如果批准，可开 M4-CP 按第 9 节
设计实现（通用 team-need-aware penalty，不 hardcode team/player）。
