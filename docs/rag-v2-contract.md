# RAG-v2 Contract Lock (M0)

> 本文档是 RAG-v2 的合同锁定文档（Milestone 0）。
> RAG-v2 在 RAG-v1 的基础上引入语义检索（chunking / embedding / vector store / multi-source），
> 但严格保持 RAG-v1 已确立的安全边界：retrieval 结果只能进入 explanation/evidence 链路，
> 不能影响 selected_player / final_score / prediction_sort_score。
>
> 本文档不包含业务代码，仅作为 RAG-v2 后续里程碑（M1/M2/M3）的设计合同。
> 任何偏离本文档的实现都需要先更新合同并重新评审。

---

## 1. RAG-v2 的目标

RAG-v2 的目标是：让 DraftMind 的证据链路支持更像真正 RAG 的语义检索。

```text
RAG-v1：ManualNote 按精确字段（prospect_id / team_id / pick_no）匹配
RAG-v2：EvidenceChunk 按 embedding 语义相似度匹配，支持多知识源
```

核心目标：

1. **语义检索**：用 embedding + vector store 替代精确字段匹配，提升召回率
2. **多知识源**：把 ManualNote 抽象为 KnowledgeSource 接口，未来可接入 news / scouting_report / stats
3. **chunking**：长文档切分为 EvidenceChunk，支持细粒度检索
4. **安全边界不变**：retrieval 结果仍然只能进入 `retrieved_evidence` / `citations`，不能影响决策

白话目标：

```text
证据能更智能地被找到（语义匹配，而非精确字段匹配）
证据能给用户看
证据能给 LLM 看
但证据仍然不能选人、不能改分、不能重排、不能推荐替代球员
```

---

## 2. RAG-v2 和 RAG-v1 的区别

| 维度 | RAG-v1 | RAG-v2 |
|---|---|---|
| 知识源 | 仅 ManualNote | ManualNote + 未来可扩展（news / scouting_report / stats） |
| 检索方式 | 精确字段匹配（prospect_id / team_id / pick_no） | 语义相似度检索（embedding + vector store） |
| 数据粒度 | 整条 ManualNoteRecord | EvidenceChunk（切分后的片段） |
| 存储 | SQLite `manual_notes` 表 | SQLite + vector store（FAISS / Chroma） |
| 召回率 | 低（仅匹配精确字段） | 高（语义相似度） |
| retrieval_score | 无 | 有（cosine similarity / dot product），但 **不参与决策** |
| 安全边界 | retrieval 只进 retrieved_evidence / citations | **完全相同** |
| LLM payload | 白名单 payload（D3-B） | **完全相同**，新增 chunk 字段也走白名单 |
| frontend | 只读展示 manual_note badge | **完全相同**，新增 semantic evidence 也只读展示 |
| config flag | `evidence_retrieve_manual_notes` | 新增 `evidence_retrieve_semantic` 等（见第 14 节） |

**不变项**（RAG-v2 必须保持）：

```text
selected_player 不变
final_score 不变
prediction_sort_score 不变
ranking_engine 不被 retrieval 调用
simulation_service 不被 retrieval 调用
prediction_calibration 不被 retrieval 调用
LLM 只能解释 locked pick
LLM 不能推荐替代球员
LLM 不能重排
LLM 不能改分
```

---

## 3. RAG-v2 不做什么

```text
不做：retrieval 参与选人
不做：retrieval 参与评分
不做：retrieval 参与排序
不做：retrieval 调用 ranking_engine
不做：retrieval 调用 simulation_service
不做：retrieval 调用 prediction_calibration
不做：retrieval 修改 selected_player
不做：retrieval 修改 final_score
不做：retrieval 修改 prediction_sort_score
不做：LLM 推荐替代球员
不做：LLM 重排候选
不做：LLM 改分
不做：frontend 写入 EvidenceChunk
不做：frontend 写入 KnowledgeSource
不做：frontend 控制 retrieval 开关
不做：API request body 控制 retrieval 开关
不做：real LLM provider 接入（M0 阶段）
不做：生产级 vector store 部署（M2 用本地 FAISS / Chroma）
不做：online embedding service 依赖（M2 用本地 sentence-transformers）
```

---

## 4. EvidenceChunk 的建议字段

EvidenceChunk 是 RAG-v2 的核心数据单元，表示从 KnowledgeSource 切分出的一个片段。

