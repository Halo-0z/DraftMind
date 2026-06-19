# Draft-day Demo Runbook

> RAG-v2 M2 里程碑闭环后的演示手册。用于在 NBA 选秀日前快速演示 DraftMind 的 RAG-v2 evidence 能力。
>
> 本文档只描述演示流程，不新增功能、不修改后端代码、不修改 frontend。

---

## 1. Demo 目标

本次 demo 要证明一件事：

```text
DraftMind 可以在不改变选人结果的前提下，把 manual notes / evidence 通过 RAG-v2 semantic retrieval 追加到 PickEvidencePackage。
```

必须强调的安全边界：

```text
RAG / Evidence / LLM 只解释，不选人。
ranking_engine / prediction_calibration / simulation_service 仍然是选人系统。
semantic retrieval 不能改变 selected_player / final_score / prediction_sort_score。
```

白话总结：**这不是"AI 替我选人"，而是"AI 帮我把为什么这么选讲清楚"。**

---

## 2. 当前能力范围

RAG-v2 M2 里程碑已全部闭环，当前已实现的能力：

```text
EvidenceChunk              — M1-B 证据块 schema（content / source_type / evidence_only 锁）
chunk_text                 — M2-B 证据切分（句子感知，离线纯 Python）
embed_chunks / embed_query — M2-C1 fake deterministic embedding（SHA-256 链，384 维，L2 归一化）
InMemoryVectorStore        — M2-D1 内存向量库（纯 Python dot product，deepcopy 隔离）
retrieve_semantic          — M2-D2 语义检索服务（query → vector → search → evidence/citation）
evidence_service wiring    — M2-E config-gated 接入（默认关闭，开启后追加 evidence）
retrieval_score isolation  — retrieval_score 进 RetrievedEvidence，不进 Citation / LLM payload / 索引 chunk
fallback                   — 任何 semantic 步骤失败都吞掉异常，回退旧逻辑
LLM payload whitelist      — _whitelist_retrieved_evidence 显式排除 retrieval_score 等内部元数据
```

---

## 3. Demo 前置条件

```text
操作系统:  Windows PowerShell
Python:   D:\anaconda\python.exe
Repo:     D:\DraftMind
Backend:  D:\DraftMind\backend
Git:      working tree clean
分支:     main 已同步 origin/main
```

确认方式：

```powershell
cd D:\DraftMind
git status --short        # 应为空
git branch -vv            # main 应跟踪 origin/main 且 up to date
```

---

## 4. Demo 前检查命令

```powershell
cd D:\DraftMind

git status --short
git log --oneline --decorate -10
git tag --list "rag-v2-*"
```

预期结果：

```text
HEAD 应在 422b264 或其后续提交
应包含 tag: rag-v2-m2e-config-gated-semantic-retrieval-acceptance
working tree 应为空（git status --short 无输出）
```

如果 `git status --short` 有输出，说明 working tree 不干净，请先参考第 13 节故障排查。

---

## 5. 如何确认 config 默认关闭

根据 `backend/app/config.py` 真实字段（L60-L72），semantic retrieval 配置如下：

```python
# ---- Semantic Retrieval (RAG-v2-M2-E) ----
evidence_retrieve_semantic: bool = False      # 默认关闭
evidence_semantic_top_k: int = 5              # 默认 top 5
evidence_semantic_min_score: float = 0.0      # 默认不过滤，便于 demo
```

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `evidence_retrieve_semantic` | `bool` | `False` | semantic retrieval 总开关，默认关闭 |
| `evidence_semantic_top_k` | `int` | `5` | 检索返回的 top K 条数 |
| `evidence_semantic_min_score` | `float` | `0.0` | 最低检索分数阈值，0.0 表示不过滤 |

环境变量配置方式：

项目使用 Pydantic Settings（`model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8")`）。按 Settings 字段名配置，具体环境变量命名以 Pydantic Settings 行为为准（通常为字段名大写，如 `EVIDENCE_RETRIEVE_SEMANTIC=true`）。如需开启 semantic retrieval，可在 `backend/` 上级目录的 `.env` 文件中设置对应环境变量。

demo 时如果不改 `.env`，默认就是关闭路径，可以直接跑路线 A。

---

## 6. Demo 路线 A：默认关闭路径

**要证明**：关闭 semantic retrieval 时，旧 evidence pipeline 完全不受影响。

