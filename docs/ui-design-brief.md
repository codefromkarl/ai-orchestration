# Stardrifter Console — UI 设计文档

## 一、项目定位

**一句话定义**：面向 operator 的 AI 任务编排控制台。

**做什么**：管理 AI agent 执行 Starsector mod 迁移到 Godot 的全过程。从 epic（大目标）拆解为 story（中目标），再拆解为 task（可执行任务），由 AI agent 自动执行，人工仅在关键决策点介入。

**核心价值**：
- 降低 operator 认知成本（不用看日志和数据库）
- 提升决策速度（快速定位卡点）
- 控制人工介入风险（有限、可解释的操作）

---

## 二、目标用户

| 用户 | 关注点 |
|------|--------|
| Operator（调度员） | 哪个任务卡住了、需要 retry 还是 split |
| Governance Owner（治理负责人） | 结构是否合理、是否需要重新拆分 |
| Program Manager | 跨仓库优先级、资源分配 |

---

## 三、信息架构（3 个 Tab）

### Tab 1: 信息室（Kanban）

**定位**：一眼看清所有任务的执行状态。

**布局**：三列看板
```
┌─────────────┬─────────────┬─────────────┐
│   待办       │   进行中     │   已完成     │
│   (To Do)   │   (Doing)   │   (Done)    │
├─────────────┼─────────────┼─────────────┤
│ [卡片]       │ [卡片]       │ [卡片]       │
│ [卡片]       │ [卡片]       │ [卡片]       │
│ [卡片]       │             │             │
└─────────────┴─────────────┴─────────────┘
```

**卡片内容**：
- Issue 编号 + 标题
- 状态 badge（pending / ready / in_progress / blocked / done）
- 阻塞原因（如有）
- 点击 → 打开右侧详情抽屉

**状态分组逻辑**：
- To Do: pending, ready
- Doing: in_progress, verifying, blocked
- Done: done

---

### Tab 2: 指挥所（Command Center）

**定位**：处理需要人工决策的事项，并支持指令下达。

**布局**：左右分栏
```
┌──────────────────┬──────────────────────────────┐
│   待处理事项      │   指令输入                    │
│   (左栏 320px)   │   (右栏，自适应)              │
├──────────────────┼──────────────────────────────┤
│ [attention item] │ user: 重试 task #55           │
│ [attention item] │ system: 已执行，状态更新为    │
│ [attention item] │         ready                 │
│                  │                              │
│                  │ ┌──────────────────┬─────┐   │
│                  │ │ 输入指令...       │ 发送 │   │
│                  │ └──────────────────┴─────┘   │
└──────────────────┴──────────────────────────────┘
```

**左栏：待处理事项**
- 按优先级排序的 attention 队列
- 每项显示：issue 编号、标题、优先级分数
- 来源：治理自动化 API（priority / health / orphans / auto-split）

**右栏：指令区**
- 上方：历史消息（user/system 交替）
- 下方：文本输入 + 发送按钮
- 支持自然语言指令（未来可接入 AI agent）

---

### Tab 3: 任务仓库（Task Repository）

**定位**：查看所有任务的完整元数据。

**布局**：表格视图
```
┌──────────────────────────────────────────────────────────┐
│  状态筛选 ▼  │  搜索任务...                    │          │
├──────┬────────────┬──────┬──────┬────────┬────────┬──────┤
│ 编号 │ 标题       │ Epic │ Story│ 状态   │ 优先级 │ 阻塞 │
├──────┼────────────┼──────┼──────┼────────┼────────┼──────┤
│ #55  │ 补充...    │ #30  │ #24  │ blocked│ core   │ timeout│
│ #56  │ 为 03-C... │ #29  │ #23  │ ready  │ core   │ —    │
└──────┴────────────┴──────┴──────┴────────┴────────┴──────┘
```

**列定义**：
- 编号：issue number
- 标题：task 标题
- Epic：所属 epic 编号
- Story：所属 story 编号
- 状态：pending / ready / in_progress / blocked / done
- 优先级：governance / core_path / cross_cutting
- 阻塞原因：如有

**交互**：
- 点击行 → 打开右侧详情抽屉
- 支持状态筛选和关键词搜索

---

## 四、全局组件

### 顶部导航栏（Top Nav）

高度：48px

```
┌──────────────────────────────────────────────────────────┐
│ ◆ Stardrifter  │  信息室  指挥所  任务仓库  │ [repo] [EN] │
└──────────────────────────────────────────────────────────┘
```

