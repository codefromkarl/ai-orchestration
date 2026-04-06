# Natural Language Intake Follow-up Plan

> 最后更新：2026-04-06
> 对应路线：`docs/product-roadmap.md` → `V2：受控自然语言入口`

## 1. 背景

当前仓库已经具备一条最小可运行的自然语言 intake 主链：

- CLI 支持提交、补答和 approve
- Console / API 支持 approve / reject / revise review
- Console 还支持 operator request ack
- `natural_language_intent` 持久化 proposal 及 review metadata
- AI 分析并进入澄清 / 审核状态
- 人工 review 后 promotion 到 `program_epic` / `program_story` / `work_item`
- 复用现有 PostgreSQL 控制面与自动编排主链

当前已落地的关键文件：

- `src/taskplane/intake_service.py`
- `src/taskplane/intake_cli.py`
- `src/taskplane/models.py`
- `src/taskplane/repository/base.py`
- `src/taskplane/repository/postgres.py`
- `src/taskplane/hierarchy_api.py`
- `sql/control_plane_schema.sql`
- `tests/test_intake_workflow.py`

这条主链已经满足“自然语言先进入 proposal/intake 层，再显式 promotion 到执行治理层”的边界要求，没有绕过当前控制面模型。

---

## 2. 当前能力边界

### 2.1 已完成

- 自然语言通过 CLI 进入 intake 层
- 支持澄清问答回合
- 支持 proposal 持久化
- 支持人工 review 后 promotion
- 支持 approve / reject / revise review 动作
- 支持把 review metadata 持久化到 `natural_language_intent`
- 控制台已经支持 operator request ack
- 支持把 promotion 结果写入现有 `program_epic` / `program_story` / `work_item`
- 支持最小 API 查询 intake 列表：`GET /api/repos/{repo:path}/intents`

### 2.2 仍然缺失

- CLI 端尚未补齐 `reject` / `revise` 子命令
- 更强的 brainstorming / planning prompt 与结构化约束
- supervisor 级联消费 intake-promoted story 的集成回归测试
- 更完整的自然语言审计事件模型（当前以 `natural_language_intent` 为主，尚未展开 `intent_parse_attempt` / `intent_promotion` 等细粒度事实表）

---

## 3. 设计边界

后续推进必须继续遵守以下边界：

1. PostgreSQL 仍然是真相源
2. 自然语言结果只能先进入 intake / proposal 层，不能直接改执行真相
3. 尽量通过新增表、查询、API、UI 扩展，不重写 `work_item` 主状态机
4. 尽量复用现有 `program_story -> work_item -> supervisor/worker` 执行主链
5. UI 只是 operator 审核与观测面，不负责定义控制面真相

---

## 4. 后续实施计划

## Phase 1：审核 UI 与操作面补齐

### 目标

让 operator 能在控制台中直接查看 intake 草案、问题、 review 结果，并通过现有审核动作完成闭环。

### 范围

- 完善 intake 列表页 / 卡片区
- 展示 `summary`、`clarification_questions`、`proposal_json`、`review_action`、`review_feedback`
- 对齐 approve / reject / revise 的操作体验
- 不改变当前 promotion 主链

### 建议改动点

- `frontend/src/App.tsx`
- `frontend/src/components/*`
- `frontend/src/api.ts`
- `src/taskplane/hierarchy_api.py`
- 可能新增 console read/query 辅助模块

### 验收标准

- operator 能在 UI 中看到待审核 intake
- operator 能执行 approve / reject / revise 动作
- review 后能观察到关联 epic/story/task 已进入现有任务池或重新进入分析流程

---

## Phase 2：CLI 与审计闭环加固

### 目标

把已经落地的 console / API review 动作补齐到 CLI、审计视图和更完整的历史呈现里，避免把 console 里的能力写成“待实现”。

### 范围

- CLI 端补齐 `reject` / `revise` 子命令
- 统一展示 review history、reason、actor、时间线
- 保持 `natural_language_intent` 作为当前 reviewable edge table
- 支持保留多轮对话与修订痕迹

### 建议改动点