```text
旧 evidence pipeline 不受影响
不会调用 semantic retrieval
不会调用 embed / vector store
不会改变 PickEvidencePackage 输出
```

测试命令：

```powershell
cd D:\DraftMind\backend

D:\anaconda\python.exe -m pytest app/tests/test_evidence_service_semantic_retrieval.py -v
```

重点测试名称（应全部 PASSED）：

```text
test_config_default_evidence_retrieve_semantic_is_false
test_semantic_flag_false_produces_same_output_as_old_logic
test_semantic_flag_false_does_not_call_embed_chunks
test_semantic_flag_false_does_not_call_retrieve_semantic
test_semantic_flag_false_does_not_call_vector_store
```

讲解要点：

- `evidence_retrieve_semantic` 默认 `False`，`_append_semantic_retrieval_evidence()` 第一行就 return
- `embed_chunks` / `InMemoryVectorStore` / `retrieve_semantic` 都不会被调用
- `PickEvidencePackage` 输出与 M2-D2 完全一致

---

## 7. Demo 路线 B：开启 semantic retrieval 路径

**要证明**：开启 semantic retrieval 后，manual notes 会经过完整 RAG-v2 链路追加到 evidence package。

```text
manual notes / evidence 会变成 EvidenceChunk
chunk 会 embed
InMemoryVectorStore 会 build_index
retrieve_semantic 会返回 RetrievedEvidence / EvidenceCitation
结果会追加到 PickEvidencePackage.retrieved_evidence / citations
```

测试命令：

```powershell
cd D:\DraftMind\backend

D:\anaconda\python.exe -m pytest app/tests/test_evidence_service_semantic_retrieval.py -v
D:\anaconda\python.exe -m pytest app/tests/test_semantic_retrieval_service.py -v
```

重点测试名称（应全部 PASSED）：

```text
test_semantic_flag_true_appends_retrieved_evidence
test_semantic_flag_true_appends_evidence_citation
test_semantic_flag_true_calls_retrieve_semantic
test_semantic_flag_true_calls_embed_chunks
test_full_semantic_pipeline_appends_evidence
test_full_semantic_pipeline_does_not_crash_with_many_notes
test_semantic_retrieval_respects_top_k_config
test_semantic_retrieval_respects_min_score_config
```

讲解要点：

- 测试通过 monkeypatch `get_settings()` 返回 `evidence_retrieve_semantic=True` 来模拟开启
- manual notes 的 `title + summary + body` 被 `chunk_text()` 切成 `EvidenceChunk`
- `embed_chunks()` 用 fake deterministic embedding 生成 384 维向量
- `InMemoryVectorStore.build_index()` 建内存索引
- `retrieve_semantic()` 用 query_text 检索，返回 `(RetrievedEvidence, EvidenceCitation)` 对
- 结果通过 `extend()` 追加到 `retrieved_evidence` / `citations`，不替换已有条目

---

## 8. Demo 路线 C：安全隔离路径

**要证明**：`retrieval_score` 的安全隔离边界完整。

```text
retrieval_score 可以存在于 RetrievedEvidence（用于排序）
retrieval_score 不进入 EvidenceCitation（前端展示）
retrieval_score 不进入 LLM payload（不让 LLM 看到分数）
retrieval_score 不写回 indexed EvidenceChunk（不污染索引）
retrieval_score 不进入 EmbeddingVector（schema 无此字段）
```

测试命令：

```powershell
cd D:\DraftMind\backend

D:\anaconda\python.exe -m pytest app/tests/test_evidence_llm_payload_safety.py -v
D:\anaconda\python.exe -m pytest app/tests/test_semantic_retrieval_service.py -v
```

重点测试名称（应全部 PASSED）：

```text
test_retrieval_score_present_in_retrieved_evidence
test_retrieval_score_not_in_evidence_citation
test_retrieval_score_not_in_llm_payload
test_semantic_retrieval_score_excluded_from_llm_payload
test_semantic_retrieval_score_excluded_from_llm_user_message
test_retrieval_score_not_written_back_to_indexed_chunk
test_retrieval_score_not_in_embedding_vector_schema
test_retrieval_score_not_in_llm_payload_whitelist
```

讲解要点：

