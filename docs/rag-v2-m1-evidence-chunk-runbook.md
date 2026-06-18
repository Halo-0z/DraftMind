# RAG-v2-M1 EvidenceChunk Foundation Runbook / Smoke Checklist

> 本文档覆盖 RAG-v2-M1 阶段（M1-B + M1-D）的验收说明、smoke test 流程与安全边界。
> 本文档不包含业务代码，仅为运维 / 验收 / 交接参考。

---

## 1. M1 的目标

RAG-v2-M1 是 RAG-v2 的"证据块地基"阶段。其目标是在不引入 embedding、vector store、semantic retrieval 的前提下，建立一套**纯内存、纯函数**的 schema 与转换链路，使未来的 M2（本地语义检索）可以直接复用。

M1 的核心交付物：

- **EvidenceChunk schema**：统一的证据块契约，作为未来检索系统的输出单元。
- **evidence_chunk_to_document() mapper**：将 EvidenceChunk 转换为已有的 EvidenceDocumentRead，复用现有 evidence pipeline。
- **manual_note_record_to_evidence_chunk() adapter**：将 DB 中的 ManualNoteRecord 安全转换为 EvidenceChunk。

M1 完成后，以下链路可用（纯内存，不接检索）：

```
ManualNoteRecord
  -> EvidenceChunk
  -> EvidenceDocumentRead
  -> map_evidence_document()
  -> RetrievedEvidence / EvidenceCitation
```

M1 不做：embedding、vector store、semantic retrieval、API 接入、前端改动、DB 新表。

---

## 2. 当前已完成的 M1-B / M1-D tag

| 里程碑 | 提交 | tag（代码） | tag（验收） | 说明 |
|---|---|---|---|---|
| M1-B | `f82e246` | `rag-v2-m1b-evidence-chunk-foundation` | `rag-v2-m1b-evidence-chunk-foundation-acceptance` | EvidenceChunk schema + evidence_chunk_to_document mapper + 测试 |
| M1-D | `2784330` | `rag-v2-m1d-manual-note-chunk-adapter` | `rag-v2-m1d-manual-note-chunk-adapter-acceptance` | ManualNoteRecord -> EvidenceChunk adapter + 测试 |

查看 tag：

```powershell
cd D:\DraftMind
git tag --list "rag-v2-*"
git log --oneline --decorate -15
```

---

## 3. EvidenceChunk schema 的作用

EvidenceChunk 是 RAG-v2 的**检索单元契约**。它代表一段可以被语义检索、可以被解释引用的文本块。

定义位置：`backend/app/schemas/evidence.py`

核心字段：

| 类别 | 字段 | 说明 |
|---|---|---|
| 身份 | `chunk_id` / `source_type` / `source_id` / `chunk_index` / `chunk_count` | chunk 全局 ID、来源类型、来源 ID、chunk 序号与总数 |
| 内容 | `title` / `content` / `excerpt` | 标题、正文（min_length=1 + 非空白校验）、摘要 |
| 实体 | `entity_type` / `entity_id` / `prospect_id` / `prospect_name` / `team_id` / `team_abbr` / `pick_no` / `year` | 关联的球员/球队/顺位/年份 |
| 来源元数据 | `url` / `source_name` / `publisher` / `author` / `published_at` | 来源 URL、名称、出版方、作者、发布时间 |
| 检索元数据 | `confidence` / `retrieval_score` / `relevance_reason` / `conflict_note` / `tags` | 置信度、检索得分、相关性理由、冲突说明、标签 |
| 安全锁 | `evidence_only: Literal[True]` | 强制为 True，不可设为 False / None |

安全约束：

- `model_config = ConfigDict(extra="forbid")`：拒绝任何未知字段。
- `evidence_only: Literal[True] = True`：无法被设为 False / None。
- `@field_validator("content")`：拒绝空字符串和纯空白字符串。
- `@model_validator(mode="after")`：强制 `chunk_index < chunk_count`。
- 12 个危险字段（`recommended_player` / `rerank_score` / `selection_override` 等）全部被 `extra="forbid"` 拒绝。