```python
# 建议字段（M1 阶段实现，M0 仅锁定合同）

class EvidenceChunk:
    # 身份
    chunk_id: str              # 全局唯一，格式 "{source_type}:{source_id}:{chunk_index}"
    source_type: str           # "manual_note" / "news" / "scouting_report" / "stats"
    source_id: str             # 源记录 ID（如 ManualNoteRecord.id）

    # 内容
    title: str | None          # 片段标题（可选，通常继承自源记录）
    content: str               # 片段正文（切分后的文本）
    chunk_index: int           # 在源记录中的切分序号（从 0 开始）
    chunk_count: int           # 源记录总切分数

    # 语义
    embedding: list[float] | None  # 向量（M2 阶段填充，M1 可为 None）
    embedding_model: str | None    # embedding 模型标识（如 "all-MiniLM-L6-v2"）
    embedding_dim: int | None      # 向量维度

    # 检索元数据
    retrieval_score: float | None  # 检索相似度分数（0.0-1.0，仅用于排序，不参与决策）
    source_rank: int | None        # 在同源记录中的排序

    # 安全标记
    evidence_only: Literal[True]   # 硬锁，EvidenceChunk 永远是 evidence-only
    entity_type: str | None        # "prospect" / "team" / "pick" / "prospect_team"
    entity_id: int | None          # 关联实体 ID
    year: int | None               # 关联年份

    # 来源元数据
    author: str | None
    source_date: str | None
    source_url: str | None
    tags: list[str]                # 标签列表

    # 审计
    created_at: datetime
    updated_at: datetime
```

**安全约束**：

- `evidence_only: Literal[True]` — 硬锁，EvidenceChunk 永远不能参与决策
- `retrieval_score` — 仅用于检索结果排序，不能传播到任何决策字段
- `embedding` — 仅用于向量检索，不进入 LLM payload（见第 10 节）
- `content` — 进入 LLM payload 时需截断（继承 D3-B 的 `LLM_EXCERPT_MAX_CHARS` 策略）

---

## 5. KnowledgeSource 的最小接口建议

KnowledgeSource 是 RAG-v2 的知识源抽象接口，让 ManualNote / News / ScoutingReport 等都能统一接入 retrieval 链路。

```python
# 建议接口（M1/M2 阶段实现，M0 仅锁定合同）

from typing import Protocol


class KnowledgeSource(Protocol):
    """知识源最小接口。

    每个知识源负责：
    1. 从自身存储读取原始记录
    2. 切分为 EvidenceChunk
    3. 提供 chunk 给 retrieval service 检索

    知识源不负责：
    - embedding 计算（由 EmbeddingService 统一处理）
    - vector store 写入（由 VectorStoreService 统一处理）
    - retrieval 排序（由 SemanticRetrievalService 统一处理）
    - 任何决策逻辑
    """

    @property
    def source_type(self) -> str:
        """知识源类型标识，如 'manual_note' / 'news' / 'scouting_report'。"""
        ...

    def list_chunks(
        self,
        *,
        year: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        limit: int = 50,
    ) -> list[EvidenceChunk]:
        """列出符合条件的 chunk（不含 embedding，用于精确过滤预筛）。"""
        ...

    def get_chunk(self, chunk_id: str) -> EvidenceChunk | None:
        """按 chunk_id 获取单个 chunk（含 embedding，用于 vector store 回填）。"""
        ...

    def count_chunks(
        self,
        *,
        year: int | None = None,
    ) -> int:
        """统计 chunk 数量（用于 smoke test / 监控）。"""
        ...
```

**设计原则**：

1. KnowledgeSource 是 **只读接口** — 不提供 create / update / delete（写入仍由各自的 service / script 处理）
2. KnowledgeSource **不调用** ranking_engine / simulation_service / prediction_calibration
3. KnowledgeSource **不调用** LLM
4. KnowledgeSource **不持有** DB session（由调用方注入）
5. `list_chunks` 返回的 chunk **不含 embedding**（避免大向量传输，embedding 由 vector store 按需回填）

---

## 6. Embedding / vector store 何时引入

| 里程碑 | 引入内容 | 说明 |
|---|---|---|
| M0 | 无 | 仅锁定合同，不引入任何依赖 |
| M1 | 无 | EvidenceChunk 数据结构 + KnowledgeSource 接口 + ManualNote chunking，embedding 字段为 None |
| M2 | embedding + local vector store | 引入 `sentence-transformers`（本地，all-MiniLM-L6-v2）+ FAISS（本地，内存或文件） |
| M3 | multi-source + 优化 | 多知识源接入 + vector store 持久化 + retrieval 调优 |

