# RAG-v1 Acceptance Runbook and Smoke Checklist

> 本文档是 RAG-v1（ManualNote persisted evidence retrieval）的验收 runbook。
> 任何人都可以按本文档快速验证：证据能进系统、能给用户看、能给 LLM 看，
> 但证据不能选人、不能改分、不能重排、不能推荐替代球员。
>
> 本文档不涉及业务代码改动，仅作为运维 / 验收 / 回归参考。

---

## 1. RAG-v1 目标

RAG-v1 的目标是：让持久化的 ManualNote（手工证据）作为 **explanation-only context** 进入 DraftMind 的证据链路，同时严格保持安全边界。

白话目标：

```text
证据能进系统
证据能给用户看
证据能给 LLM 看
但证据不能选人、不能改分、不能重排、不能推荐替代球员
```

核心设计原则（来自 `AGENTS.md`）：

- LLM output should explain model results, not replace model results.
- All player recommendations must come from the ranking_engine first.
- ManualNote 只进入 `retrieved_evidence` / `citations`，不进入决策字段。

---

## 2. RAG-v1 完整链路

```text
[manual_notes 表 / ManualNoteRecord]
      │  read-only SELECT, evidence_only=True base filter
      ▼
retrieve_manual_note_documents(db, year, limit, [prospect_id|team_id|pick_no])
      │  → EvidenceDocumentRead (source_type="manual_note", evidence_only=True)
      ▼
manual_note_record_to_evidence_document(record)
      │  adapter: tags split, excerpt fallback (summary → body truncated)
      ▼
EvidenceDocumentRead
      │  pure schema-to-schema, Literal[True] lock
      ▼
map_evidence_document(document)
      │  → (RetrievedEvidence, EvidenceCitation)
      ▼
_append_persisted_manual_notes()  [位于 evidence_service.build_pick_evidence]
      │  - 三次 OR 调用：prospect_id / team_id / pick_no
      │  - source_id 去重
      │  - 全局 cap = PERSISTED_MANUAL_NOTE_LIMIT = 5
      │  - 失败 try/except + logger.warning + continue
      ▼
PickEvidencePackage.retrieved_evidence / citations   (仅这两个字段被 append)
      │
      ▼
POST /api/evidence/pick  (config-gated: evidence_retrieve_manual_notes)
      │
      ├──→ Frontend EvidencePanel (只读展示, D2)
      │      - RetrievedEvidenceList: 手工证据 badge + 仅用于解释 + 已持久化 + 不参与选人
      │      - CitationList: 同上
      │
      └──→ LLM explanation (D3)
             - _build_llm_explanation_payload(evidence) 白名单
             - manual_note 保留但带 evidence_only=True
             - long excerpt 截断到 500 字符
             - dangerous fields 排除
             - prompt contract 明确 manual_note safety rules
             - 任何失败 fallback 到 deterministic mock
```

启用条件触发点（唯一生产调用点）：

```text
POST /api/evidence/pick
  → router.build_pick_evidence_api
      settings = get_settings()
      retrieve = settings.evidence_retrieve_manual_notes
      build_pick_evidence(
          ...,
          db=db if retrieve else None,
          retrieve_knowledge=retrieve,
      )
```

---

## 3. D1/D2/D3 对应 tag

| 阶段 | 内容 | 对应 commit | 对应 tag |
|---|---|---|---|
| B1 | EvidenceDocumentRead mapper foundation | `15ed00f` | `rag-v1-b1-evidence-document-mapper-foundation` |
| B2 | ManualNote persistence foundation | `bf0e8c2` | `rag-v1-b2-manual-note-persistence-foundation` |
| B3 | ManualNote evidence document adapter | `8d47542` | `rag-v1-b3-manual-note-evidence-adapter` |
| C1 | ManualNote retrieval service foundation | `da1b8be` | `rag-v1-c1-manual-note-retrieval-service` |
| D1-A | ManualNote retrieval 接入 build_pick_evidence | `f371c31` | `rag-v1-d1a-manual-note-evidence-package-integration` |
| D1-C | Config-gated router 开关 | `58eddb7` | `rag-v1-d1c-config-gated-manual-note-retrieval` |
| D1-E1 | Runtime logging | `c0e2d10` | `rag-v1-d1e1-manual-note-retrieval-runtime-logging` |
| D1-E2 | Dev-only seed script | `a4a9e02` | `rag-v1-d1e2-dev-manual-note-seed-script` |
| D1 封口 | ManualNote retrieval acceptance | `a4a9e02` | `rag-v1-d1-manual-note-retrieval-acceptance` |
| D2-A | Frontend ManualNote evidence read-only display | `460dad5` | `rag-v1-d2a-frontend-manual-note-evidence-display` |
| D2 封口 | Frontend display acceptance | `460dad5` | `rag-v1-d2-frontend-manual-note-display-acceptance` |
| D3-B | LLM evidence payload safety hardening | `0ed3162` | `rag-v1-d3b-llm-evidence-payload-safety` |
| D3 封口 | LLM payload safety acceptance | `0ed3162` | `rag-v1-d3-llm-evidence-payload-safety-acceptance` |
| **Final** | **RAG-v1 final acceptance** | `0ed3162` | `rag-v1-final-acceptance` |

