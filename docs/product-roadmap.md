# Taskplane Product Roadmap

> 最后更新：2026-04-06

## 1. 产品定位

Taskplane 的目标不是做一个通用项目管理 SaaS，也不是做一个“输入一句话自动完成整个项目”的全自治系统。

Taskplane 的目标应固定为：

- 以 PostgreSQL 为真相源的 AI 执行控制面
- 在控制面之上提供治理层、审计层、恢复层和受控的需求入口
- 让 operator 能看见、干预、恢复、推进 AI 执行链路

与当前仓库的一致边界：

- 控制面真相在 PostgreSQL，不在 GitHub、前端状态或自然语言对话
- repository 是 claim / finalize / retry / approval 的权威边界
- 自然语言、UI、报告、策略只应扩展在边缘层，不应反向侵入核心状态机

参考文档：

- `README.md`
- `docs/architecture-overview.md`
- `docs/program-governance-model.md`
- `docs/mvp-design.md`
- `docs/adr/0001-engineering-boundaries.md`

## 2. 长期边界

### 2.1 必须坚持的边界

- Taskplane 是执行控制面，不是通用协同办公平台
- Taskplane 记录事实、决策、证据、恢复路径，不承担任意内容创作
- LLM 输出只能是 proposal，不是直接真相
- 所有自动化动作都必须可审计、可追溯、可恢复
- 模式差异只能体现在 policy 和入口上，不应复制核心执行链路

### 2.2 明确不做

- 不做团队聊天工具
- 不做文档协作平台
- 不做通用 BI / 数据分析平台
- 不做任意代码变更的自动回滚引擎
- 不做无限开放的自然语言项目管理代理
- 不做“每种集成各自一套状态机”的 source-specific 产品分叉

### 2.3 延后做

- 复杂审批流设计器
- 插件市场
- 大规模权限系统
- 复杂跨组织治理模型
- 高度可视化的拖拽式工作流编排器

## 3. 冻结规则

后续版本更新必须遵守以下冻结规则，避免陷入重构陷阱。

### 3.1 核心数据模型冻结

以下对象视为长期合同，原则上只允许增加字段、视图、索引和兼容表，不允许频繁改变语义：

- `work_item`
- `work_dependency`
- `work_target`
- `work_claim`
- `program_epic`
- `program_story`
- `execution_run`
- `verification_evidence`
- `execution_session`
- `execution_checkpoint`
- `execution_wakeup`
- `policy_resolution`
- `event_log`
- `dead_letter_queue`

### 3.2 核心状态机冻结

以下状态流只允许做兼容增强，不允许每个版本重写：

- `pending -> ready -> in_progress -> verifying -> awaiting_approval|blocked|done`
- `program_status`
- `execution_status`
- retry/backoff 语义
- claim/lease/finalize 边界

### 3.3 新能力扩展顺序

新增能力必须优先按以下顺序扩展：

1. 新 API
2. 新查询 / 新视图
3. 新事件类型
4. 新边缘表
5. 新 policy 配置
6. 最后才考虑触碰 worker / repository 主链路

默认禁止：

- 为了支持一个新 UI 动作而改写核心状态机
- 为了支持一种新来源而复制一套控制面模型
- 为了支持自然语言而绕过治理层直接写执行层

## 4. 版本路线

## V1：Operator Console 完整化

### 目标

把当前“已有底座 + 半成品操作台”收敛成一个真正可用的 operator 产品。

### 范围

- 打通指挥所的真实动作执行
- 补齐 split / retry / decide / ack 的统一入口
- 增强运行态摘要、失败摘要、DLQ 视图、事件时间线
- 提供最小报告页：当前运行、阻塞分布、最近失败、待处理事项
- 统一 repo / all-repo 视图的展示逻辑
- 当前控制台已经支持 operator request ack，后续只需要把相同语义在更细的查询和展示面上做一致化

### 非目标

- 不做自然语言自动建模
- 不做新状态机
- 不做多种审批流
- 不做复杂 RBAC

### 数据变更原则

- 只增加查询、视图、前端接口
- 尽量复用 `event_log`、`dead_letter_queue`、`execution_run`
- 不修改 `work_item` 主语义

### 验收标准

- operator 可以在 UI 中完成 `split/retry/ack/decide`
- operator 无需看数据库即可判断当前卡点
- 失败任务和待决策任务都有统一入口
- 单仓库与多仓库视图都可稳定使用

## V2：受控自然语言入口

### 目标

提供自然语言需求输入，但限定为“受控解析 + 结构化 promotion”，不允许直接驱动执行层。

当前仓库已经实现的 review 边界是：

- `natural_language_intent` 作为 proposal / review 记录
- CLI 支持 `submit / answer / approve`
- Console / API 支持 `approve / reject / revise`
- Console 也支持 operator request ack
- review metadata 记录在控制面，不直接改写 `work_item`

### 范围

- 新增 `intent` 层
- 支持自然语言创建需求草案
- 将草案解析为结构化 proposal
- 支持从 proposal promotion 到 `program_epic` / `program_story` / `work_item`
- 第一批仅支持有限命令域：
  - 创建 story
  - 创建 task
  - 重试 task
  - 拆分 story
  - 调整优先级
  - 纳入 backlog

