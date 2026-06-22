# DraftMind M4-CP Draft-Day Team-Need Penalty Patch

## 1. Final Status

NEEDS_CHATGPT_DECISION

## 2. Why This Patch Exists

M4-CO 证明 Dallas #9 不选 Aday 时，系统自然 #9 Nate Ament / #10 Aday Mara，只有
2-pick swap，所有 safety / availability / market 检查通过。本 patch 尝试用通用
team-need penalty 落地该结果，而不是 hardcode。

经过 Step 3 数据结构检查和真实 DB 验证，发现现有 `TeamNeedSnapshot` 数据**不支持**
通用 team-need penalty 达成目标。原因详见第 5 节。

## 3. Repo State

```
git log -5 --oneline
fef5773 Add Dallas Aday counterfactual preflight
d342a3e Add post-patch corrected final board export
67fbe8b Add return-to-school availability guard
c01db30 Add real local final board export
6a6eded Add pre-draft final freeze audit

git tag --points-at HEAD
dallas-aday-counterfactual-preflight-m4-co
```

初始 `git status --short`（M4-CP 开始前）：

```
(空)
```

最终 `git status --short`（M4-CP 完成后）：

```
?? docs/draft-day-team-need-penalty-m4-cp.md
```

`git diff --stat`：空（无 tracked 文件修改）。

## 4. Files Changed

无生产代码文件修改。

仅创建：
- `docs/draft-day-team-need-penalty-m4-cp.md`（本报告）

临时脚本 `backend/scripts/tmp_inspect_m4_cp.py` 已创建、使用、删除，不在 git status。

## 5. Implementation Summary

### 结论：无法用通用规则实现

经过 Step 3 数据结构检查，发现现有 `TeamNeedSnapshot` 数据不支持通用 team-need
penalty 达成 #9 Nate Ament / #10 Aday Mara 的目标。

### 5.1 数据结构确认

`TeamNeedSnapshot`（`backend/app/services/team_need_adjustment.py`）字段：

```
need_pg: int  (范围 [1, 10])
need_sg: int  (范围 [1, 10])
need_sf: int  (范围 [1, 10])
need_pf: int  (范围 [1, 10])
need_c:  int  (范围 [1, 10])
need_shooting: int
need_defense: int
need_creation: int
```

`Prospect.position` 为单字符串：`C`, `PF`, `SF`, `SG`, `PG`（真实 DB 中无 combo
位置）。

`ProspectDraftProjection.expected_pick` 为 int (1-100)。

`reorder_rankings_by_consensus_priority`（`backend/app/services/draft_day_accuracy.py`）
当前签名不接收 `team_need`，但 `simulate_draft` 在调用时已有 `team_need` 可传。

### 5.2 真实 DB 验证结果

使用真实本地 DB (`backend/draftmind.db`, read-only) 验证：

**DAL 和 MIL 在 `team_needs` 表中无 2026 年记录**。只有 SAS, HOU, WAS, DET, POR
有显式 `team_needs` 行。DAL/MIL 的 team need 由 `get_or_infer_team_need` 从 roster
推断。

**DAL roster (2025-26, 18 players):**

| 位置类别 | 球员数 | 球员 |
|---------|--------|------|
| G | 7 | Poulakidas, Christie, Johnson, Nembhard, Williams, Irving, Thompson |
| F | 9 | Marshall, Martin, Middleton, Smith, Washington, Flagg, Bagley III, Powell(F-C), Gafford(F-C) |
| C | 4 | Lively II, Cisse, Powell(F-C), Gafford(F-C) |

**DAL 推断 needs:**

```
need_pg = 4
need_sg = 4
need_sf = 3   ← LOW (forward count 9 >= target 6+2=8)
need_pf = 4
need_c  = 4   ← MODERATE (center count 4, target 3, 4 < 3+2=5)
```

**MIL roster (2025-26, 17 players):** G=7, F=10, C=2

**MIL 推断 needs:**

```
need_pg = 4
need_sg = 4
need_sf = 3   ← LOW
need_pf = 4
need_c  = 6   ← HIGH (center count 2 < target 3)
```

**Prospect positions (真实 DB):**

| Player | Position | expected_pick | range | confidence |
|--------|----------|---------------|-------|------------|
| Aday Mara | C | 8 | [7, 11] | 0.74 |
| Nate Ament | SF | 10 | [9, 13] | 0.74 |

