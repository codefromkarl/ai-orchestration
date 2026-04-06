# Taskplane Documentation

> 最后更新：2026-04-06

本文档是当前仓库的**文档导航入口**。默认阅读顺序：

1. `README.md`：项目概览、安装、快速开始
2. `docs/README.md`：文档树与阅读路径
3. 具体主题文档：按架构 / 工作流 / 设计 / 归档分类进入

---

## 1. 文档树规范

当前仓库文档按以下层次组织：

```text
README.md                      # 项目总入口（面向首次使用者）
docs/
  README.md                    # 文档导航入口（面向持续维护者）
  architecture-*.md            # 架构与一致性分析
  *-design.md                  # 产品/方案设计
  workflows/                   # 可执行工作流与操作手册
  templates/                   # Epic / Story / Task 模板
  adr/                         # 架构决策记录
  reports/                     # 验证报告、测试报告
  archive/                     # 历史实现总结、阶段性沉淀
sql/
  MIGRATION_GUIDE.md           # SQL / migration 权威说明
```

### 分类约定

- **README.md**
  - 只保留：项目定位、快速开始、常用入口、关键链接
  - 不承载长篇阶段总结或历史实现记录
- **docs/workflows/**
  - 存放“我该怎么用”的操作文档
  - 例如：日常三命令工作流、导入/治理/执行手册
- **docs/reports/**
  - 存放测试报告、验收报告、E2E 报告
- **docs/archive/**
  - 存放历史阶段总结、实现回顾、旧路线说明
  - 默认不是一线入口文档

---

## 2. 推荐阅读路径

### 初次了解 Taskplane

1. `README.md`
2. `docs/architecture-overview.md`
3. `docs/substrate-architecture.md`
4. `docs/program-governance-model.md`

### 想直接上手日常工作流

1. `README.md`
2. `docs/workflows/three-command-workflow.md`
3. `sql/MIGRATION_GUIDE.md`

### 想理解自然语言入口与自动编排边界

1. `docs/product-roadmap.md`
2. `docs/natural-language-intake-followup-plan.md`
3. `docs/adr/0001-engineering-boundaries.md`

### 想理解控制面与验证模型

1. `docs/task-orchestrator-correctness-and-verification-design.md`
2. `docs/ai-task-testing-strategy.md`
3. `docs/eval-boundary.md`

---

## 3. 当前核心文档

### 项目入口

- `README.md`：项目概览、安装、运行、CLI/API 入口

### 工作流

- `docs/workflows/three-command-workflow.md`：当前推荐的 `/tp-link` / `/tp-intake` / `/tp-status` 三命令工作流

### 架构与边界

- `docs/architecture-overview.md`
- `docs/agent-harness-target-architecture.md`
- `docs/substrate-architecture.md`
- `docs/architecture-data-consistency-analysis.md`
- `docs/adr/0001-engineering-boundaries.md`

### 产品与路线

- `docs/product-roadmap.md`
- `docs/mvp-design.md`
- `docs/program-governance-model.md`
- `docs/natural-language-intake-followup-plan.md`

### 测试与验证

- `docs/ai-task-testing-strategy.md`
- `docs/task-orchestrator-correctness-and-verification-design.md`
- `docs/reports/e2e-test-report.md`

### 数据库与迁移

- `sql/MIGRATION_GUIDE.md`

---

## 4. 历史/归档文档

这些文档仍然保留，但默认不作为当前产品入口：

- `docs/archive/multi-project-implementation.md`
- `docs/archive/parallel-execution-implementation.md`

它们适合回答：

- 某个阶段最初是怎么实现的
- 历史设计曾经包含哪些模块
- 旧的实现边界和迁移背景是什么

---

## 5. 维护规则

后续新增文档时，建议遵守以下规则：

1. **先判断类型，再落目录**
   - 操作手册 → `docs/workflows/`
   - 报告 → `docs/reports/`
   - 历史总结 → `docs/archive/`
   - 稳定架构结论 → `docs/` 顶层或 `docs/adr/`

2. **README 只做入口，不做仓库备忘录**

3. **阶段性总结不要继续堆在根目录**

4. **每个新增文档都应能回答：**
   - 它的目标读者是谁？
   - 它是当前权威文档，还是历史归档？

5. **不要把临时 markdown 产物当成正式文档树的一部分**
   - `examples/`、`tests/`、`frontend/src/` 中出现的 `.md` 文件通常是样例、fixture 或中间产物
   - 它们默认不属于仓库文档导航入口
