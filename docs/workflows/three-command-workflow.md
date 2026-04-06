# Three-Command Workflow

> 最后更新：2026-04-06
> 验证状态：已通过 `tests/test_workflow_cli.py` 与相关 CLI / API 回归测试

本文档描述当前仓库推荐的**最小日常工作流**：

- `link`：把当前仓库接入 Taskplane
- `intake`：提交需求并处理所有人工反馈
- `status`：查看运行态、阻塞与下一步建议

底层统一走：`taskplane-workflow`

---

## 1. 适用场景

适用于以下目标：

- 把当前代码仓库接入 Taskplane 控制面
- 通过自然语言把需求送入编排器
- 让编排器拆分 proposal / story / task，并继续自动执行
- 在遇到澄清、review、operator request、blocked task 时，通过统一入口继续推进

不适用于：

- 需要直接操作底层治理/投影命令的高级维护场景
- 需要手动逐步运行 import / project / governance / worker 的调试场景

---

## 2. 前提条件

执行三命令工作流前，需满足：

1. `taskplane.toml` 中已配置 PostgreSQL DSN
2. 数据库已完成核心 migration
3. 建议使用：

```bash
taskplane-dev up
```

这一步会应用包括 `008_repo_registry.sql` 在内的核心 migration。

如果数据库未应用 `repo_registry` 相关 migration，`status` 查询会失败，因为 repo 注册表是三命令工作流的 repo 锚点之一。

---

## 3. 三个命令

## 3.1 link

```bash
taskplane-workflow link
```

作用：

- 自动从当前 git remote 推断 `owner/repo`
- 在 `repo_registry` 中创建或更新 repo 记录
- 将当前 repo 的 `workdir` / `log_dir` 写入 `taskplane.toml`

可选参数：

```bash
taskplane-workflow link --repo owner/repo --workdir /abs/path/to/repo --log-dir /abs/path/to/logs
```

建议使用时机：

- 第一次把某个仓库接入 Taskplane
- 当前 repo 在数据库中还没有记录
- 当前 `taskplane.toml` 缺少 workdir / logdir 映射

---

## 3.2 intake

### 提交新需求

```bash
taskplane-workflow intake "实现认证系统，包含 JWT 登录、刷新 token、前端登录页和权限守卫"
```

### 回答澄清问题

```bash
taskplane-workflow intake --intent <intent-id> --answer "先支持 Web，不做 OAuth"
```

### approve

```bash
taskplane-workflow intake --intent <intent-id> --approve
```

### reject

```bash
taskplane-workflow intake --intent <intent-id> --reject "范围过大，先收敛到后端 API"
```

### revise

```bash
taskplane-workflow intake --intent <intent-id> --revise "拆成登录、刷新 token、权限守卫三个 story"
```

### 处理 operator request

```bash
taskplane-workflow intake --request epic:42:progress_timeout
```

设计原则：

- 所有“人需要继续回复系统”的动作都统一走 `intake`
- 不额外引入第四个命令处理 review / answer / approve / blocked action

---

## 3.3 status

```bash
taskplane-workflow status
```

作用：

- 查看 repo 任务总览
- 查看 running jobs
- 查看 blocked tasks
- 查看等待你处理的 clarification / review / operator request
- 输出下一步建议动作

可选：

```bash
taskplane-workflow status --repo owner/repo
```

---

## 4. 建议使用顺序

```text
link   -> 把当前仓库接入 Taskplane
intake -> 提交需求，进入 proposal/review/promotion
status -> 查看执行、阻塞、待确认项
intake -> 根据 status 返回的建议继续 answer/approve/revise/request
status -> 再次确认系统继续推进
```

---

## 5. 与 `/tp-*` 别名的映射

如果你在外层工作流中使用 slash 命令，推荐映射如下：

```text
/tp-link   -> taskplane-workflow link
/tp-intake -> taskplane-workflow intake ...
/tp-status -> taskplane-workflow status
```

推荐的人类输入形式：

```text
/tp-link
/tp-intake 实现认证系统，包含 JWT 登录、刷新 token、前端登录页和权限守卫
/tp-intake intent=abc123 answer="先支持 Web，不做 OAuth"
/tp-intake intent=abc123 approve
/tp-status
```

---

## 6. 验证记录

当前工作流相关验证：

```bash
python3 -m pytest tests/test_workflow_cli.py -q
python3 -m pytest tests/test_cli_commands.py tests/test_hierarchy_api_actions.py -q
```

最近一次验证结果：

- `tests/test_workflow_cli.py`: 3 passed
- `tests/test_cli_commands.py tests/test_hierarchy_api_actions.py`: 36 passed

---

## 7. 当前边界与注意事项

1. 三命令工作流是**高层操作入口**，不是对所有底层 CLI 的替代。
2. `status` 依赖 repo 已存在于控制面可识别集合中；推荐先执行 `link`。
3. 当前文档导入计划仍然是“把文档内容送进 intake”，仓库尚未实现专门的 `--file` 文档导入入口。
4. 编排器支持自动执行，但遇到澄清、review、operator request、verification failure 时，仍需要 `intake` / `status` 形成闭环。
