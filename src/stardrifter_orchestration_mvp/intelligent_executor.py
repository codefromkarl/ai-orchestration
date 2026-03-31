from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

import psycopg
from psycopg.rows import dict_row

from .models import ExecutionContext, VerificationEvidence, WorkItem
from .worker import ExecutionResult

TERMINAL_OUTCOMES = {"done", "already_satisfied", "blocked", "needs_decision"}
DEFAULT_EXECUTOR_MODEL = "gpt-4.1-mini"
DEFAULT_VERIFIER_MODEL = "gpt-4.1-mini"
MARKDOWN_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ToolInvocation:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    text: str
    tool_calls: tuple[ToolInvocation, ...]
    assistant_message: dict[str, Any]


@dataclass(frozen=True)
class IntelligentExecutorConfig:
    provider: str
    model: str
    max_turns: int
    max_output_tokens: int
    timeout_seconds: int
    max_retries: int
    retry_backoff_seconds: float
    context_chars: int
    context_window_chars: int
    keep_recent_messages: int
    tool_loop_hard_limit: int

    @classmethod
    def from_env(cls) -> IntelligentExecutorConfig:
        return cls(
            provider=(os.environ.get("STARDRIFTER_LLM_PROVIDER") or "openai")
            .strip()
            .lower(),
            model=(
                os.environ.get("STARDRIFTER_LLM_EXECUTOR_MODEL")
                or os.environ.get("STARDRIFTER_LLM_MODEL")
                or DEFAULT_EXECUTOR_MODEL
            ).strip(),
            max_turns=_env_int("STARDRIFTER_LLM_EXECUTOR_MAX_TURNS", 18),
            max_output_tokens=_env_int("STARDRIFTER_LLM_EXECUTOR_MAX_OUTPUT_TOKENS", 1400),
            timeout_seconds=_env_int("STARDRIFTER_LLM_TIMEOUT_SECONDS", 60),
            max_retries=_env_int("STARDRIFTER_LLM_EXECUTOR_MAX_RETRIES", 2),
            retry_backoff_seconds=_env_float(
                "STARDRIFTER_LLM_EXECUTOR_RETRY_BACKOFF_SECONDS", 1.5
            ),
            context_chars=_env_int("STARDRIFTER_LLM_CONTEXT_MAX_CHARS", 16000),
            context_window_chars=_env_int(
                "STARDRIFTER_LLM_CONTEXT_WINDOW_CHARS", 30000
            ),
            keep_recent_messages=_env_int("STARDRIFTER_LLM_KEEP_RECENT_MESSAGES", 8),
            tool_loop_hard_limit=_env_int("STARDRIFTER_LLM_TOOL_LOOP_LIMIT", 4),
        )


@dataclass(frozen=True)
class IntelligentVerifierConfig:
    provider: str
    model: str
    timeout_seconds: int
    max_output_tokens: int
    context_chars: int
    diff_chars: int

    @classmethod
    def from_env(cls) -> IntelligentVerifierConfig:
        return cls(
            provider=(os.environ.get("STARDRIFTER_LLM_PROVIDER") or "openai")
            .strip()
            .lower(),
            model=(
                os.environ.get("STARDRIFTER_LLM_VERIFIER_MODEL")
                or os.environ.get("STARDRIFTER_LLM_MODEL")
                or DEFAULT_VERIFIER_MODEL
            ).strip(),
            timeout_seconds=_env_int("STARDRIFTER_LLM_TIMEOUT_SECONDS", 60),
            max_output_tokens=_env_int("STARDRIFTER_LLM_VERIFIER_MAX_OUTPUT_TOKENS", 1200),
            context_chars=_env_int("STARDRIFTER_LLM_CONTEXT_MAX_CHARS", 16000),
            diff_chars=_env_int("STARDRIFTER_LLM_VERIFIER_DIFF_CHARS", 8000),
        )


class LLMRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reason_code: str = "upstream_api_error",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason_code = reason_code
        self.retryable = retryable