**M2 阶段的技术选型约束**：

```text
embedding model: sentence-transformers/all-MiniLM-L6-v2（本地，384 维，CPU 可跑）
vector store: FAISS（本地，IndexFlatIP 或 IndexIVFFlat）
不依赖: OpenAI embedding API / Pinecone / Weaviate / 任何云服务
不依赖: GPU
```

**何时考虑生产级 vector store**：

- 当 chunk 数量 > 100,000 时（FAISS 内存压力）
- 当需要多机部署时（FAISS 单机限制）
- 当需要实时增量索引时（FAISS 批量重建成本高）

在 RAG-v2 范围内（M0-M3），坚持本地 FAISS + sentence-transformers，不引入云依赖。

---

## 7. retrieval_score 的安全边界

`retrieval_score` 是 RAG-v2 新增的字段，表示 semantic retrieval 的相似度分数。

### 允许的用途

```text
retrieval_score 可用于：检索结果排序（按分数降序）
retrieval_score 可用于：检索结果过滤（低于阈值的丢弃）
retrieval_score 可用于：日志记录（attached_count / top_score）
retrieval_score 可用于：frontend 只读展示（"匹配度 87%"）
```

### 禁止的用途

```text
retrieval_score 不能影响 selected_player
retrieval_score 不能影响 final_score
retrieval_score 不能影响 prediction_sort_score
retrieval_score 不能影响 ranking_evidence
retrieval_score 不能影响 market_evidence
retrieval_score 不能影响 risk_evidence
retrieval_score 不能作为 ranking_engine 的输入
retrieval_score 不能作为 simulation_service 的输入
retrieval_score 不能作为 prediction_calibration 的输入
retrieval_score 不能作为 LLM 的决策指令
```

### Schema 层保护

```text
RetrievedEvidence.retrieval_score: float | None  # 可选，仅展示用
EvidenceCitation: 不含 retrieval_score（citation 不需要分数）
PickExplanation: extra="forbid"（LLM 输出不能含 retrieval_score 作为决策字段）
```

### LLM payload 保护

`retrieval_score` **不进入** LLM payload（即使 `RetrievedEvidence` 有此字段，`_build_llm_explanation_payload` 的白名单也不包含它）。理由：LLM 不需要知道检索分数，避免 LLM 把高分 chunk 当作"更重要"的决策依据。

---

## 8. semantic evidence 可以进入哪些字段

semantic retrieval 的结果（EvidenceChunk）只能 append 到以下字段：

```text
PickEvidencePackage.retrieved_evidence  ← EvidenceChunk 映射为 RetrievedEvidence
PickEvidencePackage.citations           ← EvidenceChunk 映射为 EvidenceCitation
```

### 映射规则

```text
EvidenceChunk.source_type      → RetrievedEvidence.source_type
EvidenceChunk.source_id        → RetrievedEvidence.source_id
EvidenceChunk.entity_type      → RetrievedEvidence.entity_type
EvidenceChunk.title            → RetrievedEvidence.title
EvidenceChunk.content          → RetrievedEvidence.excerpt（截断到 LLM_EXCERPT_MAX_CHARS）
EvidenceChunk.source_url       → RetrievedEvidence.url
EvidenceChunk.source_date      → RetrievedEvidence.date
EvidenceChunk.evidence_only    → RetrievedEvidence.evidence_only（Literal[True]）
EvidenceChunk.relevance_reason → RetrievedEvidence.relevance_reason（由 retrieval service 生成）
EvidenceChunk.retrieval_score  → RetrievedEvidence.retrieval_score（仅展示，不进 LLM payload）
```

### 新增 source_type 值

RAG-v2 可能引入新的 `source_type`：

```text
"manual_note"       ← RAG-v1 已有
"semantic_chunk"    ← RAG-v2 新增（泛化语义检索结果）
"news_chunk"        ← M3 阶段（News 知识源）
"scouting_chunk"    ← M3 阶段（ScoutingReport 知识源）
```

---

## 9. semantic evidence 禁止进入哪些字段