- 左侧：Logo + 品牌名
- 中间：3 个 Tab 按钮（胶囊样式，当前激活有渐变高亮）
- 右侧：仓库输入框 + 加载按钮 + 语言切换

### 详情抽屉（Detail Drawer）

宽度：360px，右侧固定

```
┌────────────────────────────┐
│ #55 补充 Domain 04 进度... │ × │
├────────────────────────────┤
│ Type    │ task             │
│ Status  │ blocked          │
│ Lane    │ Lane 04          │
│ Wave    │ wave-2           │
├────────────────────────────┤
│ Work status │ blocked      │
│ Blocked     │ timeout      │
├────────────────────────────┤
│ ↗ GitHub Issue             │
└────────────────────────────┘
```

**内容结构**：
- 标题栏：issue 编号 + 标题 + 关闭按钮
- 元数据网格：type, status, lane, wave, complexity
- 工作状态：work_item status, blocked_reason, decision_required
- 外部链接：GitHub Issue 链接

---

## 五、设计系统

### 状态色

| 状态 | 颜色 | 用途 |
|------|------|------|
| pending | #94a3b8 (gray) | 待办 |
| ready | #fbbf24 (yellow) | 就绪 |
| in_progress | #3b82f6 (blue) | 进行中 |
| verifying | #a855f7 (purple) | 验证中 |
| blocked | #ef4444 (red) | 阻塞 |
| done | #22c55e (green) | 完成 |

### Badge 样式

```css
.badge {
  display: inline-flex;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}
.badge--pending   { background: #f1f5f9; color: #64748b; }
.badge--ready     { background: #fef3c7; color: #92400e; }
.badge--in_progress { background: #dbeafe; color: #1d4ed8; }
.badge--blocked   { background: #fee2e2; color: #991b1b; }
.badge--done      { background: #dcfce7; color: #166534; }
```

### 按钮

| 类型 | 样式 | 用途 |
|------|------|------|
| Primary | 蓝色填充 | 主要操作（加载、发送） |
| Ghost | 透明 + 边框 | 次要操作（筛选、切换） |
| Small | 紧凑尺寸 | 卡片内操作 |

### 卡片

```css
.kanban-card {
  padding: 12px;
  border: 1px solid rgba(208, 215, 222, 0.8);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  cursor: pointer;
  transition: box-shadow 180ms, transform 180ms;
}
.kanban-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  transform: translateY(-1px);
}
```

---

## 六、页面尺寸建议

| 设备 | 宽度 | 布局调整 |
|------|------|----------|
| Desktop | 1440px+ | 完整三栏（kanban 三列 + drawer） |
| Laptop | 1280px | kanban 三列紧凑 |
| Tablet | 768px | kanban 改为单列可滑动，drawer 改为底部弹出 |

---

## 七、Figma 组件清单

需要在 Figma 中创建的组件：

1. **TopNav** — 顶部导航栏（Logo + Tabs + Controls）
2. **TabButton** — Tab 按钮（默认 / 悬停 / 激活）
3. **KanbanBoard** — 看板容器
4. **KanbanColumn** — 看板列（标题 + 计数 + 卡片列表）
5. **KanbanCard** — 看板卡片（标题 + badge + meta）
6. **CommandCenter** — 指挥所布局
7. **AttentionItem** — 待处理事项条目
8. **CommandMessage** — 指令消息（user / system）
9. **CommandInput** — 指令输入框
10. **TaskTable** — 任务表格
11. **TaskRow** — 任务行
12. **DetailDrawer** — 详情抽屉
13. **Badge** — 状态徽章（6 种状态色）
14. **Button** — 按钮（Primary / Ghost / Small）

---

## 八、数据流说明（给设计师的上下文）

```
用户打开页面
    ↓
自动加载默认仓库（codefromkarl/stardrifter）
    ↓
信息室 Tab 默认激活
    ↓
调用 /api/repos/{repo}/work-items 获取所有任务
    ↓
按状态分组渲染到三列看板
    ↓
用户点击卡片
    ↓
右侧抽屉打开，调用 /api/issue/{number} 获取详情
    ↓
用户切换到指挥所 Tab
    ↓
调用 /api/repos/{repo}/governance/priority 获取优先级队列
    ↓
用户切换到任务仓库 Tab
    ↓
调用 /api/repos/{repo}/work-items 获取任务列表
    ↓
渲染为表格，支持筛选和搜索
```
