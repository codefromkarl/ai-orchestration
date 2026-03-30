import {
  AgentEfficiencyStat,
  AgentStatusItem,
  AttentionItem,
  EpicOverviewRow,
  EpicStoryTreeRow,
  NotificationItem,
  RepoSummary,
  RunningJobSummary,
  SnapshotHealthStatus,
  WorkItem,
  WorkspaceViewId,
} from '../types';
import { Badge } from './Badge';
import { getPriorityLabel } from '../utils/status-utils';

interface WorkspacePanelProps {
  activeView: WorkspaceViewId;
  jobs: RunningJobSummary[];
  tasks: WorkItem[];
  notifications: NotificationItem[];
  failedNotifications: NotificationItem[];
  agents: AgentStatusItem[];
  agentStats: AgentEfficiencyStat[];
  attentionItems: AttentionItem[];
  epicRows: EpicOverviewRow[];
  epicTreeRows: EpicStoryTreeRow[];
  repoSummary: RepoSummary | null;
  onJobClick: (jobId: number) => void;
  onEpicClick: (epicIssueNumber: number) => void;
  onStoryClick: (storyIssueNumber: number) => void;
  onTaskClick: (workId: string, repo?: string) => void;
}

function getSnapshotTone(status?: SnapshotHealthStatus | string, lockIsStale?: boolean) {
  if (lockIsStale || status === 'stale_lock') {
    return {
      label: '锁陈旧',
      backgroundColor: 'rgba(239, 68, 68, 0.12)',
      color: '#b91c1c',
    };
  }

  switch (status) {
    case 'ready':
      return {
        label: '就绪',
        backgroundColor: 'rgba(34, 197, 94, 0.14)',
        color: '#166534',
      };
    case 'building':
      return {
        label: '构建中',
        backgroundColor: 'rgba(59, 130, 246, 0.14)',
        color: '#1d4ed8',
      };
    case 'failed':
      return {
        label: '失败',
        backgroundColor: 'rgba(239, 68, 68, 0.12)',
        color: '#b91c1c',
      };
    case 'missing':
      return {
        label: '缺失',
        backgroundColor: 'rgba(245, 158, 11, 0.14)',
        color: '#92400e',
      };
    default:
      return {
        label: status || '未知',
        backgroundColor: 'rgba(107, 114, 128, 0.1)',
        color: '#6b7280',
      };
  }
}