- 三层防御：schema 层（`EvidenceCitation` 无 `retrieval_score` 字段）+ mapper 层（不传播）+ whitelist 层（`_whitelist_retrieved_evidence` 显式排除）
- `get_chunk()` 返回 deepcopy，`retrieval_score` 设在 disposable copy 上，不写回索引
- LLM payload whitelist 确保LLM 永远看不到 `retrieval_score`，避免被误读为排名/评分信号

---

## 9. Demo 路线 D：选人不变路径

**要证明**：semantic retrieval 不能修改任何选人决策字段，不能调用选人系统。

```text
semantic retrieval 不能修改 selected_player
不能修改 final_score
不能修改 prediction_sort_score
不能调用 ranking_engine
不能调用 simulation_service
不能调用 prediction_calibration
```

测试命令：

```powershell
cd D:\DraftMind\backend

D:\anaconda\python.exe -m pytest app/tests/test_evidence_service_semantic_retrieval.py -v
D:\anaconda\python.exe -m pytest app/tests/test_knowledge_source_boundary.py -v
```

重点测试名称（应全部 PASSED）：

```text
test_semantic_retrieval_does_not_modify_selected_player
test_semantic_retrieval_does_not_modify_final_score
test_semantic_retrieval_does_not_modify_prediction_sort_score
test_semantic_wiring_does_not_call_ranking_engine
test_semantic_wiring_does_not_call_simulation_service
test_semantic_wiring_does_not_call_prediction_calibration
```

边界测试（`test_knowledge_source_boundary.py`）：

```text
test_selection_system_modules_do_not_import_knowledge_sources
test_semantic_retrieval_service_does_not_import_selection_system
test_semantic_retrieval_service_does_not_import_db_or_llm_or_ml_libs
```

讲解要点：

- semantic retrieval 只 `extend` 到 `retrieved_evidence` / `citations`，不触碰 `PickEvidencePackage` 的 decision/scoring 字段
- 测试通过 monkeypatch `ranking_engine.rank_prospects` 等为 `_fail` 函数，若被调用则 raise AssertionError
- 三层 import 边界：正向（选人系统不导入知识源 token）+ 反向（知识源不导入选人系统）+ 运行时（不调用）

---

## 10. Demo 路线 E：fallback 路径

**要证明**：semantic retrieval 任何步骤失败都不会让主流程失败。

```text
semantic retrieval 失败不会让主流程失败
chunk 失败会 fallback
embed 失败会 fallback
retrieve_semantic 失败会 fallback
semantic 返回空结果不会破坏旧逻辑
```

测试命令：

```powershell
cd D:\DraftMind\backend

D:\anaconda\python.exe -m pytest app/tests/test_evidence_service_semantic_retrieval.py -v
```

重点测试名称（应全部 PASSED）：

```text
test_semantic_retrieval_failure_falls_back_without_exception
test_semantic_retrieval_chunk_failure_falls_back
test_semantic_retrieval_embed_failure_falls_back
test_semantic_retrieval_empty_results_does_not_break_old_logic
test_no_manual_notes_skips_semantic_retrieval
```

讲解要点：

- 整个 semantic 管线包裹在 `try/except Exception` 中
- 失败时 log warning（只记 year/pick_no/exc_type/exc_msg，不记敏感 note content）
- semantic retrieval 不是主流程的硬依赖，失败后 evidence package 照常构建

---

## 11. 一键回归测试

完整命令（复制粘贴即可）：

```powershell
cd D:\DraftMind\backend

D:\anaconda\python.exe -m pytest app/tests/test_evidence_service_semantic_retrieval.py -v
D:\anaconda\python.exe -m pytest app/tests/test_evidence_llm_payload_safety.py -v
D:\anaconda\python.exe -m pytest app/tests/test_knowledge_source_boundary.py -v
D:\anaconda\python.exe -m pytest app/tests/test_semantic_retrieval_service.py -v
D:\anaconda\python.exe -m pytest app/tests/test_vector_store_service.py -v
D:\anaconda\python.exe -m pytest app/tests/test_embedding_service.py -v

D:\anaconda\python.exe -m pytest app/tests -q
```

当前预期：

```text
test_evidence_service_semantic_retrieval.py:  27 passed
test_evidence_llm_payload_safety.py:          47 passed
test_knowledge_source_boundary.py:            10 passed
test_semantic_retrieval_service.py:           32 passed
test_vector_store_service.py:                 40 passed
test_embedding_service.py:                    44 passed
全量 app/tests -q:                            1342 passed

warnings 可存在，目前 pytest 有已知 warnings（FastAPI on_event 弃用、datetime.utcnow 弃用等），不影响测试结果。
```