当前 HEAD：`0ed3162 Harden LLM evidence payload safety`

---

## 4. 如何运行 dev seed

dev seed script 用于向 `manual_notes` 表写入 6 条 demo ManualNoteRecord，方便本地验证 persisted retrieval 链路。

```powershell
cd D:\DraftMind\backend
D:\anaconda\python.exe scripts\seed_manual_notes.py
```

预期输出：

```text
created_count: 6
skipped_count: 0
total_seed_notes: 6
```

seed script 安全属性：

- **dev-only**：位于 `backend/scripts/`，未挂载到任何 router / API / CLI 入口
- **idempotent**：dedup key = (source, title, year, entity_type, entity_id, prospect_id, team_id, pick_no)，重复运行不会重复插入
- **不删不覆盖 custom notes**：仅查询 `source="manual_seed"` 行做 dedup，从不 `db.delete()` 或 `db.update()`
- **所有 seed note `evidence_only=True`**
- **不触碰 ranking/system 表**（Team / Prospect / DraftOrder / Roster / TeamNeed）

---

## 5. 如何临时打开 retrieval flag

ManualNote retrieval 默认 **关闭**。需要临时打开时，设置环境变量：

```powershell
# PowerShell（当前 session 有效）
$env:EVIDENCE_RETRIEVE_MANUAL_NOTES="True"

# 然后启动后端
cd D:\DraftMind\backend
D:\anaconda\python.exe -m uvicorn app.main:app --reload
```

关闭（恢复默认）：

```powershell
Remove-Item Env:EVIDENCE_RETRIEVE_MANUAL_NOTES
# 或
$env:EVIDENCE_RETRIEVE_MANUAL_NOTES="False"
```

> **注意**：此 flag 只能由服务端 config 控制。Frontend 无法通过 API 参数、UI 控件或 env 变量控制此 flag。

---

## 6. 如何验证 settings 读取

```powershell
cd D:\DraftMind\backend
D:\anaconda\python.exe -c "from app.config import get_settings; print(get_settings().evidence_retrieve_manual_notes)"
```

预期输出：

- 默认（未设置 env）：`False`
- 设置 `$env:EVIDENCE_RETRIEVE_MANUAL_NOTES="True"` 后：`True`

> **注意**：`get_settings()` 被 `@lru_cache` 装饰，修改 env 后需重启 Python 进程或调用 `get_settings.cache_clear()` 才能生效。

---

## 7. 如何验证 `/api/evidence/pick` 出现 manual_note

### 前置条件

1. 已运行 dev seed（见第 4 节）
2. 已打开 retrieval flag（见第 5 节）
3. 后端已启动

### 验证步骤

```powershell
# 1. 确认 flag 已打开
D:\anaconda\python.exe -c "from app.config import get_settings; print(get_settings().evidence_retrieve_manual_notes)"
# 预期: True

# 2. 启动后端（如未启动）
cd D:\DraftMind\backend
D:\anaconda\python.exe -m uvicorn app.main:app --reload

# 3. 调用 /api/evidence/pick（需先通过 /api/simulate 获取 simulation + pick）
#    可用 curl / Postman / 前端 UI 触发
```

### 预期结果

`PickEvidencePackage` 的 `retrieved_evidence` 数组中出现 `source_type="manual_note"` 的条目：

```json
{
  "retrieved_evidence": [
    {
      "source_type": "manual_note",
      "source_id": "manual_seed:...",
      "title": "...",
      "excerpt": "...",
      "evidence_only": true,
      ...
    }
  ],
  "citations": [
    {
      "source_type": "manual_note",
      "evidence_source_type": "manual_note",
      "evidence_only": true,
      ...
    }
  ]
}
```

### 关键不变项

```text
selected_player 不变
final_score 不变
prediction_sort_score 不变
ranking_evidence 不变
market_evidence 不变
risk_evidence 不变
```

### flag=False 时

`retrieved_evidence` / `citations` 中不出现 `manual_note`，行为与 RAG-v1 之前完全一致。

---

## 8. 如何确认 frontend 只读展示

### 前置条件

1. 后端已启动且 retrieval flag=True
2. Frontend 已启动（`cd frontend && npm run dev`）
3. 已运行 dev seed

