# DraftMind

> NBA draft decision agent — simulate a general manager's draft board with a deterministic, explainable scoring engine.

DraftMind 不会让 LLM 替你做选秀决定。先用 `ranking_engine` 把候选新秀按 **talent / fit / pick value / risk** 打分并排序；只有排序结果出来之后，LLM 才把结构化结果翻译成 GM 视角的叙事。

```text
status : v3 stable
license: MIT
stack : FastAPI + Next.js + SQLite
LLM   : mock-first, hunyuan (腾讯混元) optional
tags  : simulate-v1-dynamic-needs · simulate-v2-locked-picks · simulate-v3-frontend-locked-picks
```

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

---

## 3. 比赛展示亮点

| 亮点 | 实现依据 |
|------|----------|
| **LLM 不参与底层选人** | 排序由 `app/services/ranking_engine.py` 纯函数算出；`ranking_engine` 在 `tests/test_ranking_engine.py` 与 `tests/test_simulation_service.py` 中被覆盖。 |
| **ranking_engine 可解释** | 公式公开 `final = talent*0.40 + fit*0.30 + pick_value*0.20 - risk*0.10`；每个 prospect 附带 5 项分数 + 短句 reasons/risks。 |
| **动态 team_need_state** | 同队第二次签位时，position 与 skill 需求已根据前面已选球员下调；`TeamNeedSnapshot` dataclass 隔离 DB session，**不污染 SQLite**。 |
| **locked picks 沙盘推演** | 用户在 UI 锁定任意顺位 → 后端继续从后续顺位模拟；`decision_log` 包含 `"This pick was locked by user override."`；前端展示 `手动锁定` 徽章。 |
| **GM 视角而非 auto-draft** | `decision_log[]` 逐条说明每签的"GM 思路"，不是单纯的得分排名。 |

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

---

## 9. 路线图

### 9.1 ✅ 已完成（按 tag 顺序）

- **simulate-v1-dynamic-needs** — `rounds`/`limit` 真正生效 + 动态 `team_need_state`（位置/技能需求随选人降分）+ trade market signal。
- **simulate-v2-locked-picks** — `locked_picks` 后端支持（prospect_id / prospect_name，case-insensitive，year-safe，duplicate 校验）。
- **simulate-v3-frontend-locked-picks** — UI 接入 locked picks 编辑器 + `手动锁定` 徽章 + 客户端 pre-validation + 友好错误。

### 9.2 🚧 已知限制

- 测试种子数据有限（conftest 中 prospects 与 draft_order 数量较小），单测 64 passed 但 demo 时如遇空候选池会按实际数量返回。
- `import_nba_prospects.py` 对未在 seed 中手动评分的 prospect 走启发式估算，**不是官方 NBA 评分**，不应作为预测展示。
- LLM 真实 provider 走腾讯混元；其他 OpenAI 兼容端点（DeepSeek、moonshot 等）理论上兼容但未逐一验证。
- `start_all.ps1` 是 Windows-only；macOS / Linux 用户需要分步启动（见 §5.2）。
- 交易评估是市场信号；**没有执行过真实交易**，`TradeEvaluation.executed` 永远为 `False`。

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

---

## 11. Known Limitations

- `ranking_engine` 的权重 (`0.40 / 0.30 / 0.20 / 0.10`) 是 MVP 默认值；演示中展示的"GM 解释"与权重是耦合的，调权重需要回归测试。
- `team_need_state` 是**内存** snapshot，重启进程后会从 SQLite 重新读取 `TeamNeed` 行；这是有意为之，避免 DB 被模拟过程污染。
- 球探报告（scouting report）当前来自 `import_nba_prospects.py` 的启发式文本，不是真实球探报告；演示中可解释但**不能作为决策依据**。
- 完整 60 顺位模拟在 conftest 限制下只跑前 4-30 顺位（取决于 seed 数据），生产数据全量可跑 60 顺位。
- LLM mock 输出是**确定性**模板，演示可重复但不是真正的"GM thinking"。

---

## 12. 致谢 / 引用

- `nba_api` 用于拉取 NBA.com roster。
- `balldontlie` 免费层用于 standings / 球员数据。
- 腾讯混元 / 腾讯云 tokenhub 提供 LLM 在线推理（可选）。

---

## 13. License

MIT
