"""
Agent Hub Module

多 Agent 管理模块。
支持：
- 管理多个 AI CLI 工具实例 (Claude Code, Gemini CLI, Codex, OpenCode, Qwen Code)
- 并行执行和结果聚合
- 动态创建/销毁 Agent
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal

from .models import ExecutionContext, WorkItem
from .worker import ExecutionResult

# =============================================================================
# Type Definitions
# =============================================================================

AgentType = Literal[
    "claude_code",
    "gemini_cli",
    "codex",
    "opencode",
    "qwen_code",
]


@dataclass
class AgentConfig:
    """Agent 配置"""

    agent_name: str
    agent_type: AgentType
    command_template: str
    timeout_seconds: int = 1800
    max_retries: int = 3
    auto_context_resume: bool = True
    metadata: dict = field(default_factory=dict)

    def get_command(self, work_item: WorkItem) -> str:
        """
        根据 work_item 生成实际命令

        Args:
            work_item: 工作项

        Returns:
            完整的命令字符串
        """
        env_vars = {
            "STARDRIFTER_WORK_ID": work_item.id,
            "STARDRIFTER_WORK_TITLE": work_item.title,
            "STARDRIFTER_WORK_LANE": work_item.lane,
            "STARDRIFTER_WORK_WAVE": work_item.wave,
        }

        command = self.command_template
        for key, value in env_vars.items():
            command = command.replace(f"${{{key}}}", value)
            command = command.replace(f"${key}", value)

        return command


# =============================================================================
# Agent Instance
# =============================================================================

@dataclass
class AgentInstance:
    """运行中的 Agent 实例"""

    agent_name: str
    work_id: str
    process: subprocess.Popen | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    thread: threading.Thread | None = None


# =============================================================================
# Agent Hub
# =============================================================================

class AgentHub:
    """
    Agent 管理中心

    管理多个 AI CLI 工具实例，支持并行执行和结果聚合
    """

    def __init__(self, workdir: str | None = None):
        self.workdir = workdir or os.getcwd()
        self._agents: dict[str, AgentConfig] = {}
        self._running_instances: dict[str, AgentInstance] = {}
        self._lock = threading.Lock()

    def register_agent(self, config: AgentConfig) -> None:
        """
        注册 Agent 配置

        Args:
            config: Agent 配置
        """
        with self._lock:
            self._agents[config.agent_name] = config

    def unregister_agent(self, agent_name: str) -> None:
        """注销 Agent"""
        with self._lock:
            self._agents.pop(agent_name, None)

    def get_agent(self, agent_name: str) -> AgentConfig | None:
        """获取 Agent 配置"""
        return self._agents.get(agent_name)

    def list_agents(self) -> list[AgentConfig]:
        """列出所有已注册的 Agent"""
        return list(self._agents.values())

    def get_available_agents(self) -> list[AgentConfig]:
        """获取可用的 Agent（未在运行中）"""
        with self._lock:
            running_agent_names = {
                inst.agent_name for inst in self._running_instances.values()
                if inst.finished_at is None
            }
            return [
                config for config in self._agents.values()
                if config.agent_name not in running_agent_names
            ]

    def execute(
        self,
        agent_name: str,
        work_item: WorkItem,
        execution_context: ExecutionContext | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ExecutionResult:
        """
        执行 Agent

        Args:
            agent_name: Agent 名称
            work_item: 工作项
            execution_context: 执行上下文
            heartbeat: 心跳回调

        Returns:
            执行结果
        """
        config = self._agents.get(agent_name)
        if config is None:
            return ExecutionResult(
                success=False,
                summary=f"Agent '{agent_name}' not found",
                command_digest="",
                exit_code=1,
                elapsed_ms=0,
            )

        command = config.get_command(work_item)
        return self._execute_process(
            command=command,
            agent_name=agent_name,
            work_id=work_item.id,
            timeout_seconds=config.timeout_seconds,
            heartbeat=heartbeat,
        )

    def execute_parallel(
        self,
        agent_configs: list[tuple[AgentConfig, WorkItem]],
        heartbeat: Callable[[], None] | None = None,
    ) -> list[tuple[str, ExecutionResult]]:
        """
        并行执行多个 Agent

        Args:
            agent_configs: (AgentConfig, WorkItem) 列表
            heartbeat: 心跳回调

        Returns:
            [(agent_name, ExecutionResult)] 列表
        """
        results: list[tuple[str, ExecutionResult]] = []
        threads: list[threading.Thread] = []
        results_lock = threading.Lock()

        def run_single(
            config: AgentConfig,
            work_item: WorkItem,
        ) -> None:
            result = self.execute(
                agent_name=config.agent_name,
                work_item=work_item,
                heartbeat=heartbeat,
            )
            with results_lock:
                results.append((config.agent_name, result))

        for config, work_item in agent_configs:
            thread = threading.Thread(
                target=run_single,
                args=(config, work_item),
            )
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        return results

    def _execute_process(
        self,
        command: str,
        agent_name: str,
        work_id: str,
        timeout_seconds: int,
        heartbeat: Callable[[], None] | None = None,
    ) -> ExecutionResult:
        """执行底层进程"""
        started_at = time.perf_counter()

        # 创建实例记录
        instance = AgentInstance(
            agent_name=agent_name,
            work_id=work_id,
            started_at=datetime.utcnow(),
        )

        with self._lock:
            self._running_instances[f"{agent_name}:{work_id}"] = instance

        try:
            process = subprocess.Popen(
                ["bash", "-c", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.workdir,
                text=True,
            )

            instance.process = process

            # 等待完成
            stdout, stderr = self._wait_with_heartbeat(
                process, timeout_seconds, heartbeat
            )

            instance.stdout_buffer = stdout
            instance.stderr_buffer = stderr
            instance.exit_code = process.returncode
            instance.finished_at = datetime.utcnow()

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)

            # 解析结果
            summary = self._parse_output(stdout, stderr)
            success = process.returncode == 0

            return ExecutionResult(
                success=success,
                summary=summary,
                command_digest=command,
                exit_code=process.returncode,
                elapsed_ms=elapsed_ms,
                stdout_digest=stdout.strip()[:1000],
                stderr_digest=stderr.strip()[:1000],
            )

        except subprocess.TimeoutExpired as exc:
            instance.finished_at = datetime.utcnow()
            instance.exit_code = 124

            return ExecutionResult(
                success=False,
                summary=f"Agent execution timed out after {timeout_seconds}s",
                command_digest=command,
                exit_code=124,
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            )

        finally:
            # 清理实例记录
            with self._lock:
                self._running_instances.pop(f"{agent_name}:{work_id}", None)

    def _wait_with_heartbeat(
        self,
        process: subprocess.Popen,
        timeout_seconds: int,
        heartbeat: Callable[[], None] | None,
    ) -> tuple[str, str]:
        """等待进程完成，同时发送心跳"""
        start = time.perf_counter()

        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.5)
                return stdout, stderr
            except subprocess.TimeoutExpired:
                # 检查是否超时
                if (time.perf_counter() - start) > timeout_seconds:
                    process.kill()
                    raise

                # 发送心跳
                if heartbeat is not None:
                    heartbeat()

    def _parse_output(self, stdout: str, stderr: str) -> str:
        """解析输出，提取关键结果"""
        # 尝试提取结构化结果
        import json
        import re

        # 查找 JSON 结果
        json_pattern = r'\{[^{}]*"outcome"[^{}]*\}'
        matches = re.findall(json_pattern, stdout, re.DOTALL)

        if matches:
            try:
                result = json.loads(matches[-1])
                return result.get("summary", str(result))
            except json.JSONDecodeError:
                pass

        # 默认返回输出摘要
        lines = (stdout + stderr).strip().splitlines()
        if len(lines) > 10:
            return "...\n".join(lines[-10:])
        return stdout + stderr

    def get_running_count(self) -> int:
        """获取运行中的 Agent 数量"""
        with self._lock:
            return sum(
                1 for inst in self._running_instances.values()
                if inst.finished_at is None
            )

    def get_running_instances(self) -> list[AgentInstance]:
        """获取运行中的实例列表"""
        with self._lock:
            return [
                inst for inst in self._running_instances.values()
                if inst.finished_at is None
            ]

    def stop_agent(self, agent_name: str, work_id: str) -> bool:
        """停止指定 Agent 实例"""
        key = f"{agent_name}:{work_id}"

        with self._lock:
            instance = self._running_instances.get(key)
            if instance is None or instance.process is None:
                return False

            try:
                instance.process.terminate()
                return True
            except Exception:
                instance.process.kill()
                return True


# =============================================================================
# Factory Functions
# =============================================================================

def create_default_agent_hub(workdir: str | None = None) -> AgentHub:
    """
    创建默认 Agent Hub

    预注册常用的 AI CLI 工具
    """
    hub = AgentHub(workdir=workdir)

    # Claude Code
    hub.register_agent(AgentConfig(
        agent_name="claude-code",
        agent_type="claude_code",
        command_template="claude --work-id ${STARDRIFTER_WORK_ID}",
        timeout_seconds=1800,
        max_retries=3,
    ))

    # Opencode (默认)
    hub.register_agent(AgentConfig(
        agent_name="opencode",
        agent_type="opencode",
        command_template=(
            "python3 -m stardrifter_orchestration_mvp.opencode_task_executor"
        ),
        timeout_seconds=1800,
        max_retries=3,
        auto_context_resume=True,
    ))

    return hub


# =============================================================================
# 与 ExecutorAdapter 集成
# =============================================================================

def build_agent_hub_executor(
    hub: AgentHub,
    agent_name: str,
) -> Callable:
    """
    构建 Agent Hub Executor

    Args:
        hub: Agent Hub 实例
        agent_name: Agent 名称

    Returns:
        符合 ExecutorAdapter 协议的 callable
    """
    def executor(
        work_item: WorkItem,
        workspace_path: str | None = None,
        execution_context: ExecutionContext | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ExecutionResult:
        return hub.execute(
            agent_name=agent_name,
            work_item=work_item,
            execution_context=execution_context,
            heartbeat=heartbeat,
        )

    return executor