---

## 12. Demo 讲解词

以下是一段 1-2 分钟的中文 demo 讲解词，面向老师/面试官/项目评审：

> 大家好，这是 DraftMind，一个 NBA 选秀决策支持系统。
>
> 以前系统能选人，但证据检索比较死——只能按 entity_id 精确匹配 manual notes。
>
> 现在我们加了 RAG-v2，不让 AI 选人，只让它找证据和解释。具体来说，我们把 manual notes 切成证据块，用 embedding 把它们变成向量，建一个内存向量索引，然后用语义检索把最相关的证据找出来，追加到 evidence package 里。
>
> semantic retrieval 默认关闭，开了以后也只往 evidence package 里追加证据。真正选谁还是 ranking_engine 和 simulation_service 决定。retrieval_score 只用于证据排序，不会进入前端 citation，也不会进入 LLM payload，更不会改变 selected_player、final_score 或 prediction_sort_score。
>
> 如果 semantic retrieval 任何步骤失败，系统会自动 fallback 到旧逻辑，不会影响主流程。
>
> 所以这不是"AI 替我选人"，而是"AI 帮我把为什么这么选讲清楚"。谢谢。

---

## 13. 故障排查

### git working tree 不干净怎么办

```powershell
cd D:\DraftMind
git status --short
```

如果有未跟踪文件（如 `?? some-file.md`）：
- 如果是临时文件，可以删除
- 如果是 spec 文件（如 `Draft-day Demo Runbook.md`），可以保留，不影响 demo

如果有已修改文件（如 ` M backend/app/config.py`）：
- 先确认是否是自己的改动：`git diff backend/app/config.py`
- 如果不是预期改动，可以 stash：`git stash`
- demo 前应恢复 clean 状态

### pytest 失败怎么办

1. 确认 Python 环境：`D:\anaconda\python.exe --version`（应为 3.12+）
2. 确认在正确目录：`cd D:\DraftMind\backend`
3. 确认依赖已安装：`pip install -e .`
4. 查看失败详情：`D:\anaconda\python.exe -m pytest app/tests/test_xxx.py -v --tb=long`
5. 如果是 import 错误，检查 `PYTHONPATH` 或重新 `pip install -e .`

### semantic retrieval 没结果怎么办

可能原因：
1. `evidence_retrieve_semantic` 未开启（默认 `False`）——这是预期行为，路线 A 就是证明关闭路径
2. 没有 manual notes ——`_append_semantic_retrieval_evidence` 会在 `if not manual_notes: return` 处跳过
3. `min_score` 过高——默认 `0.0` 不过滤，如果调高了可能过滤掉所有结果
4. fake embedding 的语义质量有限——这是 M2-C1 已知限制，真实召回质量要等 M2-C2 / M3

### retrieval_score 出现在 Citation / LLM payload 里怎么办

这是严重的安全边界违规，不应发生。如果出现：

1. 检查 `EvidenceCitation` schema 是否被意外修改（不应有 `retrieval_score` 字段）
2. 检查 `evidence_document_mapper.py` 的 `evidence_document_to_citation()` 是否被意外修改
3. 检查 `evidence_llm_explanation_service.py` 的 `_whitelist_retrieved_evidence()` 是否被意外修改
4. 运行安全隔离测试确认：
   ```powershell
   D:\anaconda\python.exe -m pytest app/tests/test_evidence_llm_payload_safety.py -v
   D:\anaconda\python.exe -m pytest app/tests/test_semantic_retrieval_service.py -v
   ```
5. 如果测试也失败了，说明边界被破坏，需要回溯到 `rag-v2-m2e-config-gated-semantic-retrieval-acceptance` tag 重新检查

### selected_player / final_score 变化怎么办

这也是严重的安全边界违规，不应发生。如果出现：

1. 检查 `evidence_service.py` 的 `_append_semantic_retrieval_evidence()` 是否只 `extend` 到 `retrieved_evidence` / `citations`
2. 确认没有代码把 semantic retrieval 结果写回 `selected_player` / `final_score` / `prediction_sort_score`
3. 运行选人不变测试确认：
   ```powershell
   D:\anaconda\python.exe -m pytest app/tests/test_evidence_service_semantic_retrieval.py -v -k "does_not_modify"
   ```