### 验证步骤

1. 打开 `http://localhost:3000/draft`
2. 运行模拟，选择一个 pick
3. 点击「查看证据」按钮
4. 在 Evidence Panel 中查看 `补充证据` 和 `参考来源` 区块

### 预期 UI 文案

ManualNote evidence 应显示以下 badge / 文案：

| 位置 | 文案 | 含义 |
|---|---|---|
| badge | `手工证据` | 来源类型标识 |
| badge | `仅用于解释` | evidence-only 语义 |
| badge | `已持久化` | 来自 DB 持久化 |
| 底部小字 | `不参与选人` | 安全提示 |
| 计数摘要 | `含 N 条手工证据 · 仅用于解释` | 列表级摘要 |

### 必须不出现的交互

```text
编辑 note 按钮
删除 note 按钮
创建 note 按钮
保存 note 按钮
应用到推荐 按钮
调整分数 按钮
替换球员 按钮
重新排序 按钮
```

Frontend 必须保持完全只读。

---

## 9. 如何确认 LLM payload safety

### 核心变更（D3-B）

Real LLM explanation 不再直接吃完整 `evidence.model_dump()`，而是通过 `_build_llm_explanation_payload(evidence)` 构建白名单 payload。

### 验证点

| 验证点 | 如何确认 |
|---|---|
| 不再吃完整 `evidence.model_dump()` | 查看 `evidence_llm_explanation_service.py` 的 `_call_llm` 函数，确认调用 `_build_llm_explanation_payload(evidence)` |
| 使用 `_build_llm_explanation_payload` | 同上，payload 变量来自该 helper |
| long excerpt 截断 | `LLM_EXCERPT_MAX_CHARS = 500`，超过 500 字符的 excerpt 被截断为 497 字符 + `"..."` |
| dangerous fields 排除 | payload 不含 `candidate_board` / `alternatives` / `simulation` / `replacement_player` / `score_adjustment` / `selection_override` 等 |
| manual_note 仍进入 payload | `retrieved_evidence` 和 `citations` 中保留 `source_type="manual_note"` 条目，带 `evidence_only=True` |
| prompt contract 强化 | `evidence_prompt_contract.py` 包含 `## ManualNote safety rules (RAG-v1-D3-B)` 段落 |
| 不 mutate 原 package | `_build_llm_explanation_payload` 只读不写 |
| fallback 不变 | 任何失败仍 fallback 到 `build_mock_pick_explanation(evidence)` |

### 自动化验证

```powershell
cd D:\DraftMind\backend
D:\anaconda\python.exe -m pytest app/tests/test_evidence_llm_payload_safety.py -v
```

预期：45 passed

---

## 10. 必须保持的安全边界

### ManualNote 不能做的事

```text
ManualNote 不改 selected_player
ManualNote 不改 final_score
ManualNote 不改 prediction_sort_score
ManualNote 不改 ranking_evidence
ManualNote 不改 market_evidence
ManualNote 不改 risk_evidence
ManualNote 不改 conflict_evidence
ManualNote 不改 evidence_sufficiency
```

### LLM 不能做的事

```text
LLM 不能推荐替代球员
LLM 不能改分
LLM 不能重排
LLM 不能改 selected_player
LLM 不能改 final_score
LLM 不能改 prediction_sort_score
LLM 不能输出 replacement_player / score_adjustment / selection_override 等危险字段
```

### Fallback 语义

任何失败（LLM 异常、invalid JSON、schema validation 失败、safety check 失败、dangerous phrase）都 fallback 到 `build_mock_pick_explanation(evidence)`，返回 deterministic mock explanation。

### Schema 层 Literal 锁

```text
EvidenceDocumentRead.evidence_only: Literal[True]
RetrievedEvidence.evidence_only: Literal[True]
EvidenceCitation.evidence_only: Literal[True]
PickExplanation: extra="forbid"
```

---

## 11. 推荐 smoke test 命令

### 核心回归（RAG-v1 三大支柱）

```powershell
cd D:\DraftMind\backend

# D1: ManualNote persisted backend retrieval
D:\anaconda\python.exe -m pytest app/tests/test_evidence_service_manual_note_retrieval.py -v
D:\anaconda\python.exe -m pytest app/tests/test_evidence_router_manual_note_retrieval.py -v

# D3: LLM evidence payload safety
D:\anaconda\python.exe -m pytest app/tests/test_evidence_llm_payload_safety.py -v
```

预期：

```text
test_evidence_service_manual_note_retrieval.py: 29 passed
test_evidence_router_manual_note_retrieval.py: 19 passed
test_evidence_llm_payload_safety.py: 45 passed
```

### 全量回归

```powershell
cd D:\DraftMind\backend
D:\anaconda\python.exe -m pytest app/tests -q
```

