"""
Notification Webhook Module

异步通知 Webhook 模块。
支持 Discord、Slack、Telegram 等渠道发送通知。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from .models import NotificationRequest


@dataclass
class WebhookConfig:
    """Webhook 配置"""

    discord_webhook_url: str | None = None
    slack_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @classmethod
    def from_env(cls) -> "WebhookConfig":
        """从环境变量加载配置"""
        return cls(
            discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL"),
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
        )


class NotificationWebhook:
    """通知 Webhook 发送器"""

    def __init__(self, config: WebhookConfig | None = None, dsn: str | None = None):
        self.config = config or WebhookConfig.from_env()
        self.dsn = dsn

    def send(
        self,
        notification_type: Literal[
            "human_decision_required",
            "retry_resolved",
            "story_complete",
            "epic_blocked",
            "milestone_reached",
        ],
        message: str,
        channel: Literal["discord", "slack", "telegram"] | None = None,
        subject: str | None = None,
        work_id: str | None = None,
        story_issue_number: int | None = None,
        epic_issue_number: int | None = None,
        metadata: dict | None = None,
    ) -> bool:
        """
        发送通知

        Args:
            notification_type: 通知类型
            message: 消息内容
            channel: 渠道（默认第一个可用的）
            subject: 主题
            work_id: 工作项 ID
            story_issue_number: Story issue 编号
            epic_issue_number: Epic issue 编号
            metadata: 元数据

        Returns:
            是否发送成功
        """
        # 选择渠道
        if channel is None:
            if self.config.discord_webhook_url:
                channel = "discord"
            elif self.config.slack_webhook_url:
                channel = "slack"
            elif self.config.telegram_bot_token and self.config.telegram_chat_id:
                channel = "telegram"
            else:
                print(
                    f"[NOTIFICATION] No channel configured, logging to stdout: {message}",
                )
                return True

        # 构建通知
        subject = subject or self._default_subject(notification_type)
        formatted_message = self._format_message(
            notification_type,
            subject,
            message,
            work_id,
            story_issue_number,
            epic_issue_number,
        )

        # 发送
        success = False
        if channel == "discord" and self.config.discord_webhook_url:
            success = self._send_discord(formatted_message)
        elif channel == "slack" and self.config.slack_webhook_url:
            success = self._send_slack(formatted_message)
        elif channel == "telegram" and self.config.telegram_bot_token:
            success = self._send_telegram(formatted_message)

        # 记录到数据库
        if self.dsn and success:
            self._queue_notification(
                notification_type=notification_type,
                channel=channel,
                subject=subject,
                message=message,
                work_id=work_id,
                story_issue_number=story_issue_number,
                epic_issue_number=epic_issue_number,
                metadata=metadata,
                status="sent" if success else "failed",
            )

        return success

    def notify_human_decision_required(
        self,
        work_id: str,
        reason: str,
        context_summary: str,
        story_issue_number: int | None = None,
    ) -> bool:
        """通知需要人工决策"""
        message = (
            f"🔴 **需要人工决策**\n\n"
            f"**Work ID**: `{work_id}`\n"
            f"**原因**: {reason}\n\n"
            f"**上下文摘要**:\n{context_summary}"
        )
        if story_issue_number:
            message += f"\n**Story**: #{story_issue_number}"

        return self.send(
            notification_type="human_decision_required",
            message=message,
            subject=f"🔴 需要人工决策 - Work #{work_id}",
            work_id=work_id,
            story_issue_number=story_issue_number,
        )

    def notify_retry_resolved(
        self,
        work_id: str,
        summary: str,
    ) -> bool:
        """通知重试成功"""
        message = (
            f"✅ **重试成功**\n\n"
            f"**Work ID**: `{work_id}`\n"
            f"**摘要**: {summary}"
        )

        return self.send(
            notification_type="retry_resolved",
            message=message,
            subject=f"✅ 重试成功 - Work #{work_id}",
            work_id=work_id,
        )

    def notify_story_complete(
        self,
        story_issue_number: int,
        completed_task_count: int,
    ) -> bool:
        """通知 Story 完成"""
        message = (
            f"🎉 **Story 完成**\n\n"
            f"**Story**: #{story_issue_number}\n"
            f"**完成任务数**: {completed_task_count}"
        )

        return self.send(
            notification_type="story_complete",
            message=message,
            subject=f"🎉 Story #{story_issue_number} 完成",
            story_issue_number=story_issue_number,
        )

    def notify_epic_blocked(
        self,
        epic_issue_number: int,
        blocked_reason: str,
        blocked_story_count: int,
    ) -> bool:
        """通知 Epic 阻塞"""
        message = (
            f"⚠️ **Epic 阻塞**\n\n"
            f"**Epic**: #{epic_issue_number}\n"
            f"**原因**: {blocked_reason}\n"
            f"**阻塞 Story 数**: {blocked_story_count}"
        )

        return self.send(
            notification_type="epic_blocked",
            message=message,
            subject=f"⚠️ Epic #{epic_issue_number} 阻塞",
            epic_issue_number=epic_issue_number,
        )

    def _default_subject(
        self,
        notification_type: str,
    ) -> str:
        """默认主题"""
        subjects = {
            "human_decision_required": "🔴 需要人工决策",
            "retry_resolved": "✅ 重试成功",
            "story_complete": "🎉 Story 完成",
            "epic_blocked": "⚠️ Epic 阻塞",
            "milestone_reached": "📍 达成里程碑",
        }
        return subjects.get(notification_type, "📢 通知")

    def _format_message(
        self,
        notification_type: str,
        subject: str,
        message: str,
        work_id: str | None,
        story_issue_number: int | None,
        epic_issue_number: int | None,
    ) -> str:
        """格式化消息"""
        parts = [subject, ""]
        parts.append(message)

        # 添加链接
        links = []
        if work_id:
            links.append(f"Work: `{work_id}`")
        if story_issue_number:
            links.append(f"Story: #{story_issue_number}")
        if epic_issue_number:
            links.append(f"Epic: #{epic_issue_number}")

        if links:
            parts.append("")
            parts.append(" | ".join(links))

        return "\n".join(parts)

    def _send_discord(self, message: str) -> bool:
        """发送 Discord 通知"""
        try:
            import urllib.request

            payload = {"content": message}
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.config.discord_webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 204
        except Exception as e:
            print(f"[DISCORD] Failed to send notification: {e}")
            return False

    def _send_slack(self, message: str) -> bool:
        """发送 Slack 通知"""
        try:
            import urllib.request

            payload = {"text": message}
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.config.slack_webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except Exception as e:
            print(f"[SLACK] Failed to send notification: {e}")
            return False

    def _send_telegram(self, message: str) -> bool:
        """发送 Telegram 通知"""
        try:
            import urllib.request

            if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
                return False

            url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.config.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except Exception as e:
            print(f"[TELEGRAM] Failed to send notification: {e}")
            return False

    def _queue_notification(
        self,
        *,
        notification_type: str,
        channel: str,
        subject: str,
        message: str,
        work_id: str | None,
        story_issue_number: int | None,
        epic_issue_number: int | None,
        metadata: dict | None,
        status: str,
    ) -> None:
        """记录通知到数据库"""
        try:
            with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO notification_queue (
                            notification_type,
                            channel,
                            recipient,
                            subject,
                            message,
                            work_id,
                            story_issue_number,
                            epic_issue_number,
                            metadata,
                            status,
                            sent_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            notification_type,
                            channel,
                            None,
                            subject,
                            message,
                            work_id,
                            story_issue_number,
                            epic_issue_number,
                            metadata or {},
                            status,
                            datetime.utcnow() if status == "sent" else None,
                        ),
                    )
                conn.commit()
        except Exception as e:
            print(f"[DB] Failed to queue notification: {e}")


# =============================================================================
# 便捷函数
# =============================================================================


def send_notification(
    *,
    dsn: str,
    notification_type: str,
    message: str,
    channel: str | None = None,
    work_id: str | None = None,
    story_issue_number: int | None = None,
    epic_issue_number: int | None = None,
) -> bool:
    """
    发送通知的便捷函数

    Args:
        dsn: 数据库连接字符串
        notification_type: 通知类型
        message: 消息内容
        channel: 渠道
        work_id: 工作项 ID
        story_issue_number: Story issue 编号
        epic_issue_number: Epic issue 编号

    Returns:
        是否发送成功
    """
    webhook = NotificationWebhook(dsn=dsn)
    return webhook.send(
        notification_type=notification_type,
        message=message,
        channel=channel,
        work_id=work_id,
        story_issue_number=story_issue_number,
        epic_issue_number=epic_issue_number,
    )