```text
禁止进入：selected_player_id / selected_player_name
禁止进入：ranking_evidence.final_score
禁止进入：ranking_evidence.prediction_sort_score
禁止进入：ranking_evidence.rank_in_available_pool
禁止进入：ranking_evidence.score_gap_to_next / score_gap_to_previous
禁止进入：ranking_evidence.confidence_band
禁止进入：ranking_evidence.primary_score_drivers
禁止进入：team_fit_evidence（整体）
禁止进入：market_evidence（整体）
禁止进入：risk_evidence（整体）
禁止进入：conflict_evidence（整体）
禁止进入：evidence_sufficiency（整体）
禁止进入：decision_locked / decision_source / llm_can_modify_decision
```

**测试要求**：每个里程碑都必须有测试断言 semantic evidence 不进入上述字段。

---

## 10. LLM 能看哪些 semantic evidence 字段

LLM payload（`_build_llm_explanation_payload`）的白名单对 semantic evidence 的处理：

```text
允许进入 LLM payload：
  source_type        ← 让 LLM 知道证据类型
  source_id          ← 让 LLM 引用
  entity_type        ← 让 LLM 知道证据关联的实体类型
  title              ← 让 LLM 引用标题
  excerpt            ← 截断后的内容（LLM_EXCERPT_MAX_CHARS=500）
  url                ← 让 LLM 引用来源链接
  date               ← 让 LLM 引用日期
  confidence         ← 让 LLM 知道证据可信度
  relevance_reason   ← 让 LLM 知道为什么这条证据相关
  evidence_only      ← 让 LLM 知道这是 evidence-only（prompt contract 已强化）
```

---

## 11. LLM 默认不能看哪些字段

```text
禁止进入 LLM payload：
  retrieval_score      ← 避免 LLM 把高分 chunk 当决策依据
  embedding            ← 向量本身对 LLM 无意义，且占用 token
  embedding_model      ← 内部元数据
  embedding_dim        ← 内部元数据
  chunk_index          ← 内部切分元数据
  chunk_count          ← 内部切分元数据
  source_rank          ← 内部排序元数据
  entity_id            ← 内部 ID
  freshness_days       ← 内部元数据
  conflict_note        ← 顶层 conflict_evidence 已覆盖
  citation（嵌套）      ← 与顶层 citations 冗余
  created_at           ← 内部时间戳
  updated_at           ← 内部时间戳
  tags                 ← 可能泄露内部分类逻辑（M3 阶段再评估是否开放）
```

**原则**：LLM 只看"解释需要的字段"，不看"检索/运维内部字段"。

---

## 12. frontend 可以展示什么

frontend 对 semantic evidence 的展示继承 RAG-v1 D2-A 的只读模式：

```text
可以展示：
  source_type badge（如 "语义证据" / "新闻片段" / "球探报告片段"）
  evidence-only badge（"仅用于解释"）
  persisted badge（"已持久化"）
  title
  excerpt（截断后的内容）
  source_id（参考编号）
  entity_type label（球员备注 / 球队备注 / 顺位备注）
  author
  date
  confidence（可信度百分比）
  relevance_reason（相关性说明）
  retrieval_score（匹配度百分比，只读展示）
  "不参与选人" 安全提示
```

---

## 13. frontend 禁止展示或禁止操作什么

```text
禁止展示：
  embedding 向量
  embedding_model / embedding_dim
  chunk_index / chunk_count
  created_at / updated_at（内部时间戳）
  任何暗示"影响决策"的文案

禁止操作：
  编辑 chunk
  删除 chunk
  创建 chunk
  保存 chunk
  应用到推荐
  调整分数
  替换球员
  重新排序
  控制 retrieval 开关
  修改 retrieval_score
  修改 embedding
```

frontend 必须保持完全只读，与 RAG-v1 D2-A 一致。

---

## 14. config flag 建议

RAG-v2 新增以下 config flag（均默认 **False**）：