- `src/taskplane/models.py`
- `src/taskplane/intake_service.py`
- `src/taskplane/repository/protocol.py`
- `src/taskplane/repository/base.py`
- `src/taskplane/repository/postgres.py`
- `sql/control_plane_schema.sql`
- `tests/test_repository.py`
- `tests/test_intake_workflow.py`

### 数据建议

优先在现有 `natural_language_intent` 基础上兼容扩展，必要时再拆分为：

- `intent_parse_attempt`
- `intent_promotion`
- `intent_review_decision`

不要一开始就重做整套状态机。

### 验收标准

- CLI、console、API 的 review 动作口径一致
- operator 可以追踪完整 review history
- revise 后保留完整上下文与审计痕迹

---

## Phase 3：更强的 brainstorming / planning 结构化输出

### 目标

让中大任务的拆解质量更稳定，更适合进入后续并行编排。

### 范围

- 强化 intake analyzer prompt
- 明确拆分约束：story 边界、依赖、lane、wave、verification
- 将“澄清阶段”和“拆分阶段”在输出结构上明确分离
- 增加 proposal schema 校验与失败回退

### 建议改动点

- `src/taskplane/intake_service.py`
- `src/taskplane/model_gateway/*`
- 可能新增 `src/taskplane/intake_schema.py` 或类似模块
- `tests/test_intake_workflow.py`
- 新增 schema / validation 测试

### 重点约束

- 不让模型直接生成执行态真相
- 先生成 proposal，再由 promotion 过程映射为 canonical entities
- 要显式生成：
  - story 依赖
  - task 验证方式
  - planned paths
  - done definition

### 验收标准

- intake 对中大任务能稳定产出结构化 proposal
- proposal 出现格式漂移时可检测、可拒绝、可重试
- story/task 依赖能稳定映射到现有调度模型

---

## Phase 4：Supervisor / Scheduler 集成回归测试

### 目标

证明 intake-promoted story 不只是“写入成功”，而是能被现有自动编排真正消费。

### 范围

- 增加从 intake approve 到 story/task 被 scheduler 发现的测试
- 验证依赖 gating 行为
- 验证 ready/pending 状态同步
- 验证 story dependency -> work dependency 映射后，首波任务可进入执行

### 建议改动点

- `tests/test_repository.py`
- `tests/test_worker.py`
- `tests/test_hierarchy_api_actions.py`
- 可能新增 `tests/test_scheduling_loop.py` 或集成测试文件
- 必要时补极少量 repository/query helper

### 验收标准

- approve 后的任务会进入现有 queue 视图
- 无依赖任务转为 `ready`
- 有依赖任务保持 `pending`，上游完成后再转 `ready`
- 不需要新造独立 scheduler

---

## 5. 推荐优先级

建议推进顺序：

1. **Phase 1：审核 UI**
2. **Phase 2：reject / revise 流**
3. **Phase 3：更强 planning / brainstorming**
4. **Phase 4：scheduler/supervisor 集成回归**

原因：

- 当前最缺的是 operator 可见性与治理闭环
- 在没有 reject / revise 前，proposal 审核体验不完整
- 拆分质量优化应建立在完整人工治理面之上
- 更深的调度级回归放在主功能面稳定后补齐更经济

---

## 6. 里程碑定义

### Milestone A：可审核

- 控制台可查看 intake
- 支持 approve / reject
- proposal 基本字段完整展示

### Milestone B：可修订

- 支持 revise 请求
- 支持带原因重跑分析
- 审计链完整保留

### Milestone C：可稳定拆分

- 复杂任务 proposal 更稳定
- schema 漂移可控
- story/task 依赖表达更可靠

### Milestone D：可证明接入现有编排

- intake-promoted story 的 scheduler 回归测试稳定通过
- 能证明确实进入现有并行执行主链

---

## 7. 非目标

当前这份后续计划明确不做：

- 直接“输入一句话自动执行到底”且无审核
- 新造独立的 intake 执行状态机
- 绕过 `program_story/work_item` 直接给 worker 下发自然语言任务
- 引入开放式 PM agent 来替代控制面治理
- 为 UI 便利重写核心 repository 语义

---

## 8. 一句话计划结论

下一阶段的重点不是继续扩张自然语言能力本身，而是把已经打通的 intake 主链补齐为 **可审核、可拒绝、可修订、可验证接入现有编排** 的稳定产品能力。
