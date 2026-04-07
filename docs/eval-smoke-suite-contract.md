# Eval Smoke Suite Contract

> 最后更新：2026-04-07
> 状态：active minimal contract

本文档描述 Taskplane 当前提供的**最小 smoke suite contract**，用于给下游 EvalOps / CI 消费方提供稳定的 suite / scenario 命名基础。

它的目标不是实现 benchmark orchestration，也不是承担 dataset registry，而是提供一份**稳定、轻量、可引用的 smoke suite manifest**。

---

## 1. 设计目标

当前 contract 的目标是：

1. 给 `attempt_report` / CLI 报表提供稳定的 `suite` / `scenario` 命名
2. 给下游 EvalOps 提供最小默认 smoke suite 约定
3. 避免每个消费者各自发明不一致的 scenario id
4. 在不引入完整 benchmark 管理系统的前提下，建立回归分析的最小基础

---

## 2. 当前默认 suite

Taskplane 当前内置的默认 smoke suite id 为：

- `smoke-core`

代码入口：

- `src/taskplane/eval_smoke_suites.py`

构建函数：

- `build_default_smoke_suite_manifest()`

---

## 3. 当前默认 scenarios

默认 smoke suite 当前包含 4 个 scenario：

### 3.1 `first-attempt-success`

- summary: 首次尝试即成功
- expected pattern: `success`

### 3.2 `retry-then-success`

- summary: 首次失败，重试后成功
- expected pattern: `retry_success`

### 3.3 `blocked-then-escalate`

- summary: 工作被阻塞并进入显式升级/人工处理路径
- expected pattern: `operator_escalation`

### 3.4 `verify-fail-then-replan`

- summary: 验证失败后进入重新规划路径
- expected pattern: `replan_after_verify_failure`

---

## 4. 与报表 CLI 的关系

`taskplane-attempt-report` 当前支持：

- `--suite`
- `--scenario`

这两个参数不会改变 Taskplane 的 control-plane runtime truth，
而是作为**导出上下文**附加到报表输出中，供下游 CI / EvalOps 做分组、聚合和比较。

示例：

```bash
taskplane-attempt-report \
  --repo owner/repo \
  --format json \
  --suite smoke-core \
  --scenario retry-then-success
```

JSON 输出会附带：

```json
{
  "context": {
    "suite": "smoke-core",
    "scenario": "retry-then-success"
  }
}
```

---

## 5. 边界说明

这个 smoke suite contract 仍然遵守 `docs/eval-boundary.md`：

### Taskplane 当前负责

- 提供稳定 suite/scenario id 约定
- 提供最小 smoke suite manifest
- 在 report/export surface 中承载 suite/scenario 上下文

### 仍然属于 EvalOps 的内容

- dataset/case registry
- benchmark suite management
- replay orchestration
- scorer/judge systems
- regression baseline comparison
- release gate policy

也就是说，Taskplane 当前只负责：

> 给 smoke suite 提供稳定 contract

而不是：

> 运行完整 benchmark/eval 平台

---

## 6. 后续扩展建议

后续如果继续沿 Track C 推进，建议按以下顺序扩展：

1. 在 smoke suite manifest 中加入更明确的 pattern/notes 字段
2. 为 suite/scenario 增加文档化的输入假设和验证期望
3. 定义最小 CI threshold contract
4. 再考虑是否需要外部 EvalOps runner 读取这份 contract 自动执行 suite

---

## 7. 当前权威入口

- 文档：`docs/eval-smoke-suite-contract.md`
- 代码：`src/taskplane/eval_smoke_suites.py`
- 报表导出：`src/taskplane/attempt_report_cli.py`

如果未来 contract 发生变化，应同步更新以上三个入口。
