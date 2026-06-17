# RAG-v0 Explanation Safety

> 本文档描述 DraftMind RAG-v0 explanation 后端链路的安全闭环。
> 代码名、endpoint、schema、字段名保留英文；其余说明用中文。
>
> 适用范围：`backend/app/services/evidence_*`、`backend/app/routers/evidence.py`、
> `backend/app/schemas/evidence.py` 中与 `PickExplanation` 相关的部分。

---

## 1. RAG-v0 Explanation 链路总览

当前后端 explanation 链路按以下顺序串联，每一层都是只读解释，**不进入选人决策路径**：

```text
PickEvidencePackage
  -> PickExplanation schema                 # extra="forbid", decision_locked=True
  -> evidence_prompt_contract               # system / developer prompt + 禁用字段清单
  -> deterministic mock explanation service  # build_mock_pick_explanation
  -> mock explanation API                    # POST /api/evidence/pick/explanation/mock
  -> guarded LLM explanation service shell   # build_llm_pick_explanation
  -> provider adapter safety layer           # build_evidence_llm_client
  -> guarded real explanation API            # POST /api/evidence/pick/explanation
```

**关键不变量**：

- `PickEvidencePackage` 由 `POST /api/evidence/pick` 构造，输入来自 `simulation` / `pick` / `manual_notes`，**不调用 LLM**。
- `PickExplanation` 是只读解释，`decision_locked: Literal[True]`、`llm_can_modify_decision: Literal[False]`、`extra="forbid"`。
- 真实 LLM 路径默认关闭（`enable_real_llm_explanation=False`），任何失败/不安全输出都 fallback 到 deterministic mock。

---

## 2. 核心安全原则

```text
RAG / Evidence / LLM 只能解释，不能决策。
ranking_engine / prediction_calibration / simulation_service 才是选人系统。
LLM 永远不能修改 selected_player / final_score / prediction_sort_score。
LLM 不能推荐替代人选。
LLM 不能重新排序。
LLM 不能编造 citation。
ManualNote 只能作为 evidence-only，不参与评分。
```

**解释层与决策层的边界**：

| 层 | 职责 | 是否可被 LLM 修改 |
|----|------|-------------------|
| 决策层 | `ranking_engine` / `prediction_calibration` / `simulation_service` 算出 `selected_player` / `final_score` / `prediction_sort_score` | 否 |
| 证据层 | `PickEvidencePackage` 汇总 ranking / team_fit / market / risk / conflict / sufficiency / citations | 否（只读输入） |
| 解释层 | `PickExplanation` 把证据包翻译成 GM 视角叙事 | 仅 `summary` / `key_reasons` / `evidence_notes` / `citation_refs` / `limitations` 等文本字段；**决策字段锁定** |

LLM 输出永远不能跨过解释层进入决策层。

---

## 3. API Endpoint 说明

| Endpoint | 作用 | 是否调用 LLM | 是否查 DB | 是否调用 ranking/prediction/simulation |
|----------|------|--------------|-----------|----------------------------------------|
| `POST /api/evidence/pick` | 构造 `PickEvidencePackage` | 否 | 是（读 prospect / team / manual_note） | 否（读取已有 ranking 结果，不重算） |
| `POST /api/evidence/pick/explanation/mock` | deterministic mock explanation | 否 | 否 | 否 |
| `POST /api/evidence/pick/explanation` | guarded real explanation | 默认否（provider 关闭）；开启后走 guarded shell | 否 | 否 |

**说明**：

- `/pick` 构造 evidence package，输入是 `PickEvidenceRequest`（含 `simulation` / `pick` / `manual_notes`）。
- `/pick/explanation/mock` 使用 deterministic mock explanation，输入是已构造好的 `PickEvidencePackage`，输出是 `PickExplanation`。
- `/pick/explanation` 是 guarded real explanation API，输入同样是 `PickEvidencePackage`，输出同样是 `PickExplanation`；但默认 provider 关闭。
- 两个 explanation endpoint 都是 `PickEvidencePackage -> PickExplanation`，**不重新构造 evidence**。
- real endpoint 失败或 disabled 时 fallback mock，输出与 mock endpoint 完全一致。