**Team pick projections:** DAL 和 pick 9/10 均无 `team_pick_projections` 记录。

### 5.3 为什么通用规则无法达成目标

设计目标是让 DAL #9 不选 Aday Mara (C)，改选 Nate Ament (SF)。通用 penalty 逻辑
为：如果 prospect 的 position 对应 team need 很低，则给 expected_pick 加 penalty。

但真实数据显示：

1. **DAL need_c = 4（moderate，不是 low）**。DAL roster 有 4 个 center-eligible
   球员（Lively II, Cisse, Powell F-C, Gafford F-C），target=3，count=4 <
   target+2=5，所以 `need_c = max(3, min(9, 5+(3-4))) = 4`。任何合理的 low-need
   阈值（≤3）都不会对 Aday Mara 触发 penalty。

2. **DAL need_sf = 3（low）**。DAL 有 9 个 forward-eligible 球员，远超 target+2=8。
   所以 `need_sf = 3`。通用 penalty 规则**反而会对 Nate Ament (SF) 触发 penalty**，
   让 Nate 更难被选中——这与目标完全相反。

3. **如果放宽阈值到 ≤4**：Aday (need_c=4) 和 Nate (need_sf=3) 都会被 penalty，但
   Nate 的 need 更低（3 < 4），如果使用 graduated penalty（need 越低 penalty 越大），
   Nate 的 penalty 会比 Aday 更大。即使使用固定 penalty=2：
   - Aday effective_expected_pick = 8 + 2 = 10
   - Nate effective_expected_pick = 10 + 2 = 12
   - Aday (10) 仍排在 Nate (12) 前面。不产生 swap。

4. **MIL need_c = 6（high）**。MIL 确实需要 center（roster 只有 2 个 C），这解释了
   为什么 counterfactual 中 Aday 自然掉到 MIL #10。但这对 DAL #9 的选择没有帮助。

### 5.4 尝试过的所有通用方案

| 方案 | 结果 |
|------|------|
| threshold ≤ 3, fixed penalty=2 | Aday 不触发 (need_c=4)，无效果 |
| threshold ≤ 4, fixed penalty=2 | 两人都触发，Aday(10) 仍排 Nate(12) 前 |
| graduated penalty = (5 - need) | Aday penalty=1 (eff=9)，Nate penalty=2 (eff=12)，Aday 仍在前 |
| graduated penalty = (max_need - pos_need) | Nate penalty 更大（need_sf 更低），方向相反 |
| relative need (below average) | 两人都 below average，Nate 更低，方向相反 |
| only penalize lowest-need position | need_sf=3 是最低，只 penalize Nate，方向相反 |
| bonus high-need positions | need_c=4 不是 high，need_sf=3 不是 high，无效果 |
| use raw roster count | C=4 vs target=3 → 1 above target；F=9 vs target=6 → 3 above target。Forward 更 overstocked，方向相反 |

所有通用方案都无法达成目标。根本原因是 **DAL 的 team need 推断数据认为 DAL 更
需要 center (need_c=4) 而不是 small forward (need_sf=3)**，这与人类判断（"DAL 已有
较多 center 资源，不需要 7-3 传统中锋"）相反。

### 5.5 根本原因

`get_or_infer_team_need` 的推断逻辑（`team_need_service.py`）使用简单的位置计数：

- Center target = 3，DAL 有 4 个 C-eligible 球员 → need_c = 4（moderate）
- Forward target = 6，DAL 有 9 个 F-eligible 球员 → need_sf = 3（low）

该逻辑不考虑：
- 球员质量（Lively II 是 franchise starter，Gafford 是高质量 backup）
- 球员年龄/合同（Powell 是老将）
- 位置深度 vs 位置需求（4 个 center 对 18 人 roster 已经足够）
- F-C 球员对 center 位置的覆盖（Powell 和 Gafford 实际上经常打 center）

要让通用 penalty 生效，需要以下之一（均超出本任务允许范围）：
1. 修改 `team_need_service.py` 的推断逻辑（不允许）
2. 为 DAL 添加显式 `team_needs` 行，设 need_c=2 或 3（不允许改 DB）
3. Hardcode `if team == DAL and player == Aday`（明确禁止）
4. 引入 roster composition 直接分析（超出最小 patch 范围，且需要改 simulation_service 数据流）