作用：

- 为 M2 检索服务提供统一的输出 schema。
- 为 evidence pipeline 提供可转换的中间表示。
- 通过 `evidence_only` Literal 锁确保证据"只用于解释，不参与选人"。

---

## 4. evidence_chunk_to_document() 的作用

定义位置：`backend/app/services/evidence_chunk_mapper.py`

签名：

```python
def evidence_chunk_to_document(chunk: EvidenceChunk) -> EvidenceDocumentRead:
    ...
```

作用：

将 `EvidenceChunk` 转换为已有的 `EvidenceDocumentRead`，使 chunk 能够复用现有的 evidence pipeline（`map_evidence_document()` → `RetrievedEvidence` / `EvidenceCitation`）。

关键行为：

- `chunk_id` → `source_id`（chunk 全局 ID 作为文档 ID）。
- `excerpt` 为 None 时从 `content` 生成，截断到 `EXCERPT_MAX_CHARS = 1200`。
- `published_at`（datetime）→ ISO 8601 字符串。
- `tags` 用 `list(chunk.tags)` 复制，不共享可变引用。
- 输出 `evidence_only=True`（由目标 schema Literal 锁定）。
- 不修改输入 chunk。
- 纯函数：无 DB / LLM / 网络 / ranking_engine 调用。

---

## 5. manual_note_record_to_evidence_chunk() 的作用

定义位置：`backend/app/services/manual_note_chunk_adapter.py`

签名：

```python
def manual_note_record_to_evidence_chunk(note: ManualNoteRecord) -> EvidenceChunk:
    ...
```

作用：

将 DB 中的 `ManualNoteRecord`（手工证据行）安全转换为 `EvidenceChunk`，使手工证据能够进入 RAG-v2 的 chunk 链路。

关键行为：

- **入口安全检查**：`note.evidence_only is not True` 时抛出 `ValueError`，拒绝非 evidence-only 行。
- `chunk_id = f"manual_note:{note.id}:0"`（稳定格式）。
- `source_type = "manual_note"`（固定）。
- `source_id = str(note.id)`。
- `chunk_index = 0` / `chunk_count = 1`（单 chunk）。
- `content = note.body`（NOT NULL 列）。
- `excerpt = note.summary`（非空时），否则 None（由下游 chunk_mapper 从 content 生成）。
- `tags = _split_tags(note.tags)`（逗号分隔字符串 → list[str]，strip + 去空条目）。
- `published_at = note.updated_at`（fallback `note.created_at`）。
- `retrieval_score = None`（**不生成**，留给检索服务）。
- `prospect_name` / `team_abbr` / `publisher` / `conflict_note` = None（ManualNoteRecord 不存储这些字段）。
- 不修改输入 note。
- 纯函数：无 DB session / LLM / ranking_engine / simulation_service / prediction_calibration / recommendation_service 调用。

---

## 6. 当前完整链路

```
ManualNoteRecord (DB row, evidence_only=True)
  |
  |  manual_note_record_to_evidence_chunk()     [M1-D adapter]
  v
EvidenceChunk (schema, evidence_only=True, retrieval_score=None)
  |
  |  evidence_chunk_to_document()                [M1-B mapper]
  v
EvidenceDocumentRead (schema, evidence_only=True)
  |
  |  map_evidence_document()                     [RAG-v1-B1 mapper]
  v
(RetrievedEvidence, EvidenceCitation)
  |
  |  RetrievedEvidence: 用于 LLM 解释排序
  |  EvidenceCitation: 用于前端展示
  v
PickEvidencePackage -> LLM explanation (只读解释，不参与选人)
```

链路特点：