---

## 4. Mock vs Real Explanation API 区别

### mock endpoint (`POST /api/evidence/pick/explanation/mock`)

```text
- 永远 deterministic（输入相同 → 输出相同）
- 不接 provider
- 不查 DB
- 不联网
- 适合作为 baseline / fallback / test oracle
- 直接调用 build_mock_pick_explanation(evidence)
```

### real endpoint (`POST /api/evidence/pick/explanation`)

```text
- 通过 build_evidence_llm_client(settings) 获取 client（可能为 None）
- 通过 build_llm_pick_explanation guarded shell 调用 client
- 默认 enable_real_llm_explanation=False
- provider disabled / no key / timeout / invalid output / unsafe output 都 fallback mock
- 不直接暴露 provider 原始输出
- 调用链：PickEvidencePackage -> build_evidence_llm_client -> build_llm_pick_explanation -> PickExplanation
```

**两个 endpoint 的输出 schema 完全一致**，都是 `PickExplanation`（`extra="forbid"`）。

---

## 5. Fallback 行为表

以下场景都会 fallback 到 deterministic mock explanation：

| 场景 | 触发条件 | 行为 |
|------|----------|------|
| provider disabled | `enable_real_llm_explanation=False` | `build_evidence_llm_client` 返回 `None`，shell 走 mock |
| missing API key | `llm_api_key=""` 即使 flag=True | factory 返回 `None`，shell 走 mock |
| provider timeout | `client.complete()` 抛 `TimeoutError` | shell 捕获，走 mock |
| provider error | `client.complete()` 抛 `EvidenceLLMProviderError` 或其他异常 | shell 捕获，走 mock |
| empty provider response | `client.complete()` 返回空字符串 | shell 走 mock |
| invalid JSON | provider 返回非 JSON 文本 | shell 走 mock |
| PickExplanation validation failed | JSON 可解析但字段缺失/类型错误 | shell 走 mock |
| dangerous field | 输出含 `replacement_player` / `new_score` 等禁用字段 | shell 走 mock（不 sanitize） |
| dangerous natural language | 输出含 "建议改选" / "better pick" 等禁用短语 | shell 走 mock（不 sanitize） |
| identity mismatch | `pick_number` / `selected_player_id` / `selected_player_name` 与输入不一致 | shell 走 mock |
| fabricated citation_refs | `citation_refs` 引用了输入 `citations` 之外的 `source_id` | shell 走 mock |
| limited / insufficient 但 limitations 为空 | `evidence_sufficiency.level` 是 `limited`/`insufficient` 但 `limitations` 列表为空 | shell 走 mock |
| conflict_evidence 存在但没有说明冲突 | 输入有 `conflict_evidence` 但 `summary` 未提及冲突 | shell 走 mock |
| risk_evidence 存在但 risk_summary 为空 | 输入有 `risk_evidence` 但 `summary` 未提及风险 | shell 走 mock |

**重要**：真实 LLM 输出命中危险字段或危险短语时，**不能 sanitize 后继续使用**，而是整体 fallback mock。这是为了避免 LLM 通过精心构造的输出绕过清洗。

---

## 6. 禁止字段和危险语义

### 危险字段示例

LLM 输出（JSON）中出现以下任何字段，整体 fallback mock：

```text
replacement_player
recommended_player
new_selected_player
score_adjustment
new_score
rerank_score
ranking_weight
selection_override
final_score_delta
prediction_sort_delta
should_have_selected
better_pick
```

这些字段一旦出现，意味着 LLM 试图跨过解释层进入决策层。

### 危险自然语言示例

LLM 输出（任意文本字段）中出现以下短语，整体 fallback mock：

```text
应该选别人
更好的选择
建议改选
重新排序
提升分数
替代人选
better pick
replacement player
should have selected
rerank
adjust score
score boost
manual note boost
```

**注意**：mock explanation service 内部的 `_sanitize_text` 会对输入 evidence 文本做清洗（替换为 `[redacted]`），但**真实 LLM 输出命中危险短语时是整体 fallback，不是 sanitize 后继续使用**。