4. 如果测试也失败了，说明边界被破坏，需要回溯到 acceptance tag 重新检查

### GitHub push TLS 报错怎么办

之前项目中出现过临时 TLS EOF 错误。解决方式：

```powershell
git push origin HEAD:main
```

可以重试，通常重试 1-2 次即可成功。如果持续失败：

1. 检查网络连接
2. 检查 GitHub 状态页：https://www.githubstatus.com/
3. 尝试切换网络（如换热点）
4. 如果是 TLS 握手问题，可以尝试 `git config --global http.sslVersion tlsv1.2`（但不要随意改 git config，先确认问题）

---

## 14. Demo 边界

明确说明当前 demo 的局限性：

```text
当前还没有真实 embedding model
  → 使用的是 fake deterministic embedding（SHA-256 链，384 维）
  → 向量是伪随机分布，cosine similarity 无法真正区分语义
  → 这是 M2-C1 的已知限制

当前还是 fake deterministic embedding
  → 真实召回质量要等 M2-C2 / M3 再提升
  → demo 主要证明链路完整和安全边界，不证明召回质量

当前还没有 FAISS / persistent vector DB
  → 使用的是 InMemoryVectorStore（纯 Python dot product）
  → 每次调用都重建索引，没有缓存
  → demo 数据量（少量 manual notes）性能可接受

当前 semantic retrieval 主要证明链路和安全边界
  → config-gated 默认关闭
  → 开启后只追加 evidence，不改变选人
  → 失败可 fallback
  → retrieval_score 安全隔离

真实召回质量要等 M2-C2 / M3 再提升
  → M2-C2: 接入真实 embedding model（如 sentence-transformers/all-MiniLM-L6-v2）
  → M3: 多源检索（news / scouting reports / external APIs）
```

---

## 15. 下一阶段建议

Demo runbook 完成后，建议进入：

```text
1. RAG-v2 Demo Smoke Test
   → 在真实 API 流程中验证 semantic retrieval 的 evidence 追加效果
   → 准备 manual notes seed 数据，开启 config，调用 /api/evidence/pick，查看返回的 retrieved_evidence

2. Real Embedding Adapter Preflight
   → 设计真实 embedding model 的适配层（如 sentence-transformers/all-MiniLM-L6-v2）
   → 保持 embed_chunk / embed_query 接口不变，底层切换为真实模型
   → 验证维度兼容性（fake 是 384 维，all-MiniLM-L6-v2 也是 384 维）

3. Real LLM explanation endpoint production hardening
   → 当前 LLM explanation 已有 payload whitelist + fallback
   → 生产环境需要：rate limiting、timeout、cost tracking、prompt versioning

4. Draft-day UI evidence polish
   → 前端展示 semantic retrieval 追加的 RetrievedEvidence
   → 区分 manual note evidence 和 semantic retrieval evidence 的视觉呈现
   → retrieval_score 不在前端展示（只用于后端排序）
```

---

## 附录：RAG-v2 M2 里程碑 tag 清单

```text
rag-v2-m2a-chunking-preflight-audit              — M2-A 切分预审
rag-v2-m2b-evidence-chunker                       — M2-B 证据切分器
rag-v2-m2b-evidence-chunker-acceptance            — M2-B 验收
rag-v2-m2c-embedding-preflight-audit              — M2-C embedding 预审
rag-v2-m2c1-fake-embedding-foundation             — M2-C1 fake embedding 基础
rag-v2-m2c1-fake-embedding-foundation-acceptance  — M2-C1 验收
rag-v2-m2d-vector-store-preflight-audit           — M2-D 向量库预审
rag-v2-m2d1-in-memory-vector-store                — M2-D1 内存向量库
rag-v2-m2d1-in-memory-vector-store-acceptance     — M2-D1 验收
rag-v2-m2d2-semantic-retrieval-service            — M2-D2 语义检索服务
rag-v2-m2d2-semantic-retrieval-service-acceptance — M2-D2 验收
rag-v2-m2e-config-gated-semantic-retrieval        — M2-E config-gated 接入
rag-v2-m2e-config-gated-semantic-retrieval-acceptance — M2-E 验收
```
