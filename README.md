# DraftMind

> NBA draft decision agent — simulate a general manager's draft board with a deterministic, explainable scoring engine.

DraftMind 不会让 LLM 替你做选秀决定。先用 `ranking_engine` 把候选新秀按 **talent / fit / pick value / risk** 打分并排序；只有排序结果出来之后，LLM 才把结构化结果翻译成 GM 视角的叙事。

```text
status : v4 stable (news-aware)
license: MIT planned
stack : FastAPI + Next.js + SQLite
LLM   : mock-first, hunyuan (腾讯混元) optional
tags  : simulate-v1-dynamic-needs · simulate-v2-locked-picks
        · simulate-v3-frontend-locked-picks
        · news-v1-rumor-extractor
        · news-v2-simulation-market-context
```

---

## Current final status

DraftMind 当前 public version 是 2026 NBA Draft 的 final pre-draft prediction build。最终预测入口是 [`/draft`](http://127.0.0.1:3000/draft)，前端默认打开：

- 两轮 60-pick 模拟
- Draft-Day Accuracy Mode
- 预测信息辅助选人
- 名单模式，分析模式可展开逐签解释

Draft-Day Accuracy Mode 不等于新闻自动选人，也不等于 LLM 选人。它是在 DraftMind 自身模拟系统上，引入结构化市场 projection 数据进行排序优先级调整；`ranking_engine` / `simulation_service` / `draft_day_accuracy` 仍然是选人路径。LLM 只负责解释，News/RAG 只作为 read-only context，不直接决定 `selected_player`。

最终成果文档见：[docs/final-project-result-2026.md](docs/final-project-result-2026.md)。

---

## 1. 一句话介绍

DraftMind 是一个 NBA 选秀决策智能体，按 **球队需求 + 可解释评分 + 动态顺位推演 + 用户锁签覆盖** 模拟完整 GM 决策流程，LLM 只在解释层介入。

---

## 2. 核心功能

- **Single-pick recommend** — `POST /api/recommend` 给出球队 + 顺位 → 返回推荐球员、评分拆解、风险提示和备选。
- **Full-board simulate** — `POST /api/simulate` 按 `rounds=1/2` 模拟完整选秀，已选球员自动从后续候选池移除。
- **Dynamic team needs** — 同一支球队后续顺位会受前面已选球员影响（position / skill 需求自动调整）。
- **User-override / locked picks** — 用户可在 `locked_picks` 数组里 pin 某个顺位必须选某个球员，后端继续从后续顺位模拟。
- **Trade market signals** — 每个顺位附带 `trade_evaluation`（`keep_pick` / `field_trade_up_calls` / `shop_down` / `sell_pick_or_two_way`），**不执行真实交易**。
- **Explainable scoring** — 每个 prospect 返回 5 项分数 (`talent / fit / pick_value / risk_penalty / final`) + `reasons[]` + `risks[]`，全部由 `ranking_engine` 算。
- **GM-language explanation** — `POST /api/agent/ask` 让 LLM 把结构化结果翻译成 GM 视角叙事；无 API key 时降级到 mock。
- **Local caching** — NBA.com 球队阵容 / 选秀权 / 新秀数据本地 SQLite 缓存，演示时抗网络波动。
- **Structured draft rumor extraction** — `rumor_extractor` 从本地缓存
  的 `NewsArticle` 中提取 `NewsSignal`（team / prospect / pick / intent /
  confidence），纯函数、可单测、不依赖 LLM。
- **Market context in decision log** — `POST /api/simulate` 在 `decision_log[]`
  末尾按需追加 `Market context: …` 行，最多 3 条/pick；**只用于阅读上下文**，
  不改 `selected_player` / `final_score` / `trade_evaluation` / 响应 schema。

---

## 3. 比赛展示亮点

| 亮点 | 实现依据 |
|------|----------|
| **LLM 不参与底层选人** | 排序由 `app/services/ranking_engine.py` 纯函数算出；`ranking_engine` 在 `tests/test_ranking_engine.py` 与 `tests/test_simulation_service.py` 中被覆盖。 |
| **ranking_engine 可解释** | 公式公开 `final = talent*0.40 + fit*0.30 + pick_value*0.20 - risk*0.10`；每个 prospect 附带 5 项分数 + 短句 reasons/risks。 |
| **动态 team_need_state** | 同队第二次签位时，position 与 skill 需求已根据前面已选球员下调；`TeamNeedSnapshot` dataclass 隔离 DB session，**不污染 SQLite**。 |
| **locked picks 沙盘推演** | 用户在 UI 锁定任意顺位 → 后端继续从后续顺位模拟；`decision_log` 包含 `"This pick was locked by user override."`；前端展示 `手动锁定` 徽章。 |
| **GM 视角而非 auto-draft** | `decision_log[]` 逐条说明每签的"GM 思路"，不是单纯的得分排名。 |
| **News 只作为只读上下文** | `rumor_extractor.extract_signals()` 从 cached `NewsArticle` 抽 `NewsSignal`；`simulation_service._market_context_lines_for_pick()` 按 `team_abbr / pick_no / prospect_name` 过滤后追加到 `decision_log[]`（最多 3 条）。`ranking_engine` / `final_score` / `selected_player` / `trade_evaluation.action / probability` **全部不受影响**。 |

---

## 4. 技术架构

```text
                ┌────────────────────────────┐
                │  Frontend (Next.js + TS)   │
                │  /         /draft          │
                │  locked-picks editor       │
                └────────────┬───────────────┘
                             │  fetch /api/...
                ┌────────────▼───────────────┐
                │  FastAPI routers           │
                │  /recommend /simulate      │
                │  /teams /prospects         │
                │  /agent /news              │
                └────────────┬───────────────┘
                             │
        ┌────────────────────┴────────────────────┐
        │                                         │
        ▼                                         ▼
┌──────────────────┐                  ┌──────────────────────┐
│ ranking_engine   │  ←── deterministic │ team_need_service    │
│  talent * 0.40   │      pure function │  get_or_infer_need   │
│  fit    * 0.30   │      (unit tested)│  adjust_after_pick   │
│  pv     * 0.20   │                   └──────────────────────┘
│  risk   * 0.10   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐    optional    ┌──────────────────────┐
│ simulation_service│   LLM layer   │ llm_service          │
│ simulate_draft() │ ─────────────► │ mock (default)       │
│  + locked_picks  │  post-rank     │ hunyuan (optional)   │
│  + dynamic needs │  explanation   │ is_mock exposed      │
└──────────────────┘                └──────────────────────┘
```

**关键原则**：
- LLM **不在底层选人路径上**。`simulate_draft` 主循环只调用 `rank_prospects` + `adjust_team_need_after_pick`；LLM 只在 `/api/agent/ask` 或用户显式调用时介入。
- `ranking_engine` 是带单测的纯函数；`team_need_state` 是内存快照，**不写回 DB**。
- 交易评估只产出市场信号，**不交换顺位**，`TradeEvaluation.executed` 永远为 `False`。

---

## 5. 快速开始

### 5.1 一键启动（推荐 · Windows）

```powershell
cd D:\DraftMind
.\start_all.ps1
```

脚本会：
- 清理已占用的 8000 / 3000 端口
- 检查并安装 backend / frontend 依赖
- 启动 FastAPI (8000) 和 Next.js (3000)
- 等待 20s 并打印 health check 结果

打开 [http://127.0.0.1:3000/draft](http://127.0.0.1:3000/draft) 即可。

如果只用 cmd.exe：

```bat
cd /d D:\DraftMind
start_all.bat
```

### 5.2 手动分步启动

```bash
# 1) 后端
cd backend
pip install -e .
python scripts/seed_db.py
uvicorn app.main:app --reload

# 2) 前端
cd ../frontend
npm install
npm run dev
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

---

## 6. 演示流程

### 6.1 普通完整模拟（约 60 秒）

1. 浏览器打开 [http://127.0.0.1:3000/draft](http://127.0.0.1:3000/draft)。
2. 球队下拉选 `SAS · San Antonio Spurs`。
3. 签位保持默认（或输入一个 `1-60` 的值）。
4. 点 `生成推荐` → 看主推荐卡片（final score + 5 项 score bar + reasons + risks + alternatives）。
5. 在 `Agent 追问` 区问 `为什么不选第一个备选球员？` → 看 LLM 的 GM 视角解释。
6. 在 sidebar 底部 `Full board` 卡片点 `模拟完整顺位` → 浏览器底部出现 `完整顺位模拟` 列表。
7. **关键点**：「没有 LLM 编造」+「已选球员不出现在后续候选池」+「同队第二次签位 fit_score 受前面已选球员影响」。

### 6.2 locked picks 演示（约 90 秒）

接着 6.1：

1. 在 sidebar 底部 `手动锁定 picks` 区点 `+ 添加锁定`。
2. 添加两行，例如：
   - 行 1：`#5` + 下拉选一个 prospect
   - 行 2：`#10` + 下拉选另一个 prospect
3. 点 `模拟完整顺位`。
4. 完整顺位卡片中，被锁定的 `#{pick_no}` 右侧出现琥珀色 `手动锁定` 徽章。
5. 展开 `Agent process` 详情 → `decision_log` 包含 `This pick was locked by user override.`。
6. **关键点**：「系统不是在每个顺位独立排序，而是在做连续 GM 决策」。

### 6.3 查看「手动锁定」结果

- 锁定 pick 后，完整顺位模拟的对应卡片右上出现琥珀色 `手动锁定` 徽章。
- 展开 `Agent process` 详情，**`decision_log`** 中插入 `This pick was locked by user override.` 这一行。
- `candidate_board` 仍展示前 5 名供对比，前端可以一眼看到「如果我没锁这个签，自动引擎本来会选谁」。

### 6.4 GM 沙盘推演

locked picks 的本质是 **GM 视角的"如果……会怎样"** 工具：

- 如果我把某高顺位 prospect 锁到 pick #2，会如何影响后续 draft board？
- 如果 SAS 选了 PG，同队第二次选秀的 fit_score 真的会变吗？
- 哪些球队后续会拿到 trade-up 信号？

通过对比"带 locked_picks 的 simulate 结果"和"原始 simulate 结果"，能直观看到 GM 决策的链式影响。

### 6.5 Market context 演示（约 30 秒）

接 §6.2 / §6.4：

1. 在完整顺位模拟列表中，**展开任一 pick 卡片的 `Agent process` 详情**。
2. 在 `decision_log` 末尾可能看到一行 `Market context: <TEAM> has a recent
   <trade-up / workout / draft preference> signal around pick #N
   (confidence NN%).`。
3. **关键点**：
   - 行文是**观察式**（"has a recent signal"），不是处方式
     （"System recommends trading up"）。
   - 只有**该球队 / 该 pick / 该 prospect** 命中的 cached news signal
     才会出现；`LAL` 的 rumor 不会出现在 `SAS` 的 pick 上。
   - 同一 pick 最多 **3 条** market context 行。
   - `selected_player` / `trade_evaluation` 字段都没变——这只是只读
     上下文。
4. 当 `decision_log` 末尾没有 `Market context: …` 时，说明当前 pick
   没命中任何 cached news signal——**这是正常行为**，不是 bug。

---

## 7. API 说明

### 7.1 `POST /api/recommend`

推荐单签 GM 决策。

**Request body**

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `year` | int | ✅ | 2026 | 选秀年份 |
| `team_id` | int | ✅ | — | 球队 id |
| `pick` | int | ✅ | — | 1-60 顺位 |
| `mode` | str | ❌ | `gm_decision` | 评分模式 |

**Response**

```json
{
  "year": 2026,
  "pick": 8,
  "mode": "gm_decision",
  "team": { "id": 1, "abbr": "SAS", "name": "San Antonio Spurs", "...": "..." },
  "recommended_player": { "prospect": {...}, "scores": {...}, "reasons": [...], "risks": [...] },
  "alternatives": [...]
}
```

### 7.2 `POST /api/simulate`

模拟完整选秀。

**Request body**

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `year` | int | ✅ | 2026 | |
| `rounds` | int | ❌ | 1 | `1` → 最多 30 顺位；`2` → 最多 60 顺位 |
| `limit` | int | ❌ | 60 | 用户上限 |
| `evaluate_trades` | bool | ❌ | true | 是否计算 trade market signal |
| `locked_picks` | array | ❌ | null | 用户覆盖（见 7.3） |

**`rounds` vs `limit`**

```python
effective_limit = min(limit, 30 if rounds == 1 else 60)
```

然后数据库查询 `DraftOrder` 时使用 `effective_limit`。`SimulateResponse.total_picks` 等于实际模拟出的 picks 数；如果数据库里没有足够顺位，按实际数量返回，不报错。

**Response**

```json
{
  "year": 2026,
  "rounds": 1,
  "total_picks": 4,
  "source": "Draft order source unavailable",
  "picks": [
    {
      "pick": 2,
      "team": { "...": "..." },
      "original_team": "...",
      "draft_order_note": "...",
      "selected_player": { "prospect": {...}, "scores": {...}, "reasons": [...], "risks": [...] },
      "alternatives": [...],
      "candidate_board": [...],
      "trade_evaluation": { "action": "keep_pick", "probability": 0.0, "rationale": "...", "executed": false },
      "decision_log": ["...", "...", "..."]
    }
  ]
}
```

> `decision_log[]` 末尾可能追加 0–3 行 `Market context: …`（仅在该 pick 的
> `team_abbr` / `pick_no` / `selected prospect` 命中 cached news 时出现）。
> 这是**纯文本上下文**，不会改变 `selected_player` / `final_score` /
> `trade_evaluation` 任何一个字段。**Response 顶层 shape 没变**——只是
> `decision_log` 数组多几行字符串。详见 §7.4。

### 7.3 `locked_picks` 字段

| 子字段 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `pick_no` | int | ✅ | 1-60 |
| `prospect_id` | int? | 二选一 | 主键查询，**必须同年** |
| `prospect_name` | str? | 二选一 | 大小写不敏感精确匹配 |

**Behavior**

- 该顺位不采用自动 top1 作为最终选择，而是直接选择用户指定 prospect。
- 系统仍会对 live board 调用 `rank_prospects`，并生成 `alternatives` 与 `candidate_board`，用于展示「如果不手动锁定，自动引擎本来会怎样排序」。
- `decision_log` 包含 `This pick was locked by user override.`。
- 后端 `adjust_team_need_after_pick` 仍被调用 → 同队后续顺位用更新后的需求。
- 同一 prospect 不能被锁两次；同一 `pick_no` 不能重复。

**错误码（统一 HTTP 400）**

| 触发 | message |
|------|---------|
| `prospect_id` / `prospect_name` 都不提供 | `pick_no=X: prospect_id or prospect_name required` |
| `pick_no` 不在当前 draft order | `pick_no=X not in draft order` |
| `pick_no` 重复 | `Duplicate locked pick_no=X` |
| 同一 prospect 已被锁到另一 pick | `Prospect X is already locked by another pick` |
| `prospect_id` 找不到或 year 不匹配 | `Prospect not found (id=X) for pick_no=Y` |
| `prospect_name` 找不到 | `Prospect not found (name=X) for pick_no=Y` |
| `prospect_name` 匹配多个 | `prospect_name=X is ambiguous (matches N rows)` |

### 7.4 News & Market Context

DraftMind 把新闻 / 流言视为**只读上下文**，不进入底层决策路径。`/api/simulate`
的 `decision_log[]` 末尾可能出现的 `Market context: …` 行，纯粹是给 GM 阅读
时的「近期市场情绪」参考。

**数据流（Phase 5B-M1）**

```text
NewsArticle (cached, DB)
   │
   ▼
rumor_extractor.extract_signals()       # 纯函数
   │
   ▼
NewsSignal[]  (team_abbr / pick_no / prospect_name / intent / confidence)
   │
   ▼
simulation_service._load_market_signals(db)
   │  (read-only, 不调用 fetch_recent_articles, 不联网)
   ▼
simulation_service._market_context_lines_for_pick(
   team_abbr, pick_no, selected_prospect_name, limit=3
)
   │  过滤规则（保守, 避免跨队 leak）:
   │    1) 优先按 signal.team_abbr 匹配当前 pick 的 team_abbr;
   │       带有明确 team_abbr 的 signal 永远不会显示到其他球队的 pick 上。
   │    2) 只有 signal 没有明确 team_abbr 时, 才允许通过
   │       signal.pick_no == pick_no 或 signal.prospect_name 命中
   │       selected prospect 来辅助匹配。
   ▼
build_decision_log(..., market_context_lines=...) → decision_log[] 追加
```

**Guarantees（不变量）**

- `selected_player` 永远由 `ranking_engine` 决定。
- `final_score` 永远由 `ranking_engine` 公式决定。
- `trade_evaluation.action` / `probability` 永远由 `evaluate_trade_market` 决定。
- `/api/simulate` 不会在 simulate 期间调用 `fetch_recent_articles` 或任何网络 IO。
- `/api/simulate` Response schema 完全没变——多出来的仅是 `decision_log[]` 中的纯文本行。
- 不会触发真实交易；`trade_evaluation.executed` 始终为 `false`。
- 前端无需任何改动即可继续渲染（已有 `decision_log` 详情会自然多展示几行）。
- `LLM` may be used for explanation, but it never decides `selected_player`.
  In simulation, market context is generated by deterministic extraction and
  appended to `decision_log`, not used as an LLM decision input.

> **Market context is observational, not prescriptive.**
> **News signals are read-only context.**
> **DraftMind keeps deterministic ranking as the source of truth.**

---

## 8. LLM 配置

DraftMind 遵循 **mock-first** 原则：

| 配置 | 行为 |
|------|------|
| `LLM_PROVIDER=mock` (默认) 或未设 `LLM_API_KEY` | 走 `_mock_explanation`，无网络调用 |
| `LLM_PROVIDER=hunyuan` + `LLM_API_KEY=...` | 走 `_hunyuan_explanation`（腾讯混元，OpenAI 兼容） |
| 真实 provider 抛错 | 自动降级到 mock，演示不中断 |

**`.env` 模板**（见 `.env.example`）：

```bash
LLM_PROVIDER=mock
LLM_MODEL=deepseek-v4-pro
LLM_API_KEY=
LLM_API_BASE=https://tokenhub.tencentmaas.com/v1
```

切换到真实混元：

```bash
LLM_PROVIDER=hunyuan
LLM_API_KEY=<your-tencent-hunyuan-key>
LLM_API_BASE=https://api.hunyuan.tencent.com/v1
```

**前端体验差异**：
- `is_mock=true` → `agent/explanation` 末尾显示 `mock`
- `is_mock=false` → 显示 `provider · model`

底层 `ranking_engine` 与 `simulate_draft` **完全不依赖 LLM**。LLM 只在 `/api/agent/ask` 端点介入。

> LLM may be used for explanation, but it never decides `selected_player`.
> In simulation, market context is generated by deterministic extraction
> and appended to `decision_log`, not used as an LLM decision input.
> 换言之，news / rumor signal 是确定性提取的产物，**不会**作为 LLM 的决策输入
> 进入 `selected_player` / `trade_evaluation` 任何一个字段。

---

## 9. 路线图

### 9.1 ✅ 已完成（按 tag 顺序）

- **simulate-v1-dynamic-needs** — `rounds`/`limit` 真正生效 + 动态 `team_need_state`（位置/技能需求随选人降分）+ trade market signal。
- **simulate-v2-locked-picks** — `locked_picks` 后端支持（prospect_id / prospect_name，case-insensitive，year-safe，duplicate 校验）。
- **simulate-v3-frontend-locked-picks** — UI 接入 locked picks 编辑器 + `手动锁定` 徽章 + 客户端 pre-validation + 友好错误。
- **news-v1-rumor-extractor** — `rumor_extractor` 纯函数：从 cached
  `NewsArticle` 提取 `NewsSignal`（team_abbr / pick_no / prospect_name /
  intent / confidence），关键词 + 权威度 + 时间衰减；不接 `/simulate`、
  不改 `ranking_engine` / `final_score` / `selected_player`。
- **news-v2-simulation-market-context** — `/api/simulate` 在 `decision_log[]`
  末尾追加 `Market context: …` 行（最多 3 条/pick）；不改 ranking /
  selected_player / final_score / trade_evaluation / response schema /
  frontend；不在 simulate 期间联网 refresh news。

### 9.2 🚧 已知限制

- 测试种子数据有限（conftest 中 prospects 与 draft_order 数量较小），单测 64 passed 但 demo 时如遇空候选池会按实际数量返回。
- `import_nba_prospects.py` 对未在 seed 中手动评分的 prospect 走启发式估算，**不是官方 NBA 评分**，不应作为预测展示。
- LLM 真实 provider 走腾讯混元；其他 OpenAI 兼容端点（DeepSeek、moonshot 等）理论上兼容但未逐一验证。
- `start_all.ps1` 是 Windows-only；macOS / Linux 用户需要分步启动（见 §5.2）。
- 交易评估是市场信号；**没有执行过真实交易**，`TradeEvaluation.executed` 永远为 `False`。
- `rumor_extractor` 当前是关键词 + 权威度 + 时间衰减的**启发式提取**；
  LLM-based extraction 是 future work。`confidence` 字段**仅用于阅读排序**，
  **不参与**任何 trade probability 计算。
- Market context 当前**只在 `decision_log` 中以纯文本展示**，没有前端
  结构化 UI（如带颜色的徽章 / trade-up 警示带）；后续如果加 UI，需要
  显式进入下一阶段，且不破 §7.4 的 guarantees。

### 9.3 ❌ 暂不实现

按 `AGENTS.md` MVP scope 明确排除：

- Real-time NBA scraping（演示用本地缓存即可）
- 支付系统
- 用户登录 / 鉴权
- 复杂 multi-agent orchestration
- 真实交易执行
- Monte Carlo simulation
- Strategy mode（如 user team-building、cap-sheet-aware 决策）

---

## 10. Tags / Milestones

| Tag | 范围 | 关键能力 |
|-----|------|----------|
| `simulate-v1-dynamic-needs` | 后端 | `rounds` 真正生效、动态 `team_need_state`、trade market signal |
| `simulate-v2-locked-picks` | 后端 | `locked_picks` schema、校验、`adjust_team_need_after_pick` 链式生效 |
| `simulate-v3-frontend-locked-picks` | 前端 | locked-picks 编辑器、`手动锁定` 徽章、错误解析 |
| `news-v1-rumor-extractor` | 后端 | `rumor_extractor.extract_signals()` 纯函数 + `NewsSignal` dataclass（team_abbr / pick_no / prospect_name / intent / confidence） |
| `news-v2-simulation-market-context` | 后端 | `simulation_service._market_context_lines_for_pick` + `build_decision_log(..., market_context_lines=...)`；不改其他字段、不改 schema、不改 frontend |

---

## 11. Known Limitations

- `ranking_engine` 的权重 (`0.40 / 0.30 / 0.20 / 0.10`) 是 MVP 默认值；演示中展示的"GM 解释"与权重是耦合的，调权重需要回归测试。
- `team_need_state` 是**内存** snapshot，重启进程后会从 SQLite 重新读取 `TeamNeed` 行；这是有意为之，避免 DB 被模拟过程污染。
- 球探报告（scouting report）当前来自 `import_nba_prospects.py` 的启发式文本，不是真实球探报告；演示中可解释但**不能作为决策依据**。
- 完整 60 顺位模拟在 conftest 限制下只跑前 4-30 顺位（取决于 seed 数据），生产数据全量可跑 60 顺位。
- LLM mock 输出是**确定性**模板，演示可重复但不是真正的"GM thinking"。
- Market context 的「cross-team leak」测试只覆盖 `LAL → SAS` 这类基础场景；
  极端的 trade-up rumor 链式影响尚未在测试矩阵中穷举。
- Phase 5B-M1 没有 `trade probability nudge`：news signal 不会让某个 pick 的
  trade action 从 `keep_pick` 翻成 `field_trade_up_calls`；该行为须由显式后续
  阶段才会引入。

---

## 12. RAG-v0 Explanation Safety

RAG-v0 explanation 后端安全闭环已完成。当前链路：

```text
PickEvidencePackage
  -> PickExplanation schema (extra="forbid", decision_locked=True)
  -> evidence_prompt_contract
  -> build_mock_pick_explanation (deterministic)
  -> POST /api/evidence/pick/explanation/mock
  -> build_llm_pick_explanation (guarded shell)
  -> build_evidence_llm_client (provider adapter)
  -> POST /api/evidence/pick/explanation (默认 provider 关闭)
```

**核心保证**：

- **LLM 只解释，不参与选人**。`ranking_engine` / `prediction_calibration` / `simulation_service` 才是选人系统；LLM 永远不能修改 `selected_player` / `final_score` / `prediction_sort_score`。
- **real endpoint 默认关闭真实 provider**（`enable_real_llm_explanation=False`）。provider disabled / no key / timeout / invalid output / unsafe output 都 fallback 到 deterministic mock。
- **决策边界锁定**：`PickExplanation` 使用 `extra="forbid"` + `decision_locked: Literal[True]` + `llm_can_modify_decision: Literal[False]`，禁止任何决策字段泄漏。
- **危险输出整体 fallback**：真实 LLM 输出命中禁用字段（如 `replacement_player`）或危险短语（如 "建议改选"）时，不 sanitize 后继续使用，而是整体 fallback mock。
- **ManualNote evidence-only**：`ManualNote` 只能进入 `retrieved_evidence` / `citations`，标注 `evidence_only`，不参与评分。
- **Citation 不能编造**：`citation_refs` 只能引用输入 `PickEvidencePackage.citations` 中已有的 `source_id` / `title` / `url`。

完整安全说明（链路总览、fallback 行为表、禁用字段/危险语义清单、日志规则、测试清单、未来工作建议）见：

👉 [backend/docs/rag_v0_explanation_safety.md](backend/docs/rag_v0_explanation_safety.md)

---

## 13. 致谢 / 引用

- `nba_api` 用于拉取 NBA.com roster。
- `balldontlie` 免费层用于 standings / 球员数据。
- 腾讯混元 / 腾讯云 tokenhub 提供 LLM 在线推理（可选）。
- `rumor_extractor` 的权威度评分采用**本地硬编码**的 source authority
  启发式；信号与权威度完全基于本地缓存和规则，**不代表实时官方评级**，
  也不直接拉取任何外部 NBA 媒体。

---

## 14. License

MIT planned. A formal LICENSE file can be added before public release.