---

## 7. ManualNote Evidence-only 规则

```text
ManualNote 只能进入 retrieved_evidence / citations。
ManualNote 必须标注 evidence_only。
ManualNote 不能成为评分权重。
ManualNote 不能提升 final_score。
ManualNote 不能改变 selected_player。
ManualNote 不能改变 prediction_sort_score。
```

**实现要点**：

- `ManualNote` schema 有 `evidence_only: Literal[True]` 字段，**不能设为 `False`**。
- `ManualNote` 进入 `PickEvidencePackage.retrieved_evidence` 和 `PickEvidencePackage.citations`，但**不进入** `ranking_evidence` / `team_fit_evidence`。
- `ranking_engine` / `prediction_calibration` / `simulation_service` **不读取** `ManualNote`。
- `build_mock_pick_explanation` 会对 `ManualNote` 的 `title` / `body` / `excerpt` 做 `_sanitize_text` 清洗，防止危险短语通过输入文本泄漏到输出。

---

## 8. Citation 规则

```text
citation_refs 只能引用输入 PickEvidencePackage.citations 中已有的 source_id / title / url。
不能编造 citation。
不能引用 evidence package 之外的来源。
citation title/url/source_id 中若出现危险短语，也必须被清洗或导致 fallback。
```

**实现要点**：

- `PickExplanation.citation_refs` 是 `list[CitationRef]`，每个 `CitationRef` 的 `source_id` / `title` / `url` 必须能在输入 `PickEvidencePackage.citations` 中找到对应项。
- 真实 LLM 输出的 `citation_refs` 若引用了不存在的 `source_id`，shell 检测到后整体 fallback mock（不部分采纳）。
- mock explanation service 的 `_sanitize_text` 已覆盖 `citation_refs` 的 `source_id` / `title` / `url`，防止危险短语通过 citation 元数据泄漏。

---

## 9. 日志安全规则

### 允许记录

```text
endpoint name
provider enabled/disabled
client created true/false
pick_number
team_abbr
selected_player_id
latency_ms
status success/fallback
fallback_reason 如未来单独记录
token usage 如 provider 安全返回
```

### 禁止记录

```text
API key
完整 PickEvidencePackage
完整 prompt/messages
manual note 原文
retrieved_evidence excerpt 全文
raw LLM output
provider headers
用户私有备注全文
```

**原则**：日志只记录运行时元数据（latency / status / fallback reason），不记录业务数据全文。`manual note` 原文和 `retrieved_evidence excerpt` 属于用户输入/检索结果，可能含敏感信息，不应进入日志。

---

## 10. 测试清单

建议必跑测试命令（按依赖顺序）：

```powershell
cd D:\DraftMind\backend

& "D:\anaconda\python.exe" -m pytest app/tests/test_evidence_schema.py -v
& "D:\anaconda\python.exe" -m pytest app/tests/test_evidence_service.py -v
& "D:\anaconda\python.exe" -m pytest app/tests/test_evidence_api.py -v
& "D:\anaconda\python.exe" -m pytest app/tests/test_evidence_explanation_schema.py -v
& "D:\anaconda\python.exe" -m pytest app/tests/test_evidence_prompt_contract.py -v
& "D:\anaconda\python.exe" -m pytest app/tests/test_evidence_explanation_service.py -v
& "D:\anaconda\python.exe" -m pytest app/tests/test_evidence_explanation_api.py -v
& "D:\anaconda\python.exe" -m pytest app/tests/test_evidence_llm_explanation_service.py -v
& "D:\anaconda\python.exe" -m pytest app/tests/test_evidence_llm_provider.py -v
& "D:\anaconda\python.exe" -m pytest app/tests/test_evidence_real_explanation_api.py -v
& "D:\anaconda\python.exe" -m pytest app/tests -v
```

