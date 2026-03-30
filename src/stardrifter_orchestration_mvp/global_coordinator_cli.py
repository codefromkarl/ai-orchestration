"""
Global Coordinator CLI - 多项目协调器命令行入口

使用示例:
    python -m stardrifter_orchestration_mvp.global_coordinator_cli \\
        --max-global-parallel 10 \\
        --repos repo-a repo-b repo-c \\
        --base-quota 2 \\
        --elastic-pool-size 8 \\
        --dsn postgresql://user:pass@localhost:5432/db
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

import psycopg

from .global_coordinator import GlobalCoordinator
from .agent_pool_manager import AgentPoolManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="多项目协调器 - 管理和协调多个 Repo 的并行执行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 启动多项目协调器，最大并行 10 个任务
  python -m stardrifter_orchestration_mvp.global_coordinator_cli \\
    --max-global-parallel 10 \\
    --repos repo-a repo-b repo-c \\
    --dsn postgresql://user:pass@localhost:5432/db

  # 配置基础配额和弹性池
  python -m stardrifter_orchestration_mvp.global_coordinator_cli \\
    --max-global-parallel 12 \\
    --repos repo-a repo-b \\
    --base-quota 2 \\
    --elastic-pool-size 8 \\
    --dsn postgresql://user:pass@localhost:5432/db
        """,
    )

    # 必需参数
    parser.add_argument(
        "--dsn",
        type=str,
        required=True,
        help="数据库连接字符串 (PostgreSQL)",
    )

    parser.add_argument(
        "--repos",
        type=str,
        nargs="+",
        required=True,
        help="要管理的 Repo 列表",
    )

    # 可选参数
    parser.add_argument(
        "--max-global-parallel",
        type=int,
        default=10,
        help="全局最大并行任务数 (默认：10)",
    )

    parser.add_argument(
        "--base-quota",
        type=int,
        default=2,
        help="每个 Repo 的基础 Agent 配额 (默认：2)",
    )

    parser.add_argument(
        "--elastic-pool-size",
        type=int,
        default=8,
        help="弹性 Agent 池大小 (默认：8)",
    )

    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="状态轮询间隔（秒）(默认：5.0)",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别 (默认：INFO)",
    )

    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="日志文件路径 (可选)",
    )

    parser.add_argument(
        "--status-file",
        type=str,
        default=".global_coordinator_status.json",
        help="状态文件路径 (默认：.global_coordinator_status.json)",
    )

    parser.add_argument(
        "--daemon",
        action="store_true",
        help="后台运行模式",
    )

    return parser.parse_args()


def validate_repos(connection: Any, repos: list[str]) -> list[str]:
    """
    验证 Repo 是否存在

    Returns:
        存在的 Repo 列表
    """
    valid_repos = []

    with connection.cursor() as cursor:
        for repo in repos:
            cursor.execute("""
                SELECT 1 FROM (
                    SELECT repo FROM program_epic
                    UNION
                    SELECT repo FROM program_story
                    UNION
                    SELECT repo FROM work_item WHERE repo IS NOT NULL
                ) t WHERE repo = %s
                LIMIT 1
            """, (repo,))

            if cursor.fetchone() is not None:
                valid_repos.append(repo)
            else:
                logger.warning(f"Repo '{repo}' not found in database, skipping")

    return valid_repos


def setup_signal_handlers(
    coordinator: GlobalCoordinator,
    pool_manager: AgentPoolManager,
) -> None:
    """设置信号处理器（优雅退出）"""
    shutdown_requested = False

    def signal_handler(signum: int, frame: Any) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            logger.warning("强制退出...")
            sys.exit(1)

        logger.info("收到退出信号，正在关闭...")
        shutdown_requested = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def run_coordinator_loop(
    coordinator: GlobalCoordinator,
    pool_manager: AgentPoolManager,
    repos: list[str],
    poll_interval: float,
    status_file: str,
) -> None:
    """运行协调器主循环"""
    logger.info(f"启动协调器循环，管理 {len(repos)} 个 Repo")
    logger.info(f"配置：base_quota={pool_manager.base_quota_per_repo}, "
                f"elastic_pool={pool_manager.elastic_pool_size}")

    iteration = 0

    while True:
        iteration += 1

        try:
            # 1. 更新所有 Repo 的心跳
            for repo in repos:
                coordinator.update_heartbeat(repo)

            # 2. 获取全局状态
            global_states = coordinator.get_global_status()

            # 3. 记录状态
            if iteration % 10 == 0:  # 每 10 次迭代记录一次摘要
                log_global_summary(global_states)

            # 4. 健康检查
            health = pool_manager.health_check()
            if health.get("stale"):
                logger.warning(f"检测到 {len(health['stale'])} 个心跳超时的 Agent")

            # 5. 保存状态到文件
            if iteration % 5 == 0:  # 每 5 次迭代保存一次状态
                save_status(status_file, global_states, health)

        except Exception as e:
            logger.error(f"协调器循环错误：{e}", exc_info=True)

        time.sleep(poll_interval)