function formatAge(seconds?: number | null) {
  if (seconds === undefined || seconds === null || Number.isNaN(seconds)) {
    return '—';
  }

  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

function EmptyState({ message }: { message: string }) {
  return (
    <div
      className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-text-secondary"
    >
      {message}
    </div>
  );
}

export function WorkspacePanel({
  activeView,
  jobs,
  tasks,
  notifications,
  failedNotifications,
  agents,
  agentStats,
  attentionItems,
  epicRows,
  epicTreeRows,
  repoSummary,
  onJobClick,
  onEpicClick,
  onStoryClick,
  onTaskClick,
}: WorkspacePanelProps) {
  const snapshotHealth = repoSummary?.snapshotHealth;
  const snapshotTone = getSnapshotTone(snapshotHealth?.status, snapshotHealth?.lock_is_stale);
  const latestTasks = tasks.slice(0, 80);

  return (
    <section
      id="workspace-panel"
      hidden={activeView === 'epic_overview'}
      className="flex-1 overflow-auto bg-background px-6 py-6"
    >
      <div hidden={activeView !== 'running_jobs'}>
        <h2 className="mb-4 text-lg font-semibold text-text">
          运行中的作业
        </h2>
        <div className="mb-4 flex flex-wrap gap-2">
          {epicRows.map((epic) => (
            <button
              key={epic.epic_issue_number}
              type="button"
              data-epic-issue-number={epic.epic_issue_number}
              onClick={() => onEpicClick(epic.epic_issue_number)}
              className="rounded-full border border-border bg-surface-hover px-3 py-1.5 text-sm text-text"
            >
              史诗 #{epic.epic_issue_number}
            </button>
          ))}
        </div>
        <div className="space-y-3">
          {jobs.map((job) => (
            <button
              key={job.id}
              type="button"
              data-job-id={job.id}
              onClick={() => onJobClick(job.id)}
              className="block w-full rounded-xl border border-border bg-surface px-4 py-3 text-left text-text"
            >
              <div className="text-sm font-semibold">作业 #{job.id}</div>
              <div className="mt-1 text-sm text-text-secondary">
                {job.worker_name || job.job_kind || '运行中的作业'}
              </div>
            </button>
          ))}
          {jobs.length === 0 && <EmptyState message="当前没有运行中的作业。" />}
        </div>
      </div>

      <div id="notification-panel" hidden={activeView !== 'notifications'}>
        <h2 className="mb-4 text-lg font-semibold text-text">
          通知
        </h2>
        <div className="mb-6">
          <div id="notification-pending-panel" className="rounded-xl border border-border bg-surface px-4 py-4 text-sm text-text">
            {notifications.length > 0
              ? notifications.map((item) => `#${item.id} ${item.notification_type || item.status || '通知'}`).join('\n')
              : '当前没有通知。'}
          </div>
        </div>
        <div className="mb-3 flex gap-2">
          <button type="button" data-notification-tab="pending" className="rounded-md border border-border bg-surface-hover px-3 py-1.5 text-sm text-text">
            待处理
          </button>
          <button type="button" data-notification-tab="failed" className="rounded-md border border-border bg-surface-hover px-3 py-1.5 text-sm text-text">
            失败
          </button>
        </div>
        <div id="notification-failed-panel" className="rounded-xl border border-border bg-surface px-4 py-4 text-sm text-text">
          {failedNotifications.length > 0
            ? failedNotifications.map((item) => `#${item.id} ${item.notification_type || item.status || '通知'}`).join('\n')
            : '当前没有通知。'}
        </div>
      </div>

      <div id="agent-console-panel" hidden={activeView !== 'agent_console'}>
        <h2 className="mb-4 text-lg font-semibold text-text">
          智能体控制台
        </h2>
        <div className="overflow-hidden rounded-xl border border-border bg-surface">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface-hover text-text-secondary">
              <tr>
                <th className="px-4 py-3">智能体</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">工作单元</th>
              </tr>
            </thead>
            <tbody id="agent-table-body">
              {agents.map((agent, index) => (
                <tr key={`${agent.agent_id || agent.agent_name || 'agent'}-${index}`}>
                  <td className="px-4 py-3">{agent.agent_name || agent.agent_id || '未知智能体'}</td>
                  <td className="px-4 py-3">{agent.status || '未知'}</td>
                  <td className="px-4 py-3">{agent.worker_name || agent.current_task || '—'}</td>
                </tr>
              ))}
              {agents.length === 0 && (
                <tr>
                  <td className="px-4 py-3" colSpan={3}>当前没有智能体。</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div id="agent-stats-summary" className="mt-4 text-sm text-text-secondary">
          {agentStats.map((stat) => `${stat.agent_name}: 成功率 ${stat.success_rate_percent ?? '—'}%`).join(' · ')}
        </div>
      </div>

      <div hidden={activeView !== 'system_status'}>
        <h2 className="mb-4 text-lg font-semibold text-text">
          系统状态
        </h2>

        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-text">
                ContextWeaver Snapshot
              </div>
              <div className="mt-1 text-sm text-text-secondary">
                {snapshotHealth?.summary || '当前仓库尚未提供快照健康摘要。'}
              </div>
            </div>
            <span
              className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
              style={{ backgroundColor: snapshotTone.backgroundColor, color: snapshotTone.color }}
            >
              {snapshotTone.label}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { label: 'Snapshot', value: snapshotHealth?.snapshot_id || '—' },
              { label: 'Artifact', value: snapshotHealth?.artifact_status || '—' },
              { label: 'Artifact Age', value: formatAge(snapshotHealth?.artifact_age_seconds) },
              { label: 'Lock Age', value: formatAge(snapshotHealth?.lock_age_seconds) },
            ].map((item) => (
              <div
                key={item.label}
                className="rounded-lg border border-border bg-surface-hover px-3 py-2"
              >
                <div className="text-xs uppercase tracking-wide text-text-secondary">
                  {item.label}
                </div>
                <div className="mt-1 text-sm font-medium text-text">
                  {item.value}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div hidden={activeView !== 'task_repository'}>
        <h2 className="mb-4 text-lg font-semibold text-text">
          任务仓库
        </h2>
        <div className="space-y-2">
          {latestTasks.map((task) => (
            <button
              key={task.id || `task-${task.number}`}
              type="button"
              data-work-id={task.id || ''}
              disabled={!task.id}
              onClick={() => {
                if (task.id) onTaskClick(task.id, task.repo);
              }}
              className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-left text-text transition-colors hover:opacity-95"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold">
                    #{task.number} {task.title}
                  </div>
                  <div className="mt-1 text-xs text-text-secondary">
                    {task.repo ? `仓库 ${task.repo} · ` : ''}
                    优先级 {getPriorityLabel(task.priority)}
                    {task.blockedReason ? ` · 阻塞: ${task.blockedReason}` : ''}
                  </div>
                </div>
                <Badge status={task.status} />
              </div>
            </button>
          ))}
          {latestTasks.length === 0 && <EmptyState message="当前仓库还没有任务数据。" />}
        </div>
      </div>

      <div hidden={activeView !== 'command_center'}>
        <h2 className="mb-4 text-lg font-semibold text-text">
          指挥中心
        </h2>
        <div className="space-y-3">
          {attentionItems.map((item) => (
            <div
              key={item.id}
              className="rounded-xl border border-border bg-surface px-4 py-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-text">
                    #{item.issueNumber} {item.title}
                  </div>
                  <div className="mt-1 text-xs text-text-secondary">
                    {item.reason || '待评估'} · 优先级分值 {item.priorityScore}
                  </div>
                </div>
                <span
                  className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                  style={{ backgroundColor: 'rgba(245, 158, 11, 0.16)', color: '#92400e' }}
                >
                  {item.priorityScore}
                </span>
              </div>
            </div>
          ))}
          {attentionItems.length === 0 && <EmptyState message="当前没有待处理关注项。" />}
        </div>
      </div>

      <div hidden={activeView !== 'story_tree'}>
        <h2 className="mb-4 text-lg font-semibold text-text">
          故事树
        </h2>
        <div className="space-y-3">
          {epicTreeRows.map((epic) => (
            <div
              key={epic.epic_issue_number}
              className="rounded-xl border border-border bg-surface p-3"
            >
              <button
                type="button"
                data-epic-issue-number={epic.epic_issue_number}
                onClick={() => onEpicClick(epic.epic_issue_number)}
                className="text-sm font-semibold text-text transition-colors hover:opacity-90"
              >
                史诗 #{epic.epic_issue_number} · {epic.title}
              </button>

              <div className="mt-2 space-y-2">
                {(epic.story_summaries || []).map((story) => (
                  <div key={story.story_issue_number} className="rounded-lg bg-surface-hover px-2 py-2">
                    <button
                      type="button"
                      data-story-issue-number={story.story_issue_number}
                      onClick={() => onStoryClick(story.story_issue_number)}
                      className="text-sm font-medium text-text transition-colors hover:opacity-90"
                    >
                      故事 #{story.story_issue_number} · {story.title}
                    </button>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {(story.task_summaries || []).slice(0, 6).map((task) => (
                        <button
                          key={task.work_id}
                          type="button"
                          data-work-id={task.work_id}
                          onClick={() => onTaskClick(task.work_id)}
                          className="rounded-full border border-border bg-surface px-2 py-0.5 text-[11px] text-text-secondary"
                        >
                          {task.source_issue_number ? `#${task.source_issue_number}` : task.work_id}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {epicTreeRows.length === 0 && <EmptyState message="当前仓库还没有故事树数据。" />}
        </div>
      </div>
    </section>
  );
}