- 全程 `evidence_only=True`，Literal 锁定。
- `retrieval_score` 在 M1 阶段始终为 None（adapter 不生成）。
- `retrieval_score` 若被检索服务填充，会进入 `RetrievedEvidence`（用于解释排序），但**不进入** `EvidenceCitation`（前端展示）。
- 链路中任何环节都不调用 ranking_engine / simulation_service / prediction_calibration / recommendation_service。
- 链路中任何环节都不影响 `selected_player` / `final_score` / `prediction_sort_score`。

---

## 7. 如何运行 smoke tests

```powershell
cd D:\DraftMind\backend

# M1-B: EvidenceChunk schema 验证
D:\anaconda\python.exe -m pytest app/tests/test_evidence_chunk_schema.py -v

# M1-B: evidence_chunk_to_document mapper 验证
D:\anaconda\python.exe -m pytest app/tests/test_evidence_chunk_mapper.py -v

# M1-D: manual_note_record_to_evidence_chunk adapter 验证
D:\anaconda\python.exe -m pytest app/tests/test_manual_note_chunk_adapter.py -v

# RAG-v1-B1 回归: map_evidence_document 验证
D:\anaconda\python.exe -m pytest app/tests/test_evidence_document_mapper.py -v
```

预期结果：

| 测试文件 | 预期测试数 | 预期结果 |
|---|---|---|
| `test_evidence_chunk_schema.py` | 38 | 全部 passed |
| `test_evidence_chunk_mapper.py` | 29 | 全部 passed |
| `test_manual_note_chunk_adapter.py` | 50 | 全部 passed |
| `test_evidence_document_mapper.py` | 21 | 全部 passed |
| **合计** | **138** | **全部 passed** |

如需运行全套回归：

```powershell
cd D:\DraftMind\backend
D:\anaconda\python.exe -m pytest app/tests -q
```

预期：1096 passed（含 M1-D 的 50 项新增）。

---

## 8. 每个测试文件验证什么

### test_evidence_chunk_schema.py（38 项）

验证 EvidenceChunk schema 的约束完整性：

- 最小/全字段创建。
- `content` 空/空白拒绝（`field_validator`）。
- `chunk_index` / `chunk_count` 边界与关系（`chunk_index < chunk_count`）。
- `confidence` / `retrieval_score` [0,1] 边界。
- `evidence_only` Literal 锁（False / None 拒绝）。
- 12 个危险字段参数化拒绝（`extra="forbid"`）。
- 未知字段拒绝。
- `tags` 默认不共享 / 提供不被修改。
- `pick_no` / `year` 范围。

### test_evidence_chunk_mapper.py（29 项）

验证 `evidence_chunk_to_document()` 的转换正确性：

- 字段映射（身份/实体/内容/来源/检索元数据/tags）。
- `excerpt` 显式提供 / 自动生成 / 长内容截断 / 精确边界不截断。
- 不修改输入 chunk（deepcopy + 字段比对）。
- 输出 `evidence_only=True`。
- 模块不导入 DB / LLM / ranking_engine（AST 解析实际 import 语句）。
- 全链路：EvidenceChunk → EvidenceDocumentRead → map_evidence_document。
- `retrieval_score` 进入 `RetrievedEvidence` 但不进入 `EvidenceCitation`。
- `published_at` 流转为 ISO 字符串。

### test_manual_note_chunk_adapter.py（50 项）

验证 `manual_note_record_to_evidence_chunk()` 的转换正确性与安全性：

- 基本映射（source_type / source_id / chunk_id 格式 / chunk_index=0 / chunk_count=1）。
- `evidence_only=True` 通过；`False` / `None` 拒绝（ValueError）。
- `content` = body；`excerpt` = summary（非空/None/空/空白）。
- 实体/元数据映射（entity 字段 / prospect_name=None / team_abbr=None / url / source_name / author / publisher=None / confidence / relevance_reason / published_at）。
- `tags` 分割 / strip / 去空 / 不共享引用。
- `retrieval_score` 始终 None。
- 不修改输入 record（deepcopy 快照比对）。
- 模块不导入 DB session / LLM / decision modules（AST）。
- 不调用 `ranking_engine.rank_prospects`（monkeypatch）。
- 不暴露 12 个危险字段。
- 全链路：ManualNoteRecord → EvidenceChunk → EvidenceDocumentRead → map_evidence_document（13 项）。