def log_global_summary(states: list) -> None:
    """记录全局状态摘要"""
    total_agents = sum(s.active_agent_count for s in states)
    total_tasks = sum(s.running_task_count for s in states)
    attention_needed = [s.repo for s in states if s.operator_attention_required]

    logger.info(
        f"全局状态：{len(states)} 个 Repo, "
        f"{total_agents} 个活跃 Agent, "
        f"{total_tasks} 个运行任务"
    )

    if attention_needed:
        logger.warning(f"需要关注的 Repo: {', '.join(attention_needed)}")


def save_status(
    status_file: str,
    states: list,
    health: dict[str, list[str]],
) -> None:
    """保存状态到文件"""
    import json

    status = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repos": [
            {
                "repo": s.repo,
                "active_agents": s.active_agent_count,
                "running_tasks": s.running_task_count,
                "operator_attention_required": s.operator_attention_required,
                "ready_tasks": s.ready_task_count,
                "blocked_tasks": s.blocked_task_count,
            }
            for s in states
        ],
        "agent_health": {
            "idle": len(health.get("idle", [])),
            "busy": len(health.get("busy", [])),
            "offline": len(health.get("offline", [])),
            "stale": len(health.get("stale", [])),
        },
    }

    try:
        with open(status_file, "w") as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        logger.warning(f"保存状态失败：{e}")


def main() -> int:
    """主入口"""
    args = parse_args()

    # 设置日志级别
    logging.getLogger().setLevel(args.log_level)

    # 添加文件日志
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        logging.getLogger().addHandler(file_handler)

    logger.info("=" * 60)
    logger.info("Global Coordinator - 多项目协调器")
    logger.info("=" * 60)

    # 验证参数
    if args.max_global_parallel < 1:
        logger.error("--max-global-parallel 必须大于 0")
        return 1

    if args.base_quota < 0:
        logger.error("--base-quota 必须大于等于 0")
        return 1

    if args.elastic_pool_size < 0:
        logger.error("--elastic-pool-size 必须大于等于 0")
        return 1

    # 连接数据库
    try:
        logger.info(f"连接数据库：{args.dsn[:30]}...")
        conn = psycopg.connect(args.dsn)
    except Exception as e:
        logger.error(f"数据库连接失败：{e}")
        return 1

    # 验证 Repo
    valid_repos = validate_repos(conn, args.repos)
    if not valid_repos:
        logger.error("没有有效的 Repo")
        return 1

    logger.info(f"有效 Repo: {valid_repos}")

    # 创建协调器和 Agent 池管理器
    coordinator = GlobalCoordinator(
        dsn=args.dsn,
        max_global_parallel=args.max_global_parallel,
        base_quota_per_repo=args.base_quota,
        elastic_pool_size=args.elastic_pool_size,
    )

    pool_manager = AgentPoolManager(
        dsn=args.dsn,
        base_quota_per_repo=args.base_quota,
        elastic_pool_size=args.elastic_pool_size,
    )

    # 注册默认 Agent（如果有需要）
    # 这里可以根据需要添加 Agent 注册逻辑

    # 设置信号处理
    setup_signal_handlers(coordinator, pool_manager)

    # 运行协调器循环
    try:
        run_coordinator_loop(
            coordinator=coordinator,
            pool_manager=pool_manager,
            repos=valid_repos,
            poll_interval=args.poll_interval,
            status_file=args.status_file,
        )
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.error(f"协调器异常：{e}", exc_info=True)
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
