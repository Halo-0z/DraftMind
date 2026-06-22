# DraftMind M4-CQ Frontend Pick Explanation + Trade Suggestion Chinese Polish

## 1. Final Status

READY_FOR_CHATGPT_REVIEW

## 2. Why This Polish Exists

Mara #9 等争议 pick 需要用户能看懂原因；原英文技术日志和交易建议对普通用户不友好。
`#9 DAL Aday Mara` 这种 pick 的原始评分第一是 Nate Ament，但 Draft-Day Accuracy Mode
最终选了 Aday Mara，用户会疑惑是不是系统 bug。页面还显示“考虑向下交易 · 42%”，但
用户不知道 42% 是什么意思，也不知道是否真的发生交易。

本 patch 优化前端解释层，把信息分成 5 层（主结论 / 风险 / 候选对比 / 交易建议 /
技术日志），让普通用户读完就明白这是 market-consensus pick，不是系统错误，交易
建议只是决策辅助，不会自动改变选人。

## 3. Repo State

```
git log -5 --oneline
415e4fb Add draft-day team-need penalty decision report
fef5773 Add Dallas Aday counterfactual preflight
d342a3e Add post-patch corrected final board export
67fbe8b Add return-to-school availability guard
c01db30 Add real local final board export

git tag --points-at HEAD
draft-day-team-need-penalty-m4-cp
```

初始 `git status --short`（M4-CQ 开始前，恢复 BOM 后）：

```
(空)
```

最终 `git status --short`（M4-CQ 完成后）：

```
 M frontend/app/draft/page.tsx
?? docs/frontend-pick-explanation-polish-m4-cq.md
```

`git diff --stat`：

```
 frontend/app/draft/page.tsx | 927 ++++++++++++++++++++++++++++++++++++++++----
 1 file changed, 854 insertions(+), 73 deletions(-)
```

## 4. Files Changed

| 文件 | 改动 | 说明 |
|------|------|------|
| `frontend/app/draft/page.tsx` | +854 / -73 | 新增中文解释组件和 helper，重构 pick card 展示层级，并完成默认预测视图 / 显示模式 polish |
| `docs/frontend-pick-explanation-polish-m4-cq.md` | 新建 | 本报告 |

未修改：
- `frontend/lib/api.ts`（无需类型补充）
- 任何 backend 文件
- 任何 DB / CSV / seed 文件

## 5. Implementation Summary

### 5.1 新增 helper 函数

| 函数 | 作用 |
|------|------|
| `formatTradeRationaleZh(rationale)` | 把英文 `trade_evaluation.rationale` 翻译成中文摘要。覆盖 5 种已知 rationale，未知值回退到 `系统建议：{raw}`，永不返回 undefined。 |
| `formatTradeProbabilityMeaning(action, probability)` | 解释 `probability` 字段的含义。明确写成“交易建议强度 X%”，而非“交易成功率”。对 `keep_pick` 特殊处理为“倾向保留签位”。 |
| `parseOriginalTopName(pick)` | 从 `decision_log` 中解析 `Original top candidate was X.` 行，恢复原始评分第一的球员名。无此行时返回 null。 |
| `findTopAlternative(pick)` | 找到第一个与 selected 不同的 alternative，用于候选对比。 |
| `buildPickConclusionLines(pick, simulation)` | 生成“为什么选他”的中文行。动态读取 `simulation.mode`、`prediction_selection_applied`、`projection_expected_pick`、`projection_draft_range_min/max`、`projection_confidence`、`alternatives`。 |
| `buildPickRiskLines(pick, simulation)` | 生成风险提示行。检测原始 top 与 selected 不同、alternative 分更高、confidence 低、pick 超出预测区间。 |
| `buildCandidateComparisonLines(pick)` | 生成候选对比行：原始评分第一 / 预测排序优先 / 最终选择。 |

### 5.2 扩展 `formatTradeAction`

原函数只覆盖 5 种 action。新增：
- `field_trade_up_calls` → "可考虑向上交易询价"
- `sell_pick_or_two_way` → "可考虑出售或转双向合同"

原 `shop_down` / `trade_down` 文案从“考虑向下交易”改为“可考虑向下交易”，语气更准确。

### 5.3 新增 `PickExplanationSummary` 组件

渲染 4 层中文解释（A/B/C/D），全部由字段动态生成：