```python
# RAG-v2-M1: EvidenceChunk foundation
evidence_chunk_enabled: bool = False
# 当 True 时，ManualNote 被 chunking 后存入 evidence_chunks 表
# 当 False 时，仍使用 RAG-v1 的整条 ManualNoteRecord 检索

# RAG-v2-M2: Local semantic retrieval
evidence_retrieve_semantic: bool = False
# 当 True 时，retrieval 使用 embedding + vector store（FAISS）
# 当 False 时，仍使用 RAG-v1 的精确字段匹配
# 依赖 evidence_chunk_enabled=True

evidence_embedding_model: str = "all-MiniLM-L6-v2"
# embedding 模型标识（M2 阶段仅支持 all-MiniLM-L6-v2）

evidence_vector_store_path: str = "data/vector_store"
# FAISS 索引文件路径（本地）

evidence_semantic_top_k: int = 5
# 语义检索返回的 top-K 结果数（默认 5，与 RAG-v1 PERSISTED_MANUAL_NOTE_LIMIT 一致）

evidence_semantic_min_score: float = 0.3
# 语义检索最低相似度阈值（低于此分数的结果被丢弃）

# RAG-v2-M3: Multi-source retrieval
evidence_multi_source_enabled: bool = False
# 当 True 时，retrieval 从多个 KnowledgeSource 聚合结果
# 当 False 时，仅从 ManualNote 检索
```

**安全约束**：

- 所有 flag 默认 **False**，确保 RAG-v2 功能不影响 RAG-v1 已有行为
- flag 只能由服务端 config 控制，**不暴露**给 API schema / frontend
- flag 之间有依赖关系：`evidence_retrieve_semantic=True` 要求 `evidence_chunk_enabled=True`
- `evidence_retrieve_manual_notes`（RAG-v1）保留，与 `evidence_retrieve_semantic` 独立

---

## 15. migration / seed / smoke test 建议

### Migration

```text
M1 阶段：
  - 新增 evidence_chunks 表（Alembic migration）
  - 字段见第 4 节 EvidenceChunk 建议
  - 不修改 manual_notes 表（向后兼容）

M2 阶段：
  - 新增 vector_store 索引文件（FAISS，非 DB migration）
  - 新增 embedding_cache 表（可选，缓存 embedding 避免重复计算）

M3 阶段：
  - 不新增表（多知识源复用现有 news / scouting_reports 表）
```

### Seed

```text
M1 阶段：
  - 新增 scripts/seed_evidence_chunks.py（dev-only）
  - 从 manual_notes 表读取记录，chunking 后写入 evidence_chunks 表
  - idempotent，dedup by (source_type, source_id, chunk_index)
  - 不删除/不覆盖 custom chunks

M2 阶段：
  - 新增 scripts/build_vector_index.py（dev-only）
  - 从 evidence_chunks 表读取 chunk，计算 embedding，写入 FAISS 索引
  - idempotent，每次重建索引
```

### Smoke test

```text
每个里程碑（M1/M2/M3）必须包含：

1. chunking 正确性测试
   - 长文档被正确切分
   - chunk_index 连续
   - chunk_count 正确

2. retrieval 安全边界测试
   - semantic evidence 只进入 retrieved_evidence / citations
   - semantic evidence 不进入 selected_player / final_score / prediction_sort_score
   - retrieval 不调用 ranking_engine / simulation_service / prediction_calibration

3. LLM payload 安全测试
   - retrieval_score 不进入 LLM payload
   - embedding 不进入 LLM payload
   - chunk_index / chunk_count 不进入 LLM payload
   - long content 被截断

4. fallback 测试
   - vector store 失败 → fallback 到 RAG-v1 精确匹配
   - embedding 失败 → fallback 到 RAG-v1 精确匹配
   - 任何异常 → evidence package 仍正常构建

5. config flag 测试
   - flag=False 时行为与 RAG-v1 完全一致
   - flag=True 时启用 semantic retrieval
   - flag 依赖关系正确（semantic=True 但 chunk=False 时报错或降级）

6. frontend 只读测试
   - semantic evidence 在 UI 只读展示
   - 无写入交互
   - badge 文案正确（"语义证据" / "仅用于解释" / "不参与选人"）
```

---

## 16. RAG-v2 分阶段路线

### M0 Contract Lock（本轮）

```text
目标：锁定 RAG-v2 设计合同
产出：docs/rag-v2-contract.md（本文档）
不写代码：不新增 model / schema / service / router / API
不引入依赖：不接 vector store / embedding / chunking
验收：文档评审通过，tag rag-v2-m0-contract-lock
```

### M1 EvidenceChunk Foundation