预期：979 passed（截至 RAG-v1 final acceptance）

### 前端 build 检查

```powershell
cd D:\DraftMind\frontend
npm run build
```

预期：Compiled successfully + Linting and checking validity of types + Generating static pages (5/5)

---

## 12. RAG-v1 不包含什么

RAG-v1 是 **persisted ManualNote evidence retrieval** 的最小可用版本，明确不包含：

```text
不包含 vector store（FAISS / Chroma / pgvector 等）
不包含 embedding
不包含 semantic retrieval
不包含 chunking
不包含 ManualNote create API（写入仍只能通过 seed script 或直接 DB 操作）
不包含 frontend 写入 ManualNote（frontend 完全只读）
不包含 real LLM provider 接入（LLM shell 已就绪，但未接真实 provider）
不包含 multi-source retrieval（仅 ManualNote 单一知识源）
不包含 retrieval ranking / reranking（仅按 updated_at / created_at / id 排序）
不包含 auth / rate limiting（MVP scope 明确不实现 user login）
```

---

## 13. 下一阶段 RAG-v2 可以考虑什么

以下方向仅供参考，具体 scope 需独立任务定义：

### 方向 A：ManualNote create API

- 打通 ManualNote 写入路径，让用户能通过 API 创建 note
- 需先定义 auth / rate limit 策略（当前 MVP 无 auth）
- 需 schema 验证、防注入、防滥用
- 风险：中高（write API 在无 auth 环境下风险高）

### 方向 B：多知识源抽象（KnowledgeSource interface）

- 把 ManualNote 抽象为 `KnowledgeSource` 接口
- 未来可接入 news / scouting_report / stats 等多源
- 需重新设计 retrieval 接口、ranking 注入策略、配置体系
- 风险：高（架构层重构，需 ≥2 个具体知识源验证抽象合理性）
- 时机：建议在有第二个知识源需求时再做

### 方向 C：向量检索 / semantic retrieval

- 引入 embedding + vector store（FAISS / Chroma）
- 让 retrieval 基于 semantic similarity 而非精确字段匹配
- 需新增 embedding model 依赖、vector store 运维
- 风险：中（技术成熟，但增加运维复杂度）
- 时机：当 manual_notes 数据量大（>1000 行）且精确匹配召回率不足时

### 方向 D：LLM explanation 消费 enriched evidence（深度优化）

- 让 LLM 真正利用 manual_note 生成更丰富的解释
- 需 prompt engineering 迭代、A/B 测试
- 需接 real LLM provider
- 风险：低（payload safety 已由 D3-B 锁定）
- 时机：可作为 RAG-v2 的第一个任务

### 方向 E：Frontend UI polish

- 折叠 / 分组 / 排序 / 空状态优化
- manual_note 与其他 evidence 的视觉区分增强
- 风险：低（纯前端）
- 时机：随时可做，但优先级低于功能扩展

### 推荐优先级

```text
1. 方向 D（LLM explanation 深度优化）— 最低风险，最快体现 RAG 价值
2. 方向 A（ManualNote create API）— 补齐 CRUD，但需先解决 auth
3. 方向 C（向量检索）— 当数据量增长时再做
4. 方向 B（多知识源抽象）— 当有第二个知识源需求时再做
5. 方向 E（UI polish）— 随时可做，优先级最低
```

---

## 附录：快速 smoke checklist

```text
[ ] 1. git status --short  →  clean
[ ] 2. git log --oneline -1  →  0ed3162 Harden LLM evidence payload safety
[ ] 3. git tag --list "rag-v1-*"  →  14 tags, 含 rag-v1-final-acceptance

[ ] 4. cd backend && python scripts/seed_manual_notes.py  →  created_count: 6
[ ] 5. $env:EVIDENCE_RETRIEVE_MANUAL_NOTES="True"
[ ] 6. python -c "from app.config import get_settings; print(get_settings().evidence_retrieve_manual_notes)"  →  True
[ ] 7. 启动后端，调用 /api/evidence/pick  →  retrieved_evidence 含 manual_note
[ ] 8. selected_player / final_score / prediction_sort_score 不变
[ ] 9. frontend /draft  →  Evidence Panel 显示 手工证据 / 仅用于解释 / 已持久化 / 不参与选人
[ ] 10. frontend 无写入交互

[ ] 11. pytest test_evidence_service_manual_note_retrieval.py -v  →  29 passed
[ ] 12. pytest test_evidence_router_manual_note_retrieval.py -v  →  19 passed
[ ] 13. pytest test_evidence_llm_payload_safety.py -v  →  45 passed
[ ] 14. pytest app/tests -q  →  979 passed
[ ] 15. cd frontend && npm run build  →  Compiled successfully
```