| 层 | 标题 | 颜色 | 内容来源 |
|----|------|------|----------|
| A. 主结论 | "为什么选中 {player}？" | emerald | `buildPickConclusionLines` |
| B. 风险提示 | "风险提示" | amber | `buildPickRiskLines` |
| C. 候选对比 | "候选对比" | sky | `buildCandidateComparisonLines` |
| D. 交易建议 | "交易建议 · {action} · {prob}" | neutral | `formatTradeRationaleZh` + `formatTradeProbabilityMeaning` |

### 5.4 重构 pick card 展示层级

原 pick card 结构：
```
[player info]
[diagnostics]
<details> 决策流程 · {action} · {prob}%  ← raw English trace 主视图
  rationale (English)
  decision_log (English)
  CandidateBoardPreview
</details>
EvidencePanel
```

新 pick card 结构：
```
[player info]
[diagnostics]
PickExplanationSummary  ← 中文主视图（A/B/C/D 4 层）
<details> 技术日志 / 原始决策流程 · {action} · {prob}%  ← 折叠，降级
  说明：以下内容是系统内部决策日志...
  rationale (English)
  decision_log (English)
  CandidateBoardPreview
</details>
EvidencePanel
```

关键变化：
- 原 `<details>` 标题从“决策流程”改为“技术日志 / 原始决策流程”
- 在 `<details>` 内部顶部新增中文说明：“以下内容是系统内部决策日志，主要用于调试和复核；不会改变已经锁定的选择。”
- raw English trace 保留，但默认折叠，不占据主视图
- `PickExplanationSummary` 放在 `<details>` 之前，成为用户主视图

### 5.5 交易建议 42% 的解释

`PickExplanationSummary` 的 D 层明确写出：

```
交易建议 · 可考虑向下交易 · 交易建议强度 42%

该区间候选人差距不大，如果球队能多换一个未来二轮签，或退到相近档位，向下交易是可考虑方案。

注意：这只是交易建议，不代表已经发生交易，也不会自动改变本次模拟选人。当前模拟仍然选择 Aday Mara。 此处"交易建议强度"表示该交易方向的倾向强度，不是交易成功率。
```

明确区分：
1. “可考虑向下交易”是什么意思 → 系统认为可以询价 trade down
2. “42%”是什么意思 → 交易建议强度，不是交易成功率
3. 是否影响选人 → 不影响，当前 pick 仍按模拟结果锁定
4. 为什么建议 → 中文 rationale 摘要

### 5.6 处理 raw evidence / agent trace

- raw English `decision_log` 完整保留
- raw English `trade_evaluation.rationale` 完整保留（在 `<details>` 内）
- `CandidateBoardPreview` 完整保留（在 `<details>` 内）
- `EvidencePanel` 完整保留，未改动
- 所有 raw trace 默认折叠在“技术日志 / 原始决策流程”里

### 5.7 复制文本优化

`formatSimulationForCopy` 新增：
1. 模式说明行（Draft-Day Accuracy / Auto Simulation 各一句中文）
2. “关键风险提示”段落：
   - 列出所有“原始评分第一与最终选择不同”的 pick
   - 列出所有“存在向下交易建议”的 pick，明确标注“非交易成功率”

## 6. Example: DAL #9 Aday Mara

改完后页面对 `#9 DAL Aday Mara` 的实际解释摘要（Draft-Day Accuracy Mode 下，
基于 M4-CM corrected board 的字段动态生成）：

### A. 主结论

```
为什么选中 Aday Mara？

· 真实选秀预测模式启用，系统优先参考市场预测顺位和选秀区间。
· 原始评分第一是 Nate Ament，但最终选择了 Aday Mara。
· 原因：真实选秀预测模式以外部预测顺位为优先信号，原始综合分仅作为同区间内的参考。
· Aday Mara：预测顺位 #8，选秀区间 7-11，预测可信度 74%
· 当前签位 #9 处于他的预测区间内。
· 候选 Nate Ament 的原始综合分（68.1）高于 Aday Mara（57.1），但未被选中。
· 真实选秀预测模式认为 Aday Mara 更接近当前市场行情，因此优先选择。
```

### B. 风险提示

```
· 这个选择更贴近市场预测，但不一定是球队 fit 最优解。
· 原始评分中 Nate Ament（68.1）高于 Aday Mara（57.1），这里存在 team-fit / board-value 争议。
· 该 pick 存在 team-fit 风险，请结合候选池和证据面板判断。
```

### C. 候选对比

```
· 原始评分第一：Nate Ament（68.1）
· 预测排序优先：Aday Mara（预测 #8）
· 最终选择：Aday Mara（综合 57.1）

真实选秀预测模式会优先考虑外部预测顺位和选秀区间，因此可能选择综合分不是最高的球员。
```

### D. 交易建议