```text
目标：建立 EvidenceChunk 数据结构 + KnowledgeSource 接口 + ManualNote chunking
允许修改：
  backend/app/models/evidence_chunk.py（新增）
  backend/app/schemas/evidence_chunk.py（新增）
  backend/app/services/knowledge_source.py（新增接口）
  backend/app/services/manual_note_knowledge_source.py（新增实现）
  backend/app/services/chunking_service.py（新增）
  backend/scripts/seed_evidence_chunks.py（新增 dev seed）
  backend/app/config.py（新增 evidence_chunk_enabled flag）
  backend/app/tests/test_evidence_chunk_*.py（新增测试）
不引入：embedding / vector store
embedding 字段：存在但为 None
retrieval 方式：仍为精确字段匹配（从 evidence_chunks 表读）
验收：
  - chunking 正确性测试通过
  - 安全边界测试通过
  - RAG-v1 全量回归通过
  - tag rag-v2-m1-evidence-chunk-foundation
```

### M2 Local Semantic Retrieval

```text
目标：引入 embedding + FAISS，实现语义检索
允许修改：
  backend/app/services/embedding_service.py（新增）
  backend/app/services/vector_store_service.py（新增）
  backend/app/services/semantic_retrieval_service.py（新增）
  backend/app/services/evidence_service.py（修改：接入 semantic retrieval）
  backend/app/routers/evidence.py（修改：config-gated semantic retrieval）
  backend/app/config.py（新增 semantic retrieval flags）
  backend/scripts/build_vector_index.py（新增 dev seed）
  backend/app/tests/test_semantic_retrieval_*.py（新增测试）
引入依赖：
  sentence-transformers（本地 embedding）
  faiss-cpu（本地 vector store）
不引入：云 embedding API / 云 vector store
retrieval_score：存在但不参与决策
fallback：vector store / embedding 失败时降级到 RAG-v1 精确匹配
验收：
  - 语义检索召回率 > RAG-v1 精确匹配
  - 安全边界测试通过
  - fallback 测试通过
  - RAG-v1 全量回归通过
  - tag rag-v2-m2-local-semantic-retrieval
```

### M3 Multi-source Retrieval + UI/LLM polish

```text
目标：多知识源接入 + frontend 展示增强 + LLM prompt 优化
允许修改：
  backend/app/services/news_knowledge_source.py（新增）
  backend/app/services/scouting_knowledge_source.py（新增）
  backend/app/services/knowledge_source_registry.py（新增）
  backend/app/services/evidence_service.py（修改：多源聚合）
  backend/app/services/evidence_llm_explanation_service.py（修改：payload 适配）
  backend/app/services/evidence_prompt_contract.py（修改：semantic evidence 规则）
  frontend/app/draft/page.tsx（修改：semantic evidence 展示）
  backend/app/config.py（新增 multi_source flag）
  backend/app/tests/test_multi_source_*.py（新增测试）
不引入：新的 vector store / embedding model
验收：
  - 多知识源检索正确
  - frontend 展示 semantic evidence 只读
  - LLM payload 安全
  - 全量回归通过
  - tag rag-v2-m3-multi-source-retrieval
```

---

## 17. 允许修改文件清单

### M0（本轮）

```text
docs/rag-v2-contract.md（新增，本文档）
```

### M1

```text
backend/app/models/evidence_chunk.py（新增）
backend/app/models/__init__.py（修改：注册 EvidenceChunk）
backend/app/schemas/evidence_chunk.py（新增）
backend/app/schemas/__init__.py（修改：导出 EvidenceChunk schema）
backend/app/services/knowledge_source.py（新增接口）
backend/app/services/manual_note_knowledge_source.py（新增实现）
backend/app/services/chunking_service.py（新增）
backend/app/config.py（修改：新增 evidence_chunk_enabled flag）
backend/scripts/seed_evidence_chunks.py（新增 dev seed）
backend/app/tests/test_evidence_chunk_model.py（新增）
backend/app/tests/test_evidence_chunk_schema.py（新增）
backend/app/tests/test_chunking_service.py（新增）
backend/app/tests/test_manual_note_knowledge_source.py（新增）
backend/app/tests/test_seed_evidence_chunks.py（新增）
backend/app/tests/test_evidence_service_chunk_retrieval.py（新增）
```

### M2

```text
backend/app/services/embedding_service.py（新增）
backend/app/services/vector_store_service.py（新增）
backend/app/services/semantic_retrieval_service.py（新增）
backend/app/services/evidence_service.py（修改：接入 semantic retrieval）
backend/app/routers/evidence.py（修改：config-gated semantic retrieval）
backend/app/config.py（修改：新增 semantic retrieval flags）
backend/scripts/build_vector_index.py（新增 dev seed）
backend/app/tests/test_embedding_service.py（新增）
backend/app/tests/test_vector_store_service.py（新增）
backend/app/tests/test_semantic_retrieval_service.py（新增）
backend/app/tests/test_evidence_service_semantic_retrieval.py（新增）
backend/app/tests/test_evidence_router_semantic_retrieval.py（新增）
backend/app/tests/test_evidence_llm_payload_semantic_safety.py（新增）
```