## 6. Test Results

无测试运行——未做任何代码修改。

## 7. Real Local DB Smoke

无 smoke test 运行——未做任何代码修改。

仅进行了 read-only DB inspection（使用临时脚本，已删除），确认：
- DB size unchanged
- DB mtime unchanged
- 无 DB 写入

## 8. Corrected 60-Pick Board After Patch

无变化。Board 与 M4-CM baseline 完全一致（未做任何代码修改）：

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
... (其余 50 picks 与 M4-CM baseline 完全一致)
```

## 9. Dallas / Aday Result

| 指标 | 值 |
|------|-----|
| DAL #9 selected player | Aday Mara（未改变） |
| MIL #10 selected player | Nate Ament（未改变） |
| Aday Mara final pick/team | #9 DAL（未改变） |
| Nate Ament final pick/team | #10 MIL（未改变） |
| changed picks vs M4-CM baseline | 0（未做任何修改） |
| 与 M4-CO counterfactual 一致? | 否（counterfactual 需要 hardcode skip/penalty at DAL #9） |

## 10. Safety / Market / Warning Checks

无变化——未做任何代码修改。所有检查与 M4-CM baseline 一致：

### Safety Anchors

| Anchor | 期望范围 | Pick | 结果 |
|--------|---------|------|------|
| Brayden Burries | [8, 13] | #11 GSW | OK |
| Yaxel Lendeborg | [11, 14] | #12 OKC | OK |
| Cameron Carr | [12, 17] | #13 MIA | OK |

### Market-Risk Players

全部 IN，位置不变。

### Warning Panels

空（[]）。

## 11. Boundary Verification

逐条确认：

- ✅ no commit
- ✅ no push
- ✅ no tag
- ✅ no DB change（DB size/mtime unchanged）
- ✅ no CSV change
- ✅ no seed change
- ✅ no frontend source change
- ✅ no ranking_engine change
- ✅ no prospect_availability change
- ✅ no draft_day_accuracy change
- ✅ no simulation_service change
- ✅ no Final Accuracy Board production read
- ✅ no hardcoded player/team
- ✅ no hardcoded replacement pick
- ✅ temp script deleted（`backend/scripts/tmp_inspect_m4_cp.py` 已删除，不在 git status）
- ✅ no production code change of any kind（git diff --stat 为空）

## 12. Recommendation

### Final Status: NEEDS_CHATGPT_DECISION

通用 team-need penalty **无法**在不 hardcode 的前提下达成 #9 Nate Ament / #10 Aday
Mara 的目标。

### 根本障碍

DAL 的 `TeamNeedSnapshot.need_c = 4`（moderate，非 low），而 `need_sf = 3`（low）。
任何基于现有 team need 数据的通用 penalty 规则要么不触发 Aday，要么反而 penalize
Nate Ament 更多。数据方向与目标相反。

### 可能的后续路径（需要 ChatGPT 决策）

1. **接受现状**：DAL #9 Aday Mara 保持不变。M4-CO Scenario D（editorial note only）。
   这是 pure market consensus 的结果，Aday expected_pick=8 在 #9 选中是
   consensus-correct。

2. **修改 team need 推断逻辑**（超出 M4-CP 范围）：调整 `team_need_service.py`
   中 center target 或 F-C 球员的计数方式，使 DAL 的 need_c 降低到 ≤3。但这会影响
   所有球队的推断，需要单独评估。

3. **为 DAL 添加显式 team_needs 行**（需要 DB 变更）：在 `team_needs` 表中为 DAL
   添加 2026 年记录，设 need_c=2。但这违反 "no DB change" 约束。

4. **引入 roster composition 直接分析**（较大改动）：在 `simulation_service.py`
   中直接读取 roster，计算位置饱和度，传入 reorder 函数。这比 "最小 patch" 范围大，
   且需要更仔细的 cascade 分析。

5. **接受 M4-CO counterfactual 作为 editorial override**（需要 hardcode）：在
   Draft-Day Accuracy Mode 中对特定 pick 做 counterfactual override。但这违反 "no
   hardcode" 约束。

### 不推荐 commit / push / tag

本任务未做任何生产代码修改，无需 commit。仅创建本报告文档。

Do not commit, push, or tag. Final decision belongs to ChatGPT.