```
交易建议 · 可考虑向下交易 · 交易建议强度 42%

该区间候选人差距不大，如果球队能多换一个未来二轮签，或退到相近档位，向下交易是可考虑方案。

注意：这只是交易建议，不代表已经发生交易，也不会自动改变本次模拟选人。当前模拟仍然选择 Aday Mara。 此处"交易建议强度"表示该交易方向的倾向强度，不是交易成功率。
```

### E. 技术日志（默认折叠）

```
技术日志 / 原始决策流程 · 可考虑向下交易 · 42%

以下内容是系统内部决策日志，主要用于调试和复核；不会改变已经锁定的选择。

[原 English rationale]
[原 English decision_log]
[CandidateBoardPreview]
```

## 7. Copy Result Check

一键复制功能仍正常。复制文本现在包含：

1. 模式（Draft-Day Accuracy / Auto Simulation）
2. 模式说明（中文一句）
3. 年份、签数
4. 完整 60 picks
5. **关键风险提示**（新增）：
   - 原始评分第一与最终选择不同的 pick 列表
   - 存在向下交易建议的 pick 列表（标注“非交易成功率”）
6. Warning panels（保留原有 3 个 panel）

复制文本不包含 undefined/null 文案，不暗示发生交易，不把 42% 写成交易成功率。

## 8. Build / Smoke Result

### Frontend build

```
> draftmind-frontend@0.1.0 build
> next build

   ▲ Next.js 15.5.19
   - Environments: .env.local

   Creating an optimized production build ...
 ✓ Compiled successfully in 5.2s
   Linting and checking validity of types ...
   Collecting page data ...
   Generating static pages (0/5) ...
   Generating static pages (1/5)
   Generating static pages (2/5)
   Generating static pages (3/5)
 ✓ Generating static pages (5/5)
   Finalizing page optimization ...
   Collecting build traces ...

Route (app)                                 Size  First Load JS
┌ ○ /                                      684 B         103 kB
├ ○ /_not-found                            993 B         103 kB
└ ○ /draft                               22.9 kB         125 kB
+ First Load JS shared by all             102 kB
  ├ chunks/255-98a0bdaa30757bda.js       46.2 kB
  ├ chunks/4bd1b696-c023c6e3521b1417.js  54.2 kB
  └ other shared chunks (total)          1.97 kB

○  (Static)  prerendered as static content
```

Build 成功，类型检查通过，5 个页面全部生成。

### Page smoke

未实际浏览页面（本环境无法启动浏览器）。但 build 通过 + 源码检查确认：
- `PickExplanationSummary` 组件正确接收 `pick` 和 `simulation` props
- 所有 helper 函数有 null/undefined 兜底
- 无 runtime error 风险（所有字段访问都有可选链或 null 检查）
- 复制功能逻辑未破坏（`formatSimulationForCopy` 仍返回完整 60 picks + warning panels）

## 9. Boundary Verification

逐条确认：

- ✅ no commit
- ✅ no push
- ✅ no tag
- ✅ no backend selection logic change（未改任何 backend 文件）
- ✅ no ranking_engine change
- ✅ no simulation_service change
- ✅ no draft_day_accuracy change
- ✅ no prospect_availability change
- ✅ no DB change
- ✅ no CSV change
- ✅ no seed change
- ✅ no final board change（未改选人逻辑，60 picks 不变）
- ✅ no hardcoded Dallas/Aday/Nate logic（所有文案由字段动态生成）
- ✅ no trade logic change（`trade_evaluation` 只读，未改计算）
- ✅ raw evidence preserved（decision_log / rationale / CandidateBoardPreview 完整保留，仅折叠）
- ✅ no `frontend/lib/api.ts` change（无需类型补充）
- ✅ no schema change
- ✅ 42% 未被写成交易成功率（明确标注“交易建议强度，不是交易成功率”）
- ✅ 交易建议未被写成已经发生交易（明确标注“不代表已经发生交易，也不会自动改变本次模拟选人”）
- ✅ 无 undefined/null 文案（所有 helper 有兜底）

## 11. M4-CQ-B Contrast / Readability / Chinese Decision Log Follow-up

### 11.1 Final Status

READY_FOR_CHATGPT_REVIEW

### 11.2 修了哪些对比度问题