### M3

```text
backend/app/services/news_knowledge_source.py（新增）
backend/app/services/scouting_knowledge_source.py（新增）
backend/app/services/knowledge_source_registry.py（新增）
backend/app/services/evidence_service.py（修改：多源聚合）
backend/app/services/evidence_llm_explanation_service.py（修改：payload 适配）
backend/app/services/evidence_prompt_contract.py（修改：semantic evidence 规则）
backend/app/config.py（修改：新增 multi_source flag）
frontend/app/draft/page.tsx（修改：semantic evidence 展示）
frontend/lib/api.ts（修改：新增 semantic evidence 类型字段，可选）
backend/app/tests/test_news_knowledge_source.py（新增）
backend/app/tests/test_scouting_knowledge_source.py（新增）
backend/app/tests/test_knowledge_source_registry.py（新增）
backend/app/tests/test_evidence_service_multi_source.py（新增）
backend/app/tests/test_evidence_router_multi_source.py（新增）
```

---

## 18. 禁止修改文件清单

### 所有里程碑（M0-M3）禁止修改

```text
backend/app/services/ranking_engine.py
backend/app/services/simulation_service.py
backend/app/services/prediction_calibration.py
backend/app/services/recommendation_service.py
backend/app/services/team_need_service.py
backend/app/services/team_need_adjustment.py
backend/app/services/scouting_fit.py
```

### M0（本轮）额外禁止修改

```text
backend/app/models/*（不新增 model）
backend/app/schemas/*（不新增 schema）
backend/app/services/*（不新增 service）
backend/app/routers/*（不新增 router）
frontend/*（不改 frontend）
backend/app/config.py（不改 config）
任何 .py 文件（本轮仅新增 markdown 文档）
```

### 永久禁止（RAG-v2 任何阶段）

```text
禁止让 retrieval 调用 ranking_engine
禁止让 retrieval 调用 simulation_service
禁止让 retrieval 调用 prediction_calibration
禁止让 retrieval 修改 selected_player / final_score / prediction_sort_score
禁止让 LLM 推荐替代球员
禁止让 LLM 重排候选
禁止让 LLM 改分
禁止让 frontend 写入 EvidenceChunk / KnowledgeSource
禁止让 API request body 控制 retrieval 开关
禁止接云 embedding API（M2 用本地 sentence-transformers）
禁止接云 vector store（M2 用本地 FAISS）
禁止接 real LLM provider（保持 RAG-v1 的 LLM shell + fake client 测试模式）
```

---

## 19. 风险清单

### 高风险

1. **embedding 模型质量**：`all-MiniLM-L6-v2` 是轻量模型（384 维），对中文 / 专业篮球术语的语义理解可能不足。M2 阶段需评估召回质量，必要时升级到 `paraphrase-multilingual-MiniLM-L12-v2`（768 维，支持多语言）。

2. **vector store 持久化**：FAISS 索引文件在进程重启后需重新加载。M2 阶段需设计索引加载 / 重建策略，避免每次启动都重建（耗时）。

3. **chunking 质量影响检索质量**：切分粒度太粗（整条 note）→ 召回率低；切分太细（单句）→ 语义不完整。M1 阶段需实验确定最佳 chunk size（建议 200-500 字符，overlap 50 字符）。

### 中风险

4. **multi-source 聚合的 cap 策略**：RAG-v1 有 `PERSISTED_MANUAL_NOTE_LIMIT=5` 全局 cap。M3 多源检索时需设计跨源 cap 策略（如每源 top-2，全局 top-5），避免单一知识源占满 cap。

5. **embedding 计算性能**：`all-MiniLM-L6-v2` 在 CPU 上约 50ms/chunk。M2 阶段若 chunk 数量 > 1000，首次构建索引可能耗时 > 50s。需引入 embedding cache 表。

6. **config flag 依赖链**：`evidence_retrieve_semantic=True` 要求 `evidence_chunk_enabled=True`。若用户只开 semantic 不开 chunk，需 graceful 降级或明确报错。