### test_evidence_document_mapper.py（21 项，RAG-v1-B1 回归）

验证 `map_evidence_document()` 的转换正确性（M1 未修改此文件，仅回归验证）：

- `EvidenceDocumentRead` → `RetrievedEvidence` + `EvidenceCitation` 字段映射。
- `evidence_only` 全程保留。
- `retrieval_score` 进入 `RetrievedEvidence` 但不进入 `EvidenceCitation`。
- `tags` / `confidence` / `published_at` 流转。

---

## 9. 必须保持的安全边界

M1 阶段及之后，以下边界必须严格保持：

### 代码边界

| 边界 | 要求 |
|---|---|
| 不新增 DB model | EvidenceChunk 是 Pydantic schema，不是 SQLAlchemy model。不新增 `backend/app/models/*` |
| 不新增 API / router | 不新增 `backend/app/routers/*`，不接 `/api/evidence/pick` |
| 不修改 frontend | 不触碰 `frontend/*` |
| 不接 embedding | M1 阶段无 embedding 代码 |
| 不接 vector store | M1 阶段无 FAISS / Chroma / 其他 vector store |
| 不做 semantic retrieval | M1 阶段无语义检索逻辑 |

### 调用边界

| 边界 | 要求 |
|---|---|
| 不调用 ranking_engine | adapter / mapper 不导入、不调用 `ranking_engine` |
| 不调用 simulation_service | adapter / mapper 不导入、不调用 `simulation_service` |
| 不调用 prediction_calibration | adapter / mapper 不导入、不调用 `prediction_calibration` |
| 不调用 recommendation_service | adapter / mapper 不导入、不调用 `recommendation_service` |

### 数据边界

| 边界 | 要求 |
|---|---|
| 不影响 `selected_player` | 证据链路不修改选人结果 |
| 不影响 `final_score` | 证据链路不修改评分 |
| 不影响 `prediction_sort_score` | 证据链路不修改排序 |

### 安全锁

| 锁 | 机制 |
|---|---|
| `evidence_only: Literal[True]` | EvidenceChunk / EvidenceDocumentRead / RetrievedEvidence / EvidenceCitation 均有此字段，Pydantic Literal 锁定，无法设为 False / None |
| `extra="forbid"` | EvidenceChunk schema 拒绝任何未知字段，12 个危险字段无法注入 |
| adapter 入口检查 | `manual_note_record_to_evidence_chunk()` 检查 `note.evidence_only is not True`，拒绝非 evidence-only 行 |

---

## 10. retrieval_score 当前边界

`retrieval_score` 是 EvidenceChunk 的可选字段（`float | None`，范围 [0,1]），代表检索系统对该 chunk 的相关性打分。

### M1 阶段边界

| 边界 | 状态 | 说明 |
|---|---|---|
| EvidenceChunk 可以有 `retrieval_score` 字段 | ✅ 是 | schema 定义了 `retrieval_score: float | None = Field(default=None, ge=0, le=1)` |
| ManualNote adapter 不生成 `retrieval_score` | ✅ 是 | `manual_note_record_to_evidence_chunk()` 始终设为 `None`；`test_adapter_retrieval_score_is_none` 验证 |
| `retrieval_score` 不能进入 `EvidenceCitation` | ✅ 是 | `EvidenceCitation` schema 无 `retrieval_score` 字段；`map_evidence_document()` 不传递此字段到 citation；`test_full_chain_retrieval_score_stays_none_in_citation` 验证 |
| `retrieval_score` 不能影响选人/评分/排序 | ✅ 是 | adapter / mapper 不调用 ranking_engine / simulation_service / prediction_calibration / recommendation_service；`retrieval_score` 仅存在于 `RetrievedEvidence`（用于 LLM 解释排序），不进入任何决策路径 |

### M2 预期变化