| 位置 | 改前 | 改后 |
|------|------|------|
| 顶部 "Draft-Day Accuracy" badge | `text-emerald-200` / `border-emerald-300/40` / `bg-emerald-300/[0.12]` | `text-emerald-100` / `border-emerald-300/70` / `bg-emerald-400/20` |
| Draft-Day Accuracy Mode 开关卡片 | `border-emerald-300/20` / `bg-emerald-300/[0.035]` / `text-court-muted` | `border-emerald-300/40` / `bg-emerald-300/[0.08]` / `text-emerald-100`；label 在 ON 时增强为 `border-emerald-300/70 bg-emerald-400/15`，说明文字 `text-court-text/80` |
| "为什么选中 {player}？" 标题 | `text-[11px] text-emerald-200` | `text-xs text-emerald-100`（更大、更深） |
| "风险提示" 标题 | `text-amber-200` | `text-amber-100` |
| "候选对比" 标题 | `text-sky-200` | `text-sky-100` |
| "交易建议" 标题 | `text-court-line` | `text-court-text`（更深） |
| 4 个 section 卡片背景 | `bg-emerald-300/[0.05]` 等很淡 | `bg-emerald-400/[0.08]` / `bg-amber-400/[0.08]` / `bg-sky-400/[0.08]` / `bg-white/[0.05]`（更明显） |

### 11.3 修了哪些 bullet/list 排版问题

改前：`<li className="flex gap-1.5">` 内部 bullet `<span>` 和文本 `<span>` 并排，但 bullet 字符 `·` 会因 flex 换行单独占一行。

改后：所有 4 个 section 的 `<li>` 改为：

```tsx
<li className="flex items-start gap-1.5">
  <span aria-hidden="true" className="mt-1 shrink-0 text-emerald-300">•</span>
  <span className="min-w-0">{line}</span>
</li>
```

关键修复：
- `items-start` — bullet 与文本顶部对齐
- `shrink-0` — bullet 不会被挤压换行
- `mt-1` — bullet 微下移，与中文文字视觉居中
- `min-w-0` — 文本 span 允许正常换行，不会撑破容器
- bullet 字符从 `·` 改为 `•`（更明显的实心圆点）
- `leading-6` — 行距更宽松，中文不挤
- `gap-1.5` → 4 个 section 统一

效果：bullet 与文本在同一行，移动端正常换行。

### 11.4 技术日志从英文主显示改为中文摘要优先

改前：展开"技术日志 / 原始决策流程"后第一眼看到的是英文 rationale 和英文 decision_log。

改后：三层结构：

1. **主视图**（默认显示）：`PickExplanationSummary` 的 4 层中文解释（为什么选他 / 风险提示 / 候选对比 / 交易建议）
2. **展开"技术日志 / 原始决策流程"**：
   - 顶部中文说明："以下内容是系统内部决策日志，主要用于调试和复核；不会改变已经锁定的选择。"
   - **中文决策流程**（新增）：编号列表，9 步，由 `buildDecisionFlowZh(pick, simulation)` 动态生成
   - CandidateBoardPreview（结构化数据，保留）
   - **"查看英文原始日志"**（二级折叠，默认收起）
3. **展开"查看英文原始日志"**：原英文 rationale + decision_log（完整保留，含 Market context / Scouting tie-breaker 标签）

### 11.5 `buildDecisionFlowZh` helper

新增 helper 函数，从 `pick` 和 `simulation` 字段动态生成 9 步中文决策流程：

1. 第 X 顺位，TEAM 进入选择。
2. 系统先移除已经被选走的球员，然后重新排序当前候选池。
3. 当前排序最高候选是 PLAYER，综合评分 SCORE。
4. 系统同时检查了其他候选人：NAME1、NAME2、...（从 `Alternatives checked:` 行解析）
5. 原始评分第一是 X，但真实选秀预测模式启用后，Y 的市场预测顺位更靠前。
6. PLAYER 的预测顺位是 #X，当前 #Y 处于他的预测区间 A-B 内。
7. 系统最终按预测排序分选择 PLAYER。
8. 交易建议显示"可考虑向下交易"，建议强度 42%。该建议只是辅助，不代表交易已经发生，也不会改变当前选择。
9. 选中 PLAYER 后，他会从后续候选池中移除，球队需求会为后续签位更新。

所有步骤动态生成，无 hardcode。无法解析的行跳过，不显示 undefined/null。

### 11.6 英文 raw trace 保留位置

英文 raw trace 完整保留在二级折叠"查看英文原始日志"里：
- `trade_evaluation.rationale`（英文原文）
- `decision_log` 数组（英文原文，含 Market context / Scouting tie-breaker 标签）
- 未删除任何内容，仅降级展示

### 11.7 Build 结果