### 非目标

- 不做开放式 agent PM
- 不做“需求直接生成并自动执行”
- 不让自然语言直接写 `work_item`

### 数据变更原则

- `natural_language_intent` 已经是当前 reviewable edge table
- 若后续要细分审计，优先拆出 `intent_parse_attempt`、`intent_promotion`、`intent_review_decision`
- proposal 与 canonical entity 必须分离
- promotion 必须显式记录来源、批准方式和映射结果

### 验收标准

- 任意自然语言请求都会先进入 proposal 状态
- promotion 前可审阅、可拒绝、可重新解析
- promotion 后才进入现有治理层 / 执行层
- 所有自然语言动作都有审计记录

### 当前实现后的后续计划

- 详细实施计划见：`docs/natural-language-intake-followup-plan.md`
- 当前优先级：review 历史/审计视图 → 更强 planning/brainstorming → scheduler/supervisor 集成回归

## V3：模式化产品

### 目标

把 Direct / Managed / Orchestrated 做成显式的产品模式，但共用同一控制面。

### 范围

- 引入 mode policy profile
- `Direct`
  - 适合轻量请求
  - 治理最少
  - 快速落到执行链路
- `Managed`
  - 必须先生成计划，再执行
  - 允许人工确认关键 promotion
- `Orchestrated`
  - 面向复杂项目
  - 启用 portfolio/governance/global coordination

### 非目标

- 不复制三套 worker
- 不复制三套 schema
- 不为每种模式引入独立 API 栈

### 数据变更原则

- mode 是 policy，不是状态机分叉
- mode 只影响准入、拆解、审批、调度阈值
- 模式元数据应附着在 request / intent / governance 上，而非重写 execution layer

### 验收标准

- 用户能够明确选择模式
- 三种模式共享同一执行与审计链路
- 不同模式的差异可从 policy 配置中读出

## V4：Portfolio / Multi-Repo Orchestration

### 目标

在现有治理模型上正式支持跨仓库和 program-level 执行编排。

### 范围

- portfolio 级总览
- 跨 repo 优先级与资源协调
- global coordinator 的产品化
- agent pool / executor routing 的可视化与治理动作
- governance 层的跨仓库健康检查

### 非目标

- 不做跨组织复杂权限系统
- 不做通用项目组合管理 SaaS
- 不做独立的资源管理平台

### 数据变更原则

- 优先复用现有 portfolio、agent、notification 查询面
- 不拆分现有仓库级控制面模型

### 验收标准

- operator 能看见跨 repo 的执行压力和阻塞
- program manager 能看见 portfolio 级优先级和健康度
- 多仓库调度不会破坏单仓库语义

## V5：Knowledge / Eval / Improvement Loop

### 目标

把执行历史转成可回用知识，而不是停留在事件和日志沉淀。

### 范围

- executor 选择效果评估
- 失败模式聚类
- decomposition 质量回看
- 自动生成 operator 建议和治理建议
- 对常见失败场景形成 repair playbook

### 非目标

- 不做通用分析平台
- 不把 Taskplane 变成 EvalOps 的 truth owner
- 不把历史分析结果直接反写核心执行事实

### 数据变更原则

- 评估与知识层是下游消费层
- 不改变 `execution_run`、`verification_evidence` 的事实语义
- 新分析结果以派生表、导出表、建议对象存在

### 验收标准

- 系统能对失败和拆解质量给出稳定建议
- 建议可以被 operator 使用，但不会自动覆写真相源

## 5. 优先级建议

建议版本推进顺序：

1. `V1`
2. `V2`
3. `V3`
4. `V4`
5. `V5`

原因：

- `V1` 提升可用性，能马上降低 operator 成本
- `V2` 才开始引入新入口，但有 V1 的动作与报告面托底
- `V3` 在 V2 基础上抽象产品模式，避免一开始过度设计
- `V4` 只有在真实出现多仓库压力时才值得推进
- `V5` 属于稳定期放大器，不应抢在主链路产品化之前

## 6. 决策门槛

每次启动新版本前，必须先回答以下问题。

### 6.1 是否触碰核心合同

如果需求需要改写以下任一项，默认判定为高风险：

- `work_item` 核心语义
- `program_story` / `program_epic` 核心状态语义
- claim / finalize 边界
- retry / approval 基础语义

### 6.2 是否可以通过边缘层实现

优先尝试：

- 新接口
- 新 projection
- 新 intent / proposal 表
- 新查询视图
- 新 policy profile

只有边缘层确实无法表达时，才允许改核心模型。

### 6.3 是否在扩张产品边界

如果一个需求本质上属于：

- 聊天
- 协作文档
- BI
- 通用知识库
- 通用自动化平台

默认拒绝纳入 Taskplane 核心路线，只允许做非常薄的集成。

## 7. 一句话版本纪律

后续版本更新只能增强 Taskplane 作为“可审计、可恢复、可治理的 AI 执行控制面”的能力，不能把它逐步做成一个无边界的通用项目平台。