M2（本地语义检索）将：

1. 由检索服务（不是 adapter）计算 `retrieval_score`。
2. 将 `retrieval_score` 填入 `EvidenceChunk.retrieval_score`。
3. `retrieval_score` 通过 `evidence_chunk_to_document()` → `EvidenceDocumentRead.retrieval_score` → `RetrievedEvidence.retrieval_score` 流转。
4. `retrieval_score` **不进入** `EvidenceCitation`（前端展示层不暴露检索得分）。
5. `retrieval_score` **不影响** `selected_player` / `final_score` / `prediction_sort_score`。

---

## 11. M1 不包含什么

| 不包含项 | 说明 |
|---|---|
| DB model | EvidenceChunk 是 Pydantic schema，不是 SQLAlchemy model。无 `backend/app/models/evidence_chunk.py` |
| Migration | 无 Alembic migration |
| Seed script | 无新增 seed script |
| API / router | 无新增 API 端点，不接 `/api/evidence/pick` |
| Frontend 改动 | 不触碰 `frontend/*` |
| Embedding | 无 embedding 模型调用 |
| Vector store | 无 FAISS / Chroma / 其他 vector store |
| Semantic retrieval | 无语义检索逻辑 |
| Chunking service | 无自动文本切分服务（M1-D 的 adapter 是 1:1 映射，1 个 note → 1 个 chunk） |
| Wiring | adapter 未被 wire 到 `build_pick_evidence` / `evidence_service` / `manual_note_retrieval_service` |
| LLM 调用 | adapter / mapper 不调用 LLM |
| ranking_engine 调用 | adapter / mapper 不调用 ranking_engine |
| Multi-source adapter | 仅 ManualNote → EvidenceChunk，无 news / scouting report 等其他来源的 adapter |

---

## 12. M2 之前必须再次确认什么

在开始 RAG-v2-M2（本地语义检索）之前，必须再次确认以下事项：

### 12.1 安全边界未被破坏

- [ ] EvidenceChunk schema 仍有 `evidence_only: Literal[True]` 和 `extra="forbid"`。
- [ ] `manual_note_record_to_evidence_chunk()` 仍有 `evidence_only is not True` 入口检查。
- [ ] `evidence_chunk_to_document()` 仍不修改输入 chunk。
- [ ] `map_evidence_document()` 仍不将 `retrieval_score` 传入 `EvidenceCitation`。
- [ ] adapter / mapper 仍不导入 ranking_engine / simulation_service / prediction_calibration / recommendation_service。

### 12.2 链路完整性

- [ ] `ManualNoteRecord → EvidenceChunk → EvidenceDocumentRead → map_evidence_document → (RetrievedEvidence, EvidenceCitation)` 链路测试全通过。
- [ ] `test_evidence_chunk_schema.py` / `test_evidence_chunk_mapper.py` / `test_manual_note_chunk_adapter.py` / `test_evidence_document_mapper.py` 全通过。
- [ ] 全套 `app/tests -q` 无新增失败。

### 12.3 M2 设计前提

- [ ] M2 的检索服务（不是 adapter）负责计算 `retrieval_score`。
- [ ] M2 的 chunking service 负责将长文本切分为多个 EvidenceChunk（`chunk_index` / `chunk_count` > 1）。
- [ ] M2 的 embedding / vector store 不修改 EvidenceChunk schema。
- [ ] M2 不修改 `selected_player` / `final_score` / `prediction_sort_score`。
- [ ] M2 不修改 `evidence_service.py` / `ranking_engine.py` / `simulation_service.py` / `prediction_calibration.py` / `recommendation_service.py` 的决策逻辑。
- [ ] M2 的 `retrieval_score` 仅用于 `RetrievedEvidence`（LLM 解释排序），不进入 `EvidenceCitation`（前端展示）。

### 12.4 回归基线

- [ ] M2 开始前 `git log` 确认 HEAD 在 M1 验收 tag 上。
- [ ] M2 开始前 `git status --short` 确认 working tree clean。
- [ ] M2 开始前运行全套 smoke tests 确认基线绿色。