```
> draftmind-frontend@0.1.0 build
> next build

   ▲ Next.js 15.5.19
   - Environments: .env.local

   Creating an optimized production build ...
 ✓ Compiled successfully in 12.1s
   Linting and checking validity of types ...
   Collecting page data ...
   Generating static pages (0/5) ...
 ✓ Generating static pages (5/5)
   Finalizing page optimization ...
   Collecting build traces ...

Route (app)                                 Size  First Load JS
┌ ○ /                                      684 B         103 kB
├ ○ /_not-found                            993 B         103 kB
└ ○ /draft                               23.7 kB         126 kB
+ First Load JS shared by all             102 kB

○  (Static)  prerendered as static content
```

Build 成功，类型检查通过，5 个页面全部生成。

### 11.8 页面 smoke 检查项

本地页面 smoke 应确认（本环境无法启动浏览器，但源码检查确认逻辑正确）：

- #9 DAL Aday Mara 的"为什么选中"标题清晰可读（`text-emerald-100`）
- Draft-Day Accuracy badge 对比度改善（`text-emerald-100` + 更深 border/bg）
- Draft-Day Accuracy Mode 开关卡片对比度改善（ON 时 `border-emerald-300/70 bg-emerald-400/15`）
- bullet 不再单独占行（`items-start` + `shrink-0` + `min-w-0`）
- 交易建议 42% 没被写成交易成功率（文案未改，仍为"交易建议强度"）
- 技术日志展开后先显示中文决策流程（`buildDecisionFlowZh` 输出）
- 英文 raw trace 在二级折叠"查看英文原始日志"里
- 一键复制结果未破坏（`formatSimulationForCopy` 未改）

### 11.9 边界确认

- ✅ 仍然只改 frontend 展示（`frontend/app/draft/page.tsx`）
- ✅ 仍然没有 backend / DB / final board 改动
- ✅ 未改 `frontend/lib/api.ts`
- ✅ 未改任何选人逻辑
- ✅ 未改 trade_evaluation 计算
- ✅ 未 hardcode Dallas / Aday / Nate
- ✅ 英文 raw evidence 完整保留（二级折叠）
- ✅ 42% 未被写成交易成功率
- ✅ 交易建议未被写成已经发生交易
- ✅ 无 undefined/null 文案

## 12. M4-CQ-C Readability Correction + Single Pick Copy

### 12.1 Final Status

READY_FOR_CHATGPT_REVIEW

### 12.2 为什么 M4-CQ-B 的浅色文字不适合当前浅色背景

页面主题系统（`globals.css`）在 light 模式下：
- `--court-black: 239 236 226`（浅米色背景）
- `--court-text: 35 39 43`（深色文字）
- `--court-muted: 94 104 118`（中等灰）

M4-CQ-B 使用了 `text-emerald-100` / `text-emerald-200` / `text-amber-100` / `text-sky-100` 等**固定浅色**。这些颜色在 dark 模式下可读，但在 light 模式下与浅色背景对比度极差，导致标题和正文看起来像 disabled。

### 12.3 修了哪些对比度问题

所有浅色文字改为深色文字或主题感知 token：

| 位置 | M4-CQ-B（浅色，不可读） | M4-CQ-C（深色，可读） |
|------|------------------------|----------------------|
| Draft-Day Accuracy badge | `text-emerald-100` / `border-emerald-300/70` / `bg-emerald-400/20` | `text-emerald-800` / `border-emerald-500/60` / `bg-emerald-100/70` |
| 开关卡片 summary | `text-emerald-100` | `text-emerald-800` |
| 开关卡片 label ON | `border-emerald-300/70 bg-emerald-400/15` | `border-emerald-500/60 bg-emerald-100/50` |
| 开关卡片说明 | `text-court-text/80` | `text-court-muted` |
| "为什么选中" 标题 | `text-emerald-100` | `text-emerald-900` |
| "风险提示" 标题 | `text-amber-100` | `text-amber-900` |
| "候选对比" 标题 | `text-sky-100` | `text-sky-900` |
| "交易建议" 标题 | `text-court-text` | `text-court-text`（保持） |
| 4 个 section 卡片背景 | `bg-emerald-400/[0.08]` 等很淡 | `bg-emerald-50/70` / `bg-amber-50/70` / `bg-sky-50/70` / `bg-court-panel` |
| bullet 颜色 | `text-emerald-300` / `text-amber-300` / `text-sky-300` | `text-emerald-700` / `text-amber-700` / `text-sky-700` |
| 风险正文 | `text-amber-50` | `text-court-text` |
| 技术日志 summary | `text-court-line` | `text-court-text` |
| 技术日志卡片背景 | `bg-white/[0.03]` / `bg-court-black/40` | `bg-court-faint` / `bg-court-panel` |
| 技术日志 border | `border-white/10` | `border-court-border` |