### 低风险

7. **frontend 展示一致性**：semantic evidence 与 manual_note evidence 在 UI 上的视觉区分。M3 阶段需设计统一的 badge 体系。

8. **LLM prompt 膨胀**：semantic retrieval 可能返回更多 chunk，导致 LLM payload 变大。需严格控制 `evidence_semantic_top_k` 和 `LLM_EXCERPT_MAX_CHARS`。

9. **测试覆盖**：每个里程碑都需完整的 fallback / 安全边界 / 回归测试，测试数量可能显著增长。

---

## 20. 验收标准

### M0 验收标准（本轮）

```text
[ ] docs/rag-v2-contract.md 已创建
[ ] 文档包含全部 20 个章节
[ ] 安全边界明确写入（第 7/9/11/13 节）
[ ] 分阶段路线明确（第 16 节）
[ ] 允许/禁止修改文件清单明确（第 17/18 节）
[ ] 未修改任何业务代码
[ ] 未新增 model / schema / service / router / API
[ ] 未接 vector store / embedding / chunking
[ ] git working tree 仅新增 docs/rag-v2-contract.md
[ ] 未 commit / push / tag
```

### M1 验收标准

```text
[ ] EvidenceChunk model + schema 已实现
[ ] KnowledgeSource 接口 + ManualNoteKnowledgeSource 实现已完成
[ ] chunking_service 已实现，chunk size 合理
[ ] evidence_chunk_enabled flag 默认 False
[ ] flag=False 时 RAG-v1 行为完全不变
[ ] flag=True 时 ManualNote 被 chunking 并可检索
[ ] embedding 字段存在但为 None
[ ] 安全边界测试通过（chunk 不进入决策字段）
[ ] RAG-v1 全量回归通过
[ ] 新增测试覆盖 chunking / retrieval / 安全边界
```

### M2 验收标准

```text
[ ] embedding_service 已实现（sentence-transformers，本地）
[ ] vector_store_service 已实现（FAISS，本地）
[ ] semantic_retrieval_service 已实现
[ ] evidence_retrieve_semantic flag 默认 False
[ ] flag=False 时 RAG-v1 行为完全不变
[ ] flag=True 时使用语义检索
[ ] retrieval_score 存在但不进入决策字段
[ ] retrieval_score 不进入 LLM payload
[ ] embedding 不进入 LLM payload
[ ] fallback：vector store / embedding 失败时降级到 RAG-v1
[ ] 安全边界测试通过
[ ] RAG-v1 全量回归通过
[ ] 召回率 > RAG-v1 精确匹配（需人工评估）
```

### M3 验收标准

```text
[ ] NewsKnowledgeSource + ScoutingKnowledgeSource 已实现
[ ] knowledge_source_registry 已实现
[ ] evidence_multi_source_enabled flag 默认 False
[ ] flag=False 时 RAG-v2 M2 行为完全不变
[ ] flag=True 时多源聚合检索
[ ] 跨源 cap 策略正确
[ ] frontend 展示 semantic evidence 只读
[ ] frontend 无写入交互
[ ] LLM payload 安全（多源字段也走白名单）
[ ] 安全边界测试通过
[ ] RAG-v1 + RAG-v2 M1/M2 全量回归通过
```

### 永久验收标准（所有里程碑）

```text
[ ] retrieval 不调用 ranking_engine
[ ] retrieval 不调用 simulation_service
[ ] retrieval 不调用 prediction_calibration
[ ] retrieval 不修改 selected_player / final_score / prediction_sort_score
[ ] LLM 不推荐替代球员
[ ] LLM 不重排候选
[ ] LLM 不改分
[ ] frontend 完全只读
[ ] API request body 不控制 retrieval 开关
[ ] 所有 config flag 默认 False
[ ] fallback 到 deterministic mock / RAG-v1 行为正常
```

---

## 附录：核心安全边界速查

```text
=================================================================
retrieval_score 不能影响 selected_player
retrieval_score 不能影响 final_score
retrieval_score 不能影响 prediction_sort_score
semantic retrieval 不能调用 ranking_engine
semantic retrieval 不能调用 simulation_service
semantic retrieval 不能调用 prediction_calibration
semantic retrieval 只能 append 到 retrieved_evidence / citations
LLM 只能解释 locked pick
LLM 不能推荐替代球员
LLM 不能重排
LLM 不能改分
=================================================================
```