---

## 13. 快速 checklist

### 验收 checklist

```
[ ] git status --short 无输出（working tree clean）
[ ] git log 确认 HEAD 在 M1 验收 tag
[ ] pytest app/tests/test_evidence_chunk_schema.py -v        → 38 passed
[ ] pytest app/tests/test_evidence_chunk_mapper.py -v        → 29 passed
[ ] pytest app/tests/test_manual_note_chunk_adapter.py -v    → 50 passed
[ ] pytest app/tests/test_evidence_document_mapper.py -v     → 21 passed
[ ] pytest app/tests -q                                      → 1096 passed
[ ] EvidenceChunk.evidence_only == Literal[True]
[ ] EvidenceChunk.extra == "forbid"
[ ] manual_note_record_to_evidence_chunk 拒绝 evidence_only=False / None
[ ] manual_note_record_to_evidence_chunk 不生成 retrieval_score
[ ] adapter / mapper 不导入 DB / LLM / ranking_engine
[ ] adapter / mapper 不修改输入
[ ] retrieval_score 不进入 EvidenceCitation
[ ] 不影响 selected_player / final_score / prediction_sort_score
```

### 安全边界 checklist

```
[ ] 无新增 DB model
[ ] 无新增 API / router
[ ] 无 frontend 改动
[ ] 无 embedding
[ ] 无 vector store
[ ] 无 semantic retrieval
[ ] 未接 /api/evidence/pick
[ ] 未调用 ranking_engine
[ ] 未调用 simulation_service
[ ] 未调用 prediction_calibration
[ ] 未调用 recommendation_service
[ ] 未影响 selected_player
[ ] 未影响 final_score
[ ] 未影响 prediction_sort_score
```

### M2 前置 checklist

```
[ ] M1 smoke tests 全绿
[ ] EvidenceChunk schema 未被修改
[ ] evidence_chunk_to_document 未被修改
[ ] manual_note_record_to_evidence_chunk 未被修改
[ ] map_evidence_document 未被修改
[ ] retrieval_score 仍不进入 EvidenceCitation
[ ] evidence_only 仍为 Literal[True]
[ ] extra 仍为 "forbid"
[ ] working tree clean
[ ] HEAD 在 M1 验收 tag
```

---

## 附录：文件索引

| 文件 | 里程碑 | 说明 |
|---|---|---|
| `backend/app/schemas/evidence.py` | M1-B | EvidenceChunk schema 定义 |
| `backend/app/services/evidence_chunk_mapper.py` | M1-B | `evidence_chunk_to_document()` |
| `backend/app/services/manual_note_chunk_adapter.py` | M1-D | `manual_note_record_to_evidence_chunk()` |
| `backend/app/services/evidence_document_mapper.py` | RAG-v1-B1 | `map_evidence_document()`（既有，M1 未修改） |
| `backend/app/services/manual_note_evidence_adapter.py` | RAG-v1-B3 | `manual_note_record_to_evidence_document()`（既有，M1 未修改） |
| `backend/app/models/manual_note.py` | RAG-v1-B2 | ManualNoteRecord DB model（既有，M1 未修改） |
| `backend/app/tests/test_evidence_chunk_schema.py` | M1-B | EvidenceChunk schema 测试（38 项） |
| `backend/app/tests/test_evidence_chunk_mapper.py` | M1-B | evidence_chunk_to_document 测试（29 项） |
| `backend/app/tests/test_manual_note_chunk_adapter.py` | M1-D | manual_note_record_to_evidence_chunk 测试（50 项） |
| `backend/app/tests/test_evidence_document_mapper.py` | RAG-v1-B1 | map_evidence_document 测试（21 项，回归） |
| `docs/rag-v2-contract.md` | M0 | RAG-v2 合同锁定文档 |
| `docs/rag-v1-runbook.md` | R1 | RAG-v1 验收 runbook |