class ToolModelClient(Protocol):
    def complete_with_tools(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> ModelTurn: ...

    def complete_text(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> str: ...


class TaskContextEngine:
    """Build an execution context tuned for a single task."""

    def __init__(self, *, repo_root: Path, max_chars: int) -> None:
        self.repo_root = repo_root.resolve()
        self.max_chars = max_chars

    def build_context(
        self,
        *,
        work_item: WorkItem,
        execution_context: ExecutionContext | None,
        workspace_path: Path,
    ) -> str:
        issue_body, acceptance_criteria = self._load_issue_material(work_item)
        dependency_summaries = self._load_dependency_summaries(work_item)
        related_files = self._collect_related_files(work_item, execution_context, workspace_path)
        conventions = self._load_conventions(workspace_path)

        sections: list[tuple[str, str]] = [
            (
                "Task",
                "\n".join(
                    [
                        f"work_id: {work_item.id}",
                        f"title: {work_item.title}",
                        f"lane: {work_item.lane}",
                        f"wave: {work_item.wave}",
                        f"repo: {work_item.repo or 'unknown'}",
                        f"source_issue_number: {work_item.source_issue_number}",
                        f"task_type: {work_item.task_type}",
                        f"session_policy: {execution_context.session_policy if execution_context else 'fresh_session'}",
                        f"resume_hint: {execution_context.resume_hint if execution_context else ''}",
                    ]
                ),
            ),
            ("Acceptance Criteria", acceptance_criteria),
            (
                "Dependency Summaries",
                "\n".join(dependency_summaries)
                if dependency_summaries
                else "No dependency execution summary available.",
            ),
            (
                "Related Files",
                "\n".join(f"- {path}" for path in related_files)
                if related_files
                else "No related file hints.",
            ),
            (
                "Project Conventions",
                conventions or "No AGENTS.md / CLAUDE.md conventions discovered.",
            ),
            (
                "Issue Body Excerpt",
                issue_body or "No source issue body found in control-plane database.",
            ),
        ]
        return self._trim_sections(sections)

    def _load_issue_material(self, work_item: WorkItem) -> tuple[str, str]:
        dsn = (os.environ.get("STARDRIFTER_ORCHESTRATION_DSN") or "").strip()
        if not dsn:
            return "", ""
        body = ""
        dod_json: Any = {}
        try:
            with psycopg.connect(dsn, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT wi.dod_json, gin.body
                        FROM work_item wi
                        LEFT JOIN github_issue_normalized gin
                          ON gin.repo = wi.repo
                         AND gin.issue_number = wi.source_issue_number
                        WHERE wi.id = %s
                        """,
                        (work_item.id,),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        body = str(row.get("body") or "")
                        dod_json = row.get("dod_json") or {}
        except Exception:
            return "", ""

        acceptance_parts: list[str] = []
        for heading in ("验收标准 (DoD)", "验收标准", "DoD", "Acceptance Criteria"):
            section = _extract_markdown_section(body, {heading})
            if section:
                acceptance_parts.append(section)
        if not acceptance_parts:
            checklist = _extract_checklist_from_dod(dod_json)
            if checklist:
                acceptance_parts.extend(f"- {item}" for item in checklist)
        verification_section = _extract_markdown_section(body, {"验证方式", "Verification"})
        if verification_section:
            acceptance_parts.append("Verification:\n" + verification_section)

        issue_excerpt = body.strip()
        if len(issue_excerpt) > 4000:
            issue_excerpt = issue_excerpt[:4000] + "\n...[truncated]"
        return issue_excerpt, "\n".join(part for part in acceptance_parts if part).strip()

    def _load_dependency_summaries(self, work_item: WorkItem) -> list[str]:
        dsn = (os.environ.get("STARDRIFTER_ORCHESTRATION_DSN") or "").strip()
        if not dsn:
            return []
        summaries: list[str] = []
        try:
            with psycopg.connect(dsn, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            d.depends_on_work_id,
                            wi.title,
                            er.summary,
                            er.result_payload_json,
                            ve.passed,
                            ve.output_digest
                        FROM work_dependency d
                        JOIN work_item wi
                          ON wi.id = d.depends_on_work_id
                        LEFT JOIN LATERAL (
                            SELECT summary, result_payload_json
                            FROM execution_run er
                            WHERE er.work_id = d.depends_on_work_id
                            ORDER BY er.id DESC
                            LIMIT 1
                        ) er ON TRUE
                        LEFT JOIN LATERAL (
                            SELECT passed, output_digest
                            FROM verification_evidence ve
                            WHERE ve.work_id = d.depends_on_work_id
                            ORDER BY ve.id DESC
                            LIMIT 1
                        ) ve ON TRUE
                        WHERE d.work_id = %s
                        ORDER BY d.depends_on_work_id
                        """,
                        (work_item.id,),
                    )
                    rows = cur.fetchall() or []
        except Exception:
            return []

        for row in rows:
            dependency_id = str(row.get("depends_on_work_id") or "")
            title = str(row.get("title") or "")
            summary = str(row.get("summary") or "")
            payload = row.get("result_payload_json")
            reason_code = ""
            if isinstance(payload, dict):
                reason_code = str(payload.get("reason_code") or "")
            verification_text = ""
            passed = row.get("passed")
            if isinstance(passed, bool):
                verification_text = "passed" if passed else "failed"
            output_digest = str(row.get("output_digest") or "")
            digest_excerpt = output_digest[:160]
            line = (
                f"- {dependency_id}: {title} | summary={summary[:180]}"
                f" | reason_code={reason_code or 'n/a'}"
                f" | verification={verification_text or 'unknown'}"
            )
            if digest_excerpt:
                line += f" | evidence={digest_excerpt}"
            summaries.append(line)
        return summaries

    def _collect_related_files(
        self,
        work_item: WorkItem,
        execution_context: ExecutionContext | None,
        workspace_path: Path,
    ) -> list[str]:
        candidates: list[str] = []
        for value in work_item.planned_paths:
            text = str(value).strip()
            if text and text not in candidates:
                candidates.append(text)
        if execution_context is not None:
            for value in execution_context.planned_paths:
                text = str(value).strip()
                if text and text not in candidates:
                    candidates.append(text)

        changed_paths = _safe_git_diff_name_only(workspace_path)
        for changed in changed_paths:
            if changed not in candidates:
                candidates.append(changed)

        return candidates[:40]

    def _load_conventions(self, workspace_path: Path) -> str:
        candidates = [
            workspace_path / "AGENTS.md",
            workspace_path / "CLAUDE.md",
            self.repo_root / "AGENTS.md",
            self.repo_root / "CLAUDE.md",
        ]
        blocks: list[str] = []
        for path in candidates:
            if not path.exists() or not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            snippet = content.strip()
            if len(snippet) > 2200:
                snippet = snippet[:2200] + "\n...[truncated]"
            blocks.append(f"[{path.name}]\n{snippet}")
        return "\n\n".join(blocks)

    def _trim_sections(self, sections: list[tuple[str, str]]) -> str:
        chunks: list[str] = []
        remaining = self.max_chars
        for title, content in sections:
            if not content.strip() or remaining <= 0:
                continue
            block = f"## {title}\n{content.strip()}\n"
            if len(block) <= remaining:
                chunks.append(block)
                remaining -= len(block)
                continue
            hard_limit = max(80, remaining - len(title) - 20)
            trimmed = content.strip()[:hard_limit] + "\n...[truncated]"
            chunks.append(f"## {title}\n{trimmed}\n")
            break
        return "\n".join(chunks).strip()


class WorkspaceToolbox:
    def __init__(self, *, workspace_path: Path) -> None:
        self.workspace_path = workspace_path.resolve()

    def run(self, invocation: ToolInvocation) -> str:
        name = invocation.name
        args = invocation.arguments
        if name == "read_file":
            return self._tool_read_file(args)
        if name == "write_file":
            return self._tool_write_file(args)
        if name == "bash":
            return self._tool_bash(args)
        if name == "grep":
            return self._tool_grep(args)
        if name == "list_files":
            return self._tool_list_files(args)
        raise ValueError(f"unsupported tool: {name}")

    def _tool_read_file(self, args: dict[str, Any]) -> str:
        path = self._resolve_path(str(args.get("path") or ""))
        if not path.exists():
            return _json_dump({"ok": False, "error": f"file not found: {path}"})
        if not path.is_file():
            return _json_dump({"ok": False, "error": f"not a file: {path}"})
        start_line = max(1, int(args.get("start_line") or 1))
        end_line = max(start_line, int(args.get("end_line") or (start_line + 300)))
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return _json_dump({"ok": False, "error": str(exc)})
        slice_lines = lines[start_line - 1 : end_line]
        return _json_dump(
            {
                "ok": True,
                "path": str(path.relative_to(self.workspace_path)),
                "start_line": start_line,
                "end_line": end_line,
                "content": "\n".join(slice_lines),
            }
        )

    def _tool_write_file(self, args: dict[str, Any]) -> str:
        path = self._resolve_path(str(args.get("path") or ""))
        content = str(args.get("content") or "")
        create_dirs = bool(args.get("create_dirs") or False)
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif not path.parent.exists():
            return _json_dump(
                {
                    "ok": False,
                    "error": f"parent directory does not exist: {path.parent}",
                }
            )
        path.write_text(content, encoding="utf-8")
        return _json_dump(
            {
                "ok": True,
                "path": str(path.relative_to(self.workspace_path)),
                "bytes": len(content.encode("utf-8")),
            }
        )

    def _tool_bash(self, args: dict[str, Any]) -> str:
        command = str(args.get("command") or "").strip()
        timeout_seconds = max(1, int(args.get("timeout_seconds") or 120))
        if not command:
            return _json_dump({"ok": False, "error": "command is required"})
        safety_error = _validate_bash_command(command)
        if safety_error is not None:
            return _json_dump(
                {
                    "ok": False,
                    "error": safety_error,
                    "reason_code": "security_concern",
                }
            )
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(self.workspace_path),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return _json_dump(
            {
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": _trim_text(completed.stdout or "", 4000),
                "stderr": _trim_text(completed.stderr or "", 4000),
            }
        )

    def _tool_grep(self, args: dict[str, Any]) -> str:
        pattern = str(args.get("pattern") or "").strip()
        relative_path = str(args.get("path") or ".").strip() or "."
        glob_pattern = str(args.get("glob") or "").strip()
        max_results = max(1, int(args.get("max_results") or 200))
        if not pattern:
            return _json_dump({"ok": False, "error": "pattern is required"})
        target_path = self._resolve_path(relative_path)
        if shutil.which("rg") is None:
            return _json_dump({"ok": False, "error": "rg is not installed"})
        command = [
            "rg",
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            "--max-count",
            str(max_results),
            pattern,
            str(target_path),
        ]
        if glob_pattern:
            command.extend(["-g", glob_pattern])
        completed = subprocess.run(
            command,
            cwd=str(self.workspace_path),
            capture_output=True,
            text=True,
            check=False,
        )
        return _json_dump(
            {
                "ok": completed.returncode in {0, 1},
                "returncode": completed.returncode,
                "matches": _trim_text(completed.stdout or "", 6000),
                "stderr": _trim_text(completed.stderr or "", 2000),
            }
        )

    def _tool_list_files(self, args: dict[str, Any]) -> str:
        relative_path = str(args.get("path") or ".").strip() or "."
        max_results = max(1, int(args.get("max_results") or 300))
        target_path = self._resolve_path(relative_path)
        command: list[str]
        if shutil.which("rg") is not None:
            command = ["rg", "--files", str(target_path)]
        else:
            command = ["find", str(target_path), "-type", "f"]
        completed = subprocess.run(
            command,
            cwd=str(self.workspace_path),
            capture_output=True,
            text=True,
            check=False,
        )
        files = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
        normalized: list[str] = []
        for path_text in files[:max_results]:
            try:
                rel = str(Path(path_text).resolve().relative_to(self.workspace_path))
            except Exception:
                rel = path_text
            normalized.append(rel)
        return _json_dump(
            {
                "ok": completed.returncode == 0,
                "count": len(normalized),
                "files": normalized,
                "stderr": _trim_text(completed.stderr or "", 1200),
            }
        )

    def _resolve_path(self, raw_path: str) -> Path:
        if not raw_path:
            raise ValueError("path is required")
        path = Path(raw_path)
        if not path.is_absolute():
            path = (self.workspace_path / path).resolve()
        else:
            path = path.resolve()
        if path != self.workspace_path and self.workspace_path not in path.parents:
            raise ValueError(f"path escapes workspace: {raw_path}")
        return path


class OpenAIModelClient:
    def __init__(self) -> None:
        self.base_url = (
            os.environ.get("STARDRIFTER_OPENAI_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = (
            os.environ.get("STARDRIFTER_OPENAI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        ).strip()

    def complete_with_tools(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> ModelTurn:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.1,
            "max_tokens": max_output_tokens,
        }
        data = self._post_json(
            "/chat/completions",
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        choice = ((data.get("choices") or [{}])[0])
        message = choice.get("message") or {}
        content = str(message.get("content") or "")
        tool_calls_raw = message.get("tool_calls") or []
        invocations: list[ToolInvocation] = []
        for index, call in enumerate(tool_calls_raw):
            function_payload = call.get("function") or {}
            name = str(function_payload.get("name") or "")
            call_id = str(call.get("id") or f"tool_call_{index}")
            arguments = _coerce_json_object(function_payload.get("arguments"))
            invocations.append(
                ToolInvocation(call_id=call_id, name=name, arguments=arguments)
            )
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }
        if tool_calls_raw:
            assistant_message["tool_calls"] = tool_calls_raw
        return ModelTurn(
            text=content,
            tool_calls=tuple(invocations),
            assistant_message=assistant_message,
        )

    def complete_text(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_output_tokens,
        }
        data = self._post_json(
            "/chat/completions",
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        choice = ((data.get("choices") or [{}])[0])
        message = choice.get("message") or {}
        return str(message.get("content") or "").strip()

    def _post_json(
        self,
        path: str,
        *,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise LLMRequestError(
                "OPENAI_API_KEY is required for LLM executor",
                reason_code="credential_required",
                retryable=False,
            )
        return _http_post_json(
            url=f"{self.base_url}{path}",
            payload=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout_seconds=timeout_seconds,
        )


class AnthropicModelClient:
    def __init__(self) -> None:
        self.base_url = (
            os.environ.get("STARDRIFTER_ANTHROPIC_BASE_URL")
            or os.environ.get("ANTHROPIC_BASE_URL")
            or "https://api.anthropic.com/v1"
        ).rstrip("/")
        self.api_key = (
            os.environ.get("STARDRIFTER_ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or ""
        ).strip()

    def complete_with_tools(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> ModelTurn:
        system_prompt, anthropic_messages = _convert_messages_for_anthropic(messages)
        payload = {
            "model": model,
            "system": system_prompt,
            "messages": anthropic_messages,
            "tools": _convert_tools_for_anthropic(tools),
            "max_tokens": max_output_tokens,
            "temperature": 0.1,
        }
        data = self._post_json(payload=payload, timeout_seconds=timeout_seconds)
        blocks = data.get("content") or []
        text_parts: list[str] = []
        invocations: list[ToolInvocation] = []
        assistant_tool_calls: list[dict[str, Any]] = []
        for index, block in enumerate(blocks):
            block_type = str(block.get("type") or "")
            if block_type == "text":
                text_parts.append(str(block.get("text") or ""))
                continue
            if block_type != "tool_use":
                continue
            name = str(block.get("name") or "")
            call_id = str(block.get("id") or f"tool_call_{index}")
            arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
            invocations.append(
                ToolInvocation(call_id=call_id, name=name, arguments=arguments)
            )
            assistant_tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            )
        text = "\n".join(part for part in text_parts if part).strip()
        assistant_message: dict[str, Any] = {"role": "assistant", "content": text}
        if assistant_tool_calls:
            assistant_message["tool_calls"] = assistant_tool_calls
        return ModelTurn(
            text=text,
            tool_calls=tuple(invocations),
            assistant_message=assistant_message,
        )

    def complete_text(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> str:
        system_prompt, anthropic_messages = _convert_messages_for_anthropic(messages)
        payload = {
            "model": model,
            "system": system_prompt,
            "messages": anthropic_messages,
            "max_tokens": max_output_tokens,
            "temperature": 0,
        }
        data = self._post_json(payload=payload, timeout_seconds=timeout_seconds)
        blocks = data.get("content") or []
        text_parts = [str(block.get("text") or "") for block in blocks if block.get("type") == "text"]
        return "\n".join(part for part in text_parts if part).strip()

    def _post_json(self, *, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
        if not self.api_key:
            raise LLMRequestError(
                "ANTHROPIC_API_KEY is required for LLM executor",
                reason_code="credential_required",
                retryable=False,
            )
        return _http_post_json(
            url=f"{self.base_url}/messages",
            payload=payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout_seconds=timeout_seconds,
        )


class IntelligentExecutor:
    def __init__(
        self,
        *,
        repo_root: Path,
        config: IntelligentExecutorConfig,
        fallback_command_template: str,
        model_client: ToolModelClient | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.config = config
        self.fallback_command_template = fallback_command_template
        self.context_engine = TaskContextEngine(
            repo_root=self.repo_root,
            max_chars=config.context_chars,
        )
        self.model_client = model_client or _build_model_client(config.provider)

    def __call__(
        self,
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
        heartbeat: Any | None = None,
    ) -> ExecutionResult:
        started_at = time.perf_counter()
        effective_workspace = (workspace_path or self.repo_root).resolve()
        journal: list[str] = []

        for attempt in range(self.config.max_retries + 1):
            try:
                payload = self._run_loop(
                    work_item=work_item,
                    workspace_path=effective_workspace,
                    execution_context=execution_context,
                    journal=journal,
                    heartbeat=heartbeat,
                )
                return self._build_execution_result(
                    payload=payload,
                    journal=journal,
                    started_at=started_at,
                )
            except LLMRequestError as exc:
                if attempt < self.config.max_retries and exc.retryable:
                    backoff = self.config.retry_backoff_seconds * (2**attempt)
                    if callable(heartbeat):
                        heartbeat()
                    time.sleep(backoff)
                    continue
                return self._build_failed_result(
                    reason_code=exc.reason_code,
                    summary=str(exc),
                    journal=journal,
                    started_at=started_at,
                )
            except Exception as exc:
                return self._build_failed_result(
                    reason_code="tooling_error",
                    summary=f"intelligent executor failed: {exc}",
                    journal=journal,
                    started_at=started_at,
                )

        return self._build_failed_result(
            reason_code="upstream_api_error",
            summary="intelligent executor exhausted retries",
            journal=journal,
            started_at=started_at,
        )

    def _run_loop(
        self,
        *,
        work_item: WorkItem,
        workspace_path: Path,
        execution_context: ExecutionContext | None,
        journal: list[str],
        heartbeat: Any | None,
    ) -> dict[str, Any]:
        task_context = self.context_engine.build_context(
            work_item=work_item,
            execution_context=execution_context,
            workspace_path=workspace_path,
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": _build_executor_system_prompt(),
            },
            {
                "role": "user",
                "content": (
                    "Execute this task in the repository using tools.\n"
                    "Return one terminal JSON object only when done.\n\n"
                    f"{task_context}"
                ),
            },
        ]
        toolbox = WorkspaceToolbox(workspace_path=workspace_path)
        signature_counts: dict[str, int] = {}

        for _ in range(self.config.max_turns):
            if callable(heartbeat):
                heartbeat()
            turn = self.model_client.complete_with_tools(
                model=self.config.model,
                messages=messages,
                tools=_executor_tools_schema(),
                timeout_seconds=self.config.timeout_seconds,
                max_output_tokens=self.config.max_output_tokens,
            )
            messages.append(turn.assistant_message)

            if turn.tool_calls:
                signature = _tool_signature(turn.tool_calls)
                signature_counts[signature] = signature_counts.get(signature, 0) + 1
                if signature_counts[signature] >= self.config.tool_loop_hard_limit:
                    return {
                        "outcome": "blocked",
                        "reason_code": "tool_loop_detected",
                        "summary": "LLM repeated identical tool calls; loop protection triggered.",
                        "decision_required": False,
                    }

                for call in turn.tool_calls:
                    try:
                        tool_output = toolbox.run(call)
                    except Exception as exc:
                        tool_output = _json_dump(
                            {
                                "ok": False,
                                "error": f"tool execution failed: {exc}",
                                "reason_code": "tooling_error",
                            }
                        )
                    journal.append(
                        f"tool={call.name} args={_trim_text(_json_dump(call.arguments), 240)} result={_trim_text(tool_output, 480)}"
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.call_id,
                            "name": call.name,
                            "content": tool_output,
                        }
                    )
                    if callable(heartbeat):
                        heartbeat()
                self._compact_messages(messages=messages, journal=journal)
                continue

            payload = _extract_terminal_payload(turn.text)
            if payload is None:
                return {
                    "outcome": "blocked",
                    "reason_code": "invalid-result-payload",
                    "summary": _trim_text(
                        f"LLM did not return terminal JSON. raw={turn.text}",
                        500,
                    ),
                    "decision_required": False,
                }
            payload = _normalize_terminal_payload(payload)
            payload.setdefault("summary", _compact_journal(journal) or "LLM execution completed")
            payload.setdefault("decision_required", payload.get("outcome") == "needs_decision")
            payload["execution_journal"] = _compact_journal(journal)
            return payload

        return {
            "outcome": "blocked",
            "reason_code": "timeout",
            "summary": f"LLM executor reached max turns ({self.config.max_turns})",
            "decision_required": False,
        }

    def _compact_messages(self, *, messages: list[dict[str, Any]], journal: list[str]) -> None:
        total_chars = sum(len(_json_dump(message)) for message in messages)
        if total_chars <= self.config.context_window_chars:
            return
        if len(messages) <= self.config.keep_recent_messages + 1:
            return
        system_prompt = messages[0]
        recent = messages[-self.config.keep_recent_messages :]
        summary_message = {
            "role": "user",
            "content": (
                "Execution history summary (compressed):\n"
                f"{_compact_journal(journal)}"
            ),
        }
        messages[:] = [system_prompt, summary_message, *recent]

    def _build_execution_result(
        self,
        *,
        payload: dict[str, Any],
        journal: list[str],
        started_at: float,
    ) -> ExecutionResult:
        outcome = str(payload.get("outcome") or "blocked").strip().lower()
        success = outcome in {"done", "already_satisfied"}
        reason_code = str(payload.get("reason_code") or "").strip() or None
        elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        summary = str(payload.get("summary") or "").strip() or _compact_journal(journal)
        decision_required = bool(payload.get("decision_required") or outcome == "needs_decision")
        if outcome == "needs_decision" and not reason_code:
            reason_code = "needs_decision"

        return ExecutionResult(
            success=success,
            summary=summary,
            command_digest=f"llm-executor:{self.config.provider}:{self.config.model}",
            exit_code=0 if success else 1,
            elapsed_ms=elapsed_ms,
            stdout_digest=_trim_text(_compact_journal(journal), 1800),
            stderr_digest="",
            blocked_reason=reason_code,
            decision_required=decision_required,
            result_payload_json=payload,
        )

    def _build_failed_result(
        self,
        *,
        reason_code: str,
        summary: str,
        journal: list[str],
        started_at: float,
    ) -> ExecutionResult:
        elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        payload = {
            "outcome": "blocked",
            "reason_code": reason_code,
            "summary": summary,
            "decision_required": reason_code in {"credential_required", "permission_required"},
            "execution_journal": _compact_journal(journal),
        }
        return ExecutionResult(
            success=False,
            summary=summary,
            command_digest=f"llm-executor:{self.config.provider}:{self.config.model}",
            exit_code=1,
            elapsed_ms=elapsed_ms,
            stdout_digest=_trim_text(_compact_journal(journal), 1800),
            stderr_digest="",
            blocked_reason=reason_code,
            decision_required=bool(payload["decision_required"]),
            result_payload_json=payload,
        )


class LLMVerifier:
    """Adaptive verifier: run tests, then let LLM review diff against criteria."""

    def __init__(
        self,
        *,
        repo_root: Path,
        command_template: str,
        check_type: str,
        config: IntelligentVerifierConfig,
        model_client: ToolModelClient | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.command_template = command_template
        self.check_type = check_type
        self.config = config
        self.context_engine = TaskContextEngine(
            repo_root=self.repo_root,
            max_chars=config.context_chars,
        )
        self.model_client = model_client or _build_model_client(config.provider)

    def __call__(
        self,
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> VerificationEvidence:
        effective_workspace = (workspace_path or self.repo_root).resolve()
        started_at = time.perf_counter()

        test_completed, test_elapsed_ms = _run_verifier_command_if_enabled(
            command_template=self.command_template,
            work_item=work_item,
            workdir=effective_workspace,
            execution_context=execution_context,
        )
        diff_snapshot = _collect_diff_snapshot(
            workdir=effective_workspace,
            max_chars=self.config.diff_chars,
        )
        task_context = self.context_engine.build_context(
            work_item=work_item,
            execution_context=execution_context,
            workspace_path=effective_workspace,
        )
        llm_summary = ""
        llm_passed = test_completed.returncode == 0

        prompt = _build_verifier_prompt(
            task_context=task_context,
            test_returncode=test_completed.returncode,
            test_stdout=test_completed.stdout or "",
            test_stderr=test_completed.stderr or "",
            diff_snapshot=diff_snapshot,
            check_type=self.check_type,
        )
        try:
            llm_text = self.model_client.complete_text(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": _build_verifier_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                timeout_seconds=self.config.timeout_seconds,
                max_output_tokens=self.config.max_output_tokens,
            )
            llm_payload = _extract_terminal_payload(llm_text) or _coerce_json_object(llm_text)
            if isinstance(llm_payload, dict) and "passed" in llm_payload:
                llm_passed = bool(llm_payload.get("passed"))
                llm_summary = str(llm_payload.get("summary") or "").strip()
            else:
                llm_summary = _trim_text(llm_text, 500)
        except Exception as exc:
            llm_summary = f"LLM verifier unavailable: {exc}"

        final_passed = bool(test_completed.returncode == 0 and llm_passed)
        elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        output_digest = _trim_text(
            "\n".join(
                part
                for part in [
                    f"test_returncode={test_completed.returncode}",
                    llm_summary,
                    _trim_text(diff_snapshot, 800),
                ]
                if part
            ),
            2000,
        )

        command = (
            f"{self.check_type}:{self.command_template}"
            f"|llm:{self.config.provider}:{self.config.model}"
        )
        return VerificationEvidence(
            work_id=work_item.id,
            check_type=f"{self.check_type}+llm",
            command=command,
            passed=final_passed,
            output_digest=output_digest,
            exit_code=test_completed.returncode,
            elapsed_ms=max(elapsed_ms, test_elapsed_ms),
            stdout_digest=_trim_text(test_completed.stdout or "", 1200),
            stderr_digest=_trim_text(test_completed.stderr or "", 1200),
        )


def build_intelligent_executor(
    *,
    command_template: str,
    workdir: Path,
) -> Any:
    config = IntelligentExecutorConfig.from_env()
    executor = IntelligentExecutor(
        repo_root=workdir,
        config=config,
        fallback_command_template=command_template,
    )
    return executor


def build_adaptive_verifier(
    *,
    command_template: str,
    workdir: Path,
    check_type: str,
) -> Any:
    config = IntelligentVerifierConfig.from_env()
    verifier = LLMVerifier(
        repo_root=workdir,
        command_template=command_template,
        check_type=check_type,
        config=config,
    )
    return verifier


def llm_executor_enabled(*, command_template: str) -> bool:
    return _is_truthy(os.environ.get("STARDRIFTER_ENABLE_LLM_EXECUTOR")) or command_template.strip().lower().startswith(
        "llm://"
    )


def llm_verifier_enabled(*, command_template: str) -> bool:
    return _is_truthy(os.environ.get("STARDRIFTER_ENABLE_LLM_VERIFIER")) or command_template.strip().lower().startswith(
        "llm://"
    )


def _executor_tools_schema() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read file contents from workspace by line range.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Overwrite a file with provided content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "create_dirs": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Execute a shell command in workspace and return output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout_seconds": {"type": "integer"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "grep",
                "description": "Search repository text using ripgrep.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                        "glob": {"type": "string"},
                        "max_results": {"type": "integer"},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files under a directory for quick navigation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_results": {"type": "integer"},
                    },
                },
            },
        },
    ]


def _build_executor_system_prompt() -> str:
    return (
        "You are the task execution agent for a PostgreSQL-backed control plane.\n"
        "You may use tools to inspect and edit files and run commands.\n"
        "When the task is complete, return exactly one JSON object with:"
        " outcome, summary, reason_code, decision_required.\n"
        "Allowed outcome values: done, already_satisfied, blocked, needs_decision.\n"
        "Rules:\n"
        "1) Keep edits minimal and deterministic.\n"
        "2) Do not ask the human for clarification. If required, return needs_decision.\n"
        "3) Prefer direct implementation over open-ended exploration.\n"
        "4) The final answer MUST be JSON only, no markdown fence, no extra text.\n"
    )


def _build_verifier_system_prompt() -> str:
    return (
        "You are a strict verification reviewer.\n"
        "Assess whether changes satisfy acceptance criteria based on test output and git diff.\n"
        "Return a single JSON object with keys: passed(boolean), summary(string), risk_codes(array).\n"
        "No markdown, no extra commentary."
    )


def _build_verifier_prompt(
    *,
    task_context: str,
    test_returncode: int,
    test_stdout: str,
    test_stderr: str,
    diff_snapshot: str,
    check_type: str,
) -> str:
    return (
        f"check_type: {check_type}\n"
        f"test_returncode: {test_returncode}\n\n"
        f"task_context:\n{task_context}\n\n"
        f"test_stdout:\n{_trim_text(test_stdout, 2400)}\n\n"
        f"test_stderr:\n{_trim_text(test_stderr, 1200)}\n\n"
        f"git_diff:\n{diff_snapshot}\n\n"
        "Decide pass/fail. If any acceptance criterion appears unmet, set passed=false."
    )


def _run_verifier_command_if_enabled(
    *,
    command_template: str,
    work_item: WorkItem,
    workdir: Path,
    execution_context: ExecutionContext | None,
) -> tuple[subprocess.CompletedProcess[str], int]:
    normalized = command_template.strip().lower()
    if not command_template.strip() or normalized.startswith("llm://"):
        completed = subprocess.CompletedProcess(
            args=command_template,
            returncode=0,
            stdout="",
            stderr="",
        )
        return completed, 0

    env = os.environ.copy()
    env.update(
        {
            "STARDRIFTER_WORK_ID": work_item.id,
            "STARDRIFTER_WORK_TITLE": work_item.title,
            "STARDRIFTER_WORK_LANE": work_item.lane,
            "STARDRIFTER_WORK_WAVE": work_item.wave,
            "STARDRIFTER_PROJECT_DIR": str(workdir),
        }
    )
    if execution_context is not None:
        env["STARDRIFTER_EXECUTION_CONTEXT_JSON"] = _json_dump(
            {
                "work_id": execution_context.work_id,
                "title": execution_context.title,
                "lane": execution_context.lane,
                "wave": execution_context.wave,
                "repo": execution_context.repo,
                "source_issue_number": execution_context.source_issue_number,
                "canonical_story_issue_number": execution_context.canonical_story_issue_number,
                "story_issue_numbers": list(execution_context.story_issue_numbers),
                "planned_paths": list(execution_context.planned_paths),
                "workspace_path": execution_context.workspace_path,
                "project_dir": execution_context.project_dir,
            }
        )

    started_at = time.perf_counter()
    completed = subprocess.run(
        command_template,
        shell=True,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    return completed, elapsed_ms


def _collect_diff_snapshot(*, workdir: Path, max_chars: int) -> str:
    commands = [
        ["git", "-C", str(workdir), "diff", "--name-only"],
        ["git", "-C", str(workdir), "diff", "--stat"],
        ["git", "-C", str(workdir), "diff"],
    ]
    parts: list[str] = []
    for command in commands:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        output = (completed.stdout or "").strip()
        if output:
            parts.append(output)
    return _trim_text("\n\n".join(parts), max_chars)


def _extract_checklist_from_dod(dod_json: Any) -> list[str]:
    if isinstance(dod_json, dict):
        values = dod_json.get("checklist") or dod_json.get("acceptance") or []
        if isinstance(values, list):
            return [str(item).strip() for item in values if str(item).strip()]
        return []
    if isinstance(dod_json, list):
        return [str(item).strip() for item in dod_json if str(item).strip()]
    return []


def _extract_markdown_section(body: str, headings: set[str]) -> str:
    matches = list(MARKDOWN_SECTION_RE.finditer(body or ""))
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        if heading not in headings:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        return (body[start:end] or "").strip()
    return ""


def _http_post_json(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib_request.Request(
        url,
        data=_json_dump(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        reason_code, retryable = _classify_http_error(exc.code)
        raise LLMRequestError(
            _trim_text(f"LLM API HTTP {exc.code}: {raw}", 900),
            status_code=exc.code,
            reason_code=reason_code,
            retryable=retryable,
        ) from exc
    except urllib_error.URLError as exc:
        raise LLMRequestError(
            f"LLM API network error: {exc}",
            reason_code="resource_temporarily_unavailable",
            retryable=True,
        ) from exc
    except TimeoutError as exc:
        raise LLMRequestError(
            f"LLM API timeout: {exc}",
            reason_code="timeout",
            retryable=True,
        ) from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMRequestError(
            f"LLM API returned invalid JSON: {_trim_text(body, 400)}",
            reason_code="invalid-result-payload",
            retryable=False,
        ) from exc
    if not isinstance(data, dict):
        raise LLMRequestError(
            "LLM API returned non-object response",
            reason_code="invalid-result-payload",
            retryable=False,
        )
    return data


def _classify_http_error(status_code: int) -> tuple[str, bool]:
    if status_code in {401, 403}:
        return "credential_required", False
    if status_code in {408, 429, 500, 502, 503, 504}:
        return "upstream_api_error", True
    return "upstream_api_error", False


def _extract_terminal_payload(raw_text: str) -> dict[str, Any] | None:
    raw = raw_text.strip()
    candidate = _coerce_json_object(raw)
    if candidate:
        return candidate

    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        return None
    maybe_json = raw[first_brace : last_brace + 1]
    candidate = _coerce_json_object(maybe_json)
    if candidate:
        return candidate
    return None


def _normalize_terminal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    outcome = str(normalized.get("outcome") or "").strip().lower()
    if outcome not in TERMINAL_OUTCOMES:
        return {
            "outcome": "blocked",
            "reason_code": "unsupported-outcome",
            "summary": f"unsupported outcome: {outcome or 'missing'}",
            "decision_required": False,
        }
    normalized["outcome"] = outcome
    if "decision_required" not in normalized:
        normalized["decision_required"] = outcome == "needs_decision"
    if outcome in {"blocked", "needs_decision"} and not normalized.get("reason_code"):
        normalized["reason_code"] = "llm_reported_blocked"
    return normalized


def _coerce_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[truncated]"


def _tool_signature(calls: tuple[ToolInvocation, ...]) -> str:
    material = [
        {
            "name": call.name,
            "arguments": call.arguments,
        }
        for call in calls
    ]
    material.sort(key=lambda item: (item["name"], _json_dump(item["arguments"])))
    return hashlib.sha1(_json_dump(material).encode("utf-8")).hexdigest()[:12]


def _compact_journal(journal: list[str]) -> str:
    if not journal:
        return ""
    if len(journal) <= 12:
        return "\n".join(journal)
    head = journal[:4]
    tail = journal[-8:]
    omitted = len(journal) - len(head) - len(tail)
    return "\n".join([*head, f"... {omitted} steps omitted ...", *tail])


def _build_model_client(provider: str) -> ToolModelClient:
    normalized = provider.strip().lower()
    if normalized == "anthropic":
        return AnthropicModelClient()
    return OpenAIModelClient()


def _safe_git_diff_name_only(workspace_path: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(workspace_path), "diff", "--name-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    paths: list[str] = []
    for line in (completed.stdout or "").splitlines():
        normalized = line.strip()
        if normalized and normalized not in paths:
            paths.append(normalized)
    return paths[:30]


def _convert_messages_for_anthropic(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    result: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        content = message.get("content")
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content)
            continue
        if role == "tool":
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(message.get("tool_call_id") or ""),
                            "content": str(content or ""),
                        }
                    ],
                }
            )
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            for call in message.get("tool_calls") or []:
                function_payload = call.get("function") or {}
                arguments = _coerce_json_object(function_payload.get("arguments"))
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(call.get("id") or ""),
                        "name": str(function_payload.get("name") or ""),
                        "input": arguments,
                    }
                )
            if not blocks:
                blocks.append({"type": "text", "text": ""})
            result.append({"role": "assistant", "content": blocks})
            continue

        text_content = str(content or "")
        result.append(
            {
                "role": "user" if role != "assistant" else "assistant",
                "content": [{"type": "text", "text": text_content}],
            }
        )
    return "\n\n".join(system_parts), result


def _convert_tools_for_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        function_payload = tool.get("function") or {}
        converted.append(
            {
                "name": str(function_payload.get("name") or ""),
                "description": str(function_payload.get("description") or ""),
                "input_schema": function_payload.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return converted


def _is_truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _validate_bash_command(command: str) -> str | None:
    if _is_truthy(os.environ.get("STARDRIFTER_LLM_BASH_ALLOW_UNSAFE")):
        return None
    lowered = command.lower()
    deny_patterns = _load_bash_deny_patterns()
    for pattern in deny_patterns:
        if re.search(pattern, lowered):
            return f"command blocked by safety policy pattern: {pattern}"
    allow_patterns = _load_bash_allow_patterns()
    if allow_patterns:
        for pattern in allow_patterns:
            if re.search(pattern, lowered):
                return None
        return "command does not match required allowlist patterns"
    return None


def _load_bash_deny_patterns() -> list[str]:
    from_env = (os.environ.get("STARDRIFTER_LLM_BASH_DENY_PATTERNS") or "").strip()
    if from_env:
        return [part.strip() for part in from_env.split(",") if part.strip()]
    return [
        r"(^|\s)sudo(\s|$)",
        r"rm\s+-rf(\s|$)",
        r"(^|\s)mkfs(\.|\s)",
        r"(^|\s)dd\s+if=",
        r"(^|\s)shutdown(\s|$)",
        r"(^|\s)reboot(\s|$)",
        r"(^|\s)poweroff(\s|$)",
        r":\(\)\s*\{\s*:\|:\s*&\s*\};\s*:",
    ]


def _load_bash_allow_patterns() -> list[str]:
    from_env = (os.environ.get("STARDRIFTER_LLM_BASH_ALLOW_PATTERNS") or "").strip()
    if not from_env:
        return []
    return [part.strip() for part in from_env.split(",") if part.strip()]


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value