**测试文件覆盖说明**：

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_evidence_schema.py` | `PickEvidencePackage` / `EvidenceCitation` / `RetrievedEvidence` / `ManualNote` schema 边界 |
| `test_evidence_service.py` | `build_pick_evidence` 构造逻辑、manual_note 映射、retrieved_evidence 注入 |
| `test_evidence_api.py` | `POST /api/evidence/pick` 端点契约 |
| `test_evidence_explanation_schema.py` | `PickExplanation` schema（`extra="forbid"`、`decision_locked`、`llm_can_modify_decision`） |
| `test_evidence_prompt_contract.py` | system / developer prompt 内容、禁用字段清单、输出 schema 示例 |
| `test_evidence_explanation_service.py` | `build_mock_pick_explanation` 确定性输出、`_sanitize_text` 清洗、poisoned input 防护 |
| `test_evidence_explanation_api.py` | `POST /api/evidence/pick/explanation/mock` 端点契约 |
| `test_evidence_llm_explanation_service.py` | `build_llm_pick_explanation` guarded shell 的 13 种 fallback 场景 |
| `test_evidence_llm_provider.py` | `build_evidence_llm_client` factory、`OpenAICompatibleEvidenceLLMClient` adapter、lazy import |
| `test_evidence_real_explanation_api.py` | `POST /api/evidence/pick/explanation` 端点契约、fallback 行为、决策边界锁定 |

---

## 11. 未来工作建议

```text
不建议马上接 frontend。
不建议马上做真实 provider smoke test。
下一步如果做 frontend，只能做 read-only explanation panel。
下一步如果做真实 provider smoke test，必须 dev-only、显式 env、成本限制、不进默认 CI。
```

### 11.1 Frontend 接入原则

如果未来要把 explanation 接入 frontend：

- 只做 **read-only explanation panel**，展示 `PickExplanation` 的 `summary` / `key_reasons` / `evidence_notes` / `citation_refs` / `limitations`。
- **不能**在 frontend 暴露 `enable_real_llm_explanation` 开关给终端用户。
- **不能**在 frontend 允许用户编辑 `PickExplanation` 任何字段。
- **不能**在 frontend 用 explanation 结果覆盖 `selected_player` / `final_score` 显示。

### 11.2 真实 provider smoke test 原则

如果未来要做真实 provider smoke test：

- **dev-only**：只在本地开发环境运行，不进默认 CI。
- **显式 env**：必须显式设置 `ENABLE_REAL_LLM_EXPLANATION=true` + `LLM_API_KEY=...`，不读默认配置。
- **成本限制**：单次 smoke test 调用次数有上限（建议 ≤ 5 次），并记录 token usage。
- **不进默认 CI**：smoke test 文件名建议 `test_evidence_real_provider_smoke.py`，用 `pytest.mark.skipif` 跳过，除非显式 env 触发。
- **不修改生产代码**：smoke test 只验证现有 guarded shell 的端到端行为，不修改 `evidence_llm_provider` / `evidence_llm_explanation_service` 任何代码。

---

## 附录：相关文件索引

| 文件 | 作用 |
|------|------|
| `backend/app/schemas/evidence.py` | `PickEvidencePackage` / `PickExplanation` / `EvidenceCitation` / `RetrievedEvidence` / `ManualNote` schema |
| `backend/app/services/evidence_prompt_contract.py` | system / developer prompt、`FORBIDDEN_OUTPUT_FIELDS`、`OUTPUT_SCHEMA_EXAMPLE` |
| `backend/app/services/evidence_explanation_service.py` | `build_mock_pick_explanation`、`_sanitize_text`、`FORBIDDEN_PHRASES` |
| `backend/app/services/evidence_llm_explanation_service.py` | `build_llm_pick_explanation` guarded shell、`LLMClient` Protocol、`_passes_safety_checks` |
| `backend/app/services/evidence_llm_provider.py` | `build_evidence_llm_client` factory、`OpenAICompatibleEvidenceLLMClient` adapter、`EvidenceLLMProviderError` |
| `backend/app/routers/evidence.py` | `POST /api/evidence/pick`、`POST /api/evidence/pick/explanation`、`POST /api/evidence/pick/explanation/mock` |
| `backend/app/config.py` | `enable_real_llm_explanation` / `llm_explanation_timeout` / `llm_explanation_max_tokens` / `llm_explanation_temperature` 配置 |