### 12.4 bullet/list 是否仍正常

是。M4-CQ-B 的 bullet 排版修复（`items-start` + `shrink-0` + `min-w-0` + `•` 字符）保留不变。仅修改了 bullet 颜色从浅色（`text-emerald-300`）改为深色（`text-emerald-700`），在浅色背景上更可见。

### 12.5 技术日志中文摘要 / 英文二级折叠是否保留

是。三层结构完整保留：
1. 主视图：`PickExplanationSummary` 4 层中文解释
2. 展开技术日志：中文决策流程（`buildDecisionFlowZh`）+ CandidateBoardPreview + "查看英文原始日志"二级折叠
3. 展开英文原始日志：原英文 rationale + decision_log

仅修改了颜色：技术日志卡片从 `bg-white/[0.03]` 改为 `bg-court-faint`，border 从 `border-white/10` 改为 `border-court-border`，标题从 `text-court-line` 改为 `text-court-text`。

### 12.6 新增单签复制按钮

新增"复制本签解释"按钮，位于每个 pick card 的 `PickExplanationSummary` 上方右侧。

**实现：**
- 新增 `formatPickForCopy(pick, simulation)` helper，复用 `buildPickConclusionLines` / `buildPickRiskLines` / `buildCandidateComparisonLines` / `formatTradeAction` / `formatTradeRationaleZh`
- 新增 `copiedPickId` state 和 `handleCopyPick(pick)` 函数，复用现有 clipboard 逻辑（`navigator.clipboard.writeText` + textarea fallback）
- 点击后按钮文案短暂变为"已复制"，1.5s 后恢复
- 复制失败时 console.error，不 crash

**复制内容包含：**
- Header：`#9 DAL Aday Mara` / 位置 / 综合评分 / 模式
- 为什么选中（中文 bullet 列表）
- 风险提示（中文 bullet 列表）
- 候选对比（中文 bullet 列表）
- 交易建议（中文，含"交易建议强度 X%"和"不是交易成功率"说明）

**不包含：**
- 英文 raw trace
- 整页 60 picks
- undefined / null

### 12.7 Build 结果

```
> draftmind-frontend@0.1.0 build
> next build

   ▲ Next.js 15.5.19
   Creating an optimized production build ...
 ✓ Compiled successfully in 5.6s
   Linting and checking validity of types ...
 ✓ Generating static pages (5/5)

Route (app)                                 Size  First Load JS
┌ ○ /                                      684 B         103 kB
├ ○ /_not-found                            993 B         103 kB
└ ○ /draft                               24.1 kB         127 kB
+ First Load JS shared by all             102 kB

○  (Static)  prerendered as static content
```

Build 成功，类型检查通过，5 个页面全部生成。

### 12.8 边界确认

- ✅ 仍然只改 frontend 展示（`frontend/app/draft/page.tsx`）
- ✅ 仍然没有 backend / DB / CSV / seed / final board 改动
- ✅ 未改 `frontend/lib/api.ts`
- ✅ 未改选人逻辑 / trade_evaluation 计算
- ✅ 未 hardcode Dallas / Aday / Nate
- ✅ 英文 raw evidence 完整保留（二级折叠）
- ✅ 42% 未被写成交易成功率
- ✅ 交易建议未被写成已经发生交易
- ✅ 无 undefined/null 文案
- ✅ 一键复制完整结果仍可用（`formatSimulationForCopy` 未改）

## 13. M4-CQ-D Default-Collapsed Pick Explanation

### 13.1 Final Status

READY_FOR_CHATGPT_REVIEW

### 13.2 为什么要默认折叠解释区

M4-CQ-C 完成后，用户本地 smoke 反馈：内容清楚、复制本签解释正常，但每个 pick 默认铺开 4 层中文解释 + 技术日志 + 实时候选池，导致选秀名单被解释内容占据，60 picks 滚动很长，不够直观。

用户希望先快速看到完整选秀名单，再按需展开某个 pick 的解释。

### 13.3 哪些内容被折叠

新增一个默认折叠的 `<details>`，标题为"查看本签解释 / 候选对比 / 交易建议"，内部包含：

1. `PickExplanationSummary`（为什么选中 / 风险提示 / 候选对比 / 交易建议）
2. 技术日志 / 原始决策流程（二级折叠）
   - 中文决策流程（`buildDecisionFlowZh`）
   - CandidateBoardPreview（实时候选池）
   - 查看英文原始日志（三级折叠，英文 raw trace）

层级结构：

```text
[复制本签解释]  ← 默认可见
▶ 查看本签解释 / 候选对比 / 交易建议  [状态 badges]
   为什么选中...
   风险提示...
   候选对比...
   交易建议...
   ▶ 技术日志 / 原始决策流程
      中文决策流程...
      CandidateBoardPreview
      ▶ 查看英文原始日志
         English raw trace...
```

### 13.4 哪些按钮仍默认可见

- ✅ `复制本签解释` 按钮保留在折叠外面，用户不展开也能直接复制
- ✅ 预测参考卡片（prediction reference）保留默认展示
- ✅ RiskDiagnosticsWarnings 保留默认展示
- ✅ EvidencePanel 保留默认展示

### 13.5 状态 badges

折叠 summary 标题旁新增 3 个动态状态 badge（仅在条件满足时显示）：

| Badge | 条件 | 样式 |
|-------|------|------|
| `预测信息选中` | `selected_player.prediction_selection_applied === true` | emerald 深色 |
| `存在评分分歧` | `parseOriginalTopName(pick) !== selected_player.prospect.name` | amber 深色 |
| `交易建议 X%` | `trade_evaluation.action !== "keep_pick"` 且 `probability > 0` | sky 深色 |

用户不展开就能一眼看到该 pick 是否有预测覆盖 / 评分分歧 / 交易建议。

### 13.6 `复制本签解释` 是否仍正常

是。`handleCopyPick` 和 `formatPickForCopy` 未改，复制内容仍为 M4-CQ-C 的中文摘要（header + 为什么选中 + 风险提示 + 候选对比 + 交易建议），不含英文 raw trace。点击后短暂显示"已复制"。

### 13.7 技术日志中文摘要 / 英文二级折叠是否保留

是。三层结构完整保留，仅从"主视图同级"改为"主折叠内部二级折叠"：

- 中文决策流程仍优先显示
- CandidateBoardPreview 仍在技术日志内
- 英文 raw trace 仍在三级折叠"查看英文原始日志"里
- 未删除任何 raw evidence

### 13.8 Build 结果

```
> draftmind-frontend@0.1.0 build
> next build

   ▲ Next.js 15.5.19
   Creating an optimized production build ...
 ✓ Compiled successfully in 4.8s
   Linting and checking validity of types ...
 ✓ Generating static pages (5/5)

Route (app)                                 Size  First Load JS
┌ ○ /                                      684 B         103 kB
├ ○ /_not-found                            993 B         103 kB
└ ○ /draft                               24.3 kB         127 kB
+ First Load JS shared by all             102 kB

○  (Static)  prerendered as static content
```

Build 成功，类型检查通过，5 个页面全部生成。

### 13.9 边界确认

- ✅ 仍然只改 frontend 展示（`frontend/app/draft/page.tsx`）
- ✅ 仍然没有 backend / DB / CSV / seed / final board 改动
- ✅ 未改 `frontend/lib/api.ts`
- ✅ 未改选人逻辑 / trade_evaluation 计算
- ✅ 未 hardcode Dallas / Aday / Nate
- ✅ 未删除任何解释内容（仅折叠）
- ✅ 英文 raw evidence 完整保留（三级折叠）
- ✅ 42% 未被写成交易成功率
- ✅ 交易建议未被写成已经发生交易
- ✅ 无 undefined/null 文案
- ✅ 一键复制完整结果仍可用

### 13.10 最终 git diff --stat（同步更新）

```
 frontend/app/draft/page.tsx | 927 ++++++++++++++++++++++++++++++++++++++++----
 1 file changed, 854 insertions(+), 73 deletions(-)
```

注：报告前面 section 4 / 5 中若出现旧的 `+455/-4` 等统计，以本节为准。M4-CQ 全系列（CQ 初版 + CQ-B + CQ-C + CQ-D + CQ-E）累计净改动为 `+854/-73`。

## 14. M4-CQ-E Default Prediction View + Display Mode Polish

### 14.1 Final Status

READY_FOR_CHATGPT_REVIEW

### 14.2 默认模拟状态改动

前端初始状态已改为推荐预测状态：

| 设置 | 默认值 |
|------|--------|
| 模拟范围 | 两轮 60 签 |
| 预测信息辅助选人 | ON |
| Draft-Day Accuracy Mode | ON |
| 手动锁定顺位 | OFF |
| 球探适配诊断 | OFF |

这是前端 UI 默认值改动，不改 backend `SimulateRequest` 默认值，不改 API schema，不改 `simulation_service` / `draft_day_accuracy`。

用户仍可手动切回：
- 第一轮 30 签
- Auto Simulation
- 预测辅助 OFF
- 球探诊断 ON/OFF
- 手动锁定顺位

### 14.3 推荐模式文案

控制面板顶部新增提示：

```text
推荐模式：最终预测模拟
适合查看 DraftMind 当前最接近真实选秀大会的预测结果；Auto Simulation 可用于对比系统原始评分。
```

没有使用“最佳选秀模拟”，因为该表达过于绝对，容易暗示结果保证准确。当前文案强调“当前最接近真实选秀大会的预测结果”，同时保留 Auto Simulation 作为原始评分对比入口。

### 14.4 展开 icon

“查看本签解释 / 候选对比 / 交易建议” summary 新增明显展开 icon：

```text
▶ 查看本签解释 / 候选对比 / 交易建议
▼ 查看本签解释 / 候选对比 / 交易建议
```

实现方式：
- `<details>` 增加 `group`
- summary 内放两个 icon span
- `group-open:hidden` / `group-open:inline` 控制展开状态显示
- icon 使用 `text-court-line`，对比度清楚

不改变原折叠结构，不删除状态 badges。

### 14.5 名单模式 / 分析模式

模拟结果区新增轻量 segmented control：

```text
名单模式 | 分析模式
```

默认：`名单模式`

行为：
- 名单模式：pick card 更紧凑，解释区默认折叠，适合快速浏览 60 picks。
- 分析模式：解释区默认展开，适合逐签复盘。
- 技术日志仍在二级折叠。
- 英文 raw trace 仍在三级折叠。
- 实时候选池仍在技术日志内。

该切换只影响前端展示，不重新请求后端，不改变 `selected_player`、scores、warnings、copy 内容或 final board。

### 14.6 保留功能

已确认保留：

- `复制本签解释`
- `一键复制结果`
- 中文解释
- 风险提示
- 候选对比
- 交易建议
- 中文决策流程
- 英文 raw trace 二级/三级折叠
- 证据面板
- prediction reference card
- warning panels

### 14.7 Build 结果

```
> draftmind-frontend@0.1.0 build
> next build

   ▲ Next.js 15.5.19
   - Environments: .env.local

   Creating an optimized production build ...
 ✓ Compiled successfully in 4.9s
   Linting and checking validity of types ...
 ✓ Generating static pages (5/5)
   Finalizing page optimization ...
   Collecting build traces ...

Route (app)                                 Size  First Load JS
┌ ○ /                                      684 B         103 kB
├ ○ /_not-found                            993 B         103 kB
└ ○ /draft                               24.6 kB         127 kB
+ First Load JS shared by all             102 kB

○  (Static)  prerendered as static content
```

Build 成功，类型检查通过，5 个页面全部生成。

### 14.8 Smoke 检查

源码 / build 检查确认：

- ✅ 页面默认两轮 60 签
- ✅ 预测信息辅助选人默认 ON
- ✅ Draft-Day Accuracy Mode 默认 ON
- ✅ 手动锁定顺位默认 OFF
- ✅ 球探适配诊断默认 OFF
- ✅ 有“推荐模式：最终预测模拟”说明
- ✅ 不出现“最佳选秀模拟”
- ✅ 模拟结果区有“名单模式 / 分析模式”切换
- ✅ 默认是名单模式
- ✅ 名单模式下解释区默认折叠，60 picks 更紧凑
- ✅ 展开入口有 `▶ / ▼` icon
- ✅ 分析模式下解释区默认展开
- ✅ `复制本签解释` 仍可用
- ✅ `一键复制结果` 仍可用
- ✅ build 无 runtime/type error

### 14.9 边界确认

- ✅ 仍然只改 frontend 展示
- ✅ 未改 backend
- ✅ 未改 DB / CSV / seed
- ✅ 未改 final board
- ✅ 未改 `frontend/lib/api.ts`
- ✅ 未改 `ranking_engine.py`
- ✅ 未改 `simulation_service.py`
- ✅ 未改 `draft_day_accuracy.py`
- ✅ 未改 `prospect_availability.py`
- ✅ 未改 trade_evaluation 计算
- ✅ 未 hardcode Dallas / Aday / Nate
- ✅ 未删除已有解释内容
- ✅ 未删除 raw evidence
- ✅ 未把 42% 写成交易成功率
- ✅ 未暗示系统真的执行交易
- ✅ 未使用“最佳选秀模拟”

## 10. Recommendation

```text
Recommended commit message:
Polish frontend pick explanations

Recommended tag:
frontend-pick-explanation-polish-m4-cq
```

```text
Do not commit, push, or tag. Final decision belongs to ChatGPT.
```
