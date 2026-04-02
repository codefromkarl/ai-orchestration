import { X, ExternalLink } from 'lucide-react';
import { DrawerDetailItem } from '../types';
import { Badge } from './Badge';
import { getPriorityLabel } from '../utils/status-utils';

function getSnapshotTone(status?: string, lockIsStale?: boolean) {
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
        backgroundColor: 'var(--color-surface-hover)',
        color: 'var(--color-text-secondary)',
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

function formatTimestamp(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

interface DetailDrawerProps {
  item: DrawerDetailItem | null;
  onClose: () => void;
  onStorySelect?: (storyIssueNumber: number) => void;
  onTaskSelect?: (workId: string) => void;
  onActionSelect?: (actionUrl: string, label: string) => void;
}

export function DetailDrawer({ item, onClose, onStorySelect, onTaskSelect, onActionSelect }: DetailDrawerProps) {
  if (!item) return null;

  const snapshotTone = getSnapshotTone(item.snapshotState?.status, item.snapshotState?.lock_is_stale);

  return (
    <div className="w-[360px] border-l flex flex-col h-full border-border bg-surface">
      <div className="flex items-start justify-between p-4 border-b border-border">
        <div className="flex-1 pr-2">
          <h3
            id="detail-title"
            className="font-semibold text-text"
          >
            #{item.number} {item.title}
          </h3>
        </div>
        <button
          onClick={onClose}
          className="transition-colors text-text-secondary hover:text-text"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <div id="detail-meta" className="flex-1 overflow-y-auto p-4 space-y-4">
        {item.metaSummary && (
          <div
            className="rounded-lg border px-3 py-3 text-sm border-border bg-surface-hover text-text-secondary"
          >
            {item.metaSummary}
          </div>
        )}

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
            <div className="text-text-secondary">类型</div>
            <div className="font-medium text-text">
              {item.type}
            </div>

            {item.status && (
              <>
                <div className="text-text-secondary">状态</div>
                <div><Badge status={item.status} /></div>
              </>
            )}

            {item.lane && (
              <>
                <div className="text-text-secondary">泳道</div>
                <div className="font-medium text-text">
                  {item.lane}
                </div>
              </>
            )}

            {item.wave && (
              <>
                <div className="text-text-secondary">波次</div>
                <div className="font-medium text-text">
                  {item.wave}
                </div>
              </>
            )}

            {item.complexity !== undefined && (
              <>
                <div className="text-text-secondary">复杂度</div>
                <div className="font-medium text-text">
                  {item.complexity}
                </div>
              </>
            )}
          </div>
        </div>

        {(item.status || item.blockedReason || item.decisionRequired) && (
          <div className="pt-3 border-t space-y-2 border-border">
            {item.status && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-secondary">执行状态</span>
                <Badge status={item.status} />
              </div>
            )}

            {item.blockedReason && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-secondary">阻塞</span>
                <span className="text-red-600 font-medium">{item.blockedReason}</span>
              </div>
            )}

            {item.decisionRequired && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-secondary">需要决策</span>
                <span className="text-orange-600 font-medium">是</span>
              </div>
            )}
          </div>
        )}

        {(item.epicNumber || item.storyNumber) && (
          <div className="pt-3 border-t space-y-2 text-sm border-border">
            {item.epicNumber && (
              <div className="flex items-center justify-between">
                <span className="text-text-secondary">史诗</span>
                <span className="font-medium text-primary">
                  #{item.epicNumber}
                </span>
              </div>
            )}
            {item.storyNumber && (
              <div className="flex items-center justify-between">
                <span className="text-text-secondary">故事</span>
                <span className="font-medium text-primary">
                  #{item.storyNumber}
                </span>
              </div>
            )}
          </div>
        )}

        {item.storySummaries && item.storySummaries.length > 0 && (
          <div
            id="detail-tab-overview"
            className="pt-3 border-t space-y-2 border-border"
          >
            <div className="text-sm font-medium text-text">
              故事
            </div>
            <div className="flex flex-wrap gap-2">
              {item.storySummaries.map((story) => (
                <button
                  key={story.story_issue_number}
                  type="button"
                  data-story-issue-number={story.story_issue_number}
                  className="rounded-full border px-3 py-1.5 text-sm border-border bg-surface-hover text-text"
                  onClick={() => onStorySelect?.(story.story_issue_number)}
                >
                  #{story.story_issue_number} {story.title}
                </button>
              ))}
            </div>
          </div>
        )}

        {item.taskSummaries && item.taskSummaries.length > 0 && (
          <div className="pt-3 border-t space-y-2 border-border">
            <div className="text-sm font-medium text-text">
              活跃任务
            </div>
            <div id="sidebar-story-tree" className="space-y-2">
              {item.taskSummaries.map((task) => (
                <button
                  key={task.workId}
                  type="button"
                  data-work-id={task.workId}
                  className="flex w-full items-start justify-between rounded-lg border px-3 py-2 text-left text-sm border-border bg-surface-hover text-text"
                  onClick={() => onTaskSelect?.(task.workId)}
                >
                  <span>
                    {task.issueNumber ? `#${task.issueNumber} ` : ''}
                    {task.title}
                  </span>
                  {task.status && <span className="text-text-secondary">{task.status}</span>}
                </button>
              ))}
            </div>
          </div>
        )}

        {item.kind === 'task' && item.snapshotState && (
          <div className="pt-3 border-t space-y-3 border-border">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-text">
                  Snapshot 状态
                </div>
                <div className="mt-1 text-sm text-text-secondary">
                  {item.snapshotState.summary || '当前任务未返回快照摘要。'}
                </div>
              </div>
              <span
                className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                style={{ backgroundColor: snapshotTone.backgroundColor, color: snapshotTone.color }}
              >
                {snapshotTone.label}
              </span>
            </div>

            <div className="overflow-hidden rounded-xl border border-border">
              <table className="w-full text-left text-sm">
                <tbody>
                  {[
                    { label: 'Snapshot', value: item.snapshotState.snapshot_id || '—' },
                    { label: 'Artifact', value: item.snapshotState.artifact_status || '—' },
                    { label: 'Artifact Age', value: formatAge(item.snapshotState.artifact_age_seconds) },
                    { label: 'Lock Age', value: formatAge(item.snapshotState.lock_age_seconds) },
                  ].map((row, index) => (
                    <tr key={row.label} className={index > 0 ? "border-t border-border" : ""}>
                      <td className="px-3 py-2 align-top text-text-secondary">
                        {row.label}
                      </td>
                      <td className="px-3 py-2 font-medium text-text">
                        {row.value}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {item.kind === 'task' && item.runtimeSessions && item.runtimeSessions.length > 0 && (
          <div className="pt-3 border-t space-y-3 border-border">
            <div>
              <div className="text-sm font-medium text-text">
                Session Runtime
              </div>
              <div className="mt-1 text-sm text-text-secondary">
                最近会话与最新 checkpoint 摘要。
              </div>
            </div>

            <div className="space-y-2">
              {item.runtimeSessions.map((session) => (
                <div
                  key={session.id}
                  className="rounded-xl border border-border bg-surface-hover px-3 py-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-text">
                        {session.id}
                      </div>
                      <div className="mt-1 text-xs text-text-secondary">
                        {(session.currentPhase || session.status || 'session')}{session.attemptIndex !== undefined ? ` · attempt ${session.attemptIndex}` : ''}
                      </div>
                    </div>
                    {session.status && (
                      <span className="inline-flex items-center rounded-full bg-surface px-2 py-0.5 text-[11px] font-semibold text-text-secondary">
                        {session.status}
                      </span>
                    )}
                  </div>

                  {(session.checkpointSummary || session.checkpointNextAction || session.waitingReason) && (
                    <div className="mt-3 space-y-1 text-sm">
                      {session.checkpointSummary && (
                        <div className="text-text">
                          {session.checkpointSummary}
                        </div>
                      )}
                      <div className="text-xs text-text-secondary">
                        {[session.checkpointNextAction, session.waitingReason, formatTimestamp(session.updatedAt)].filter(Boolean).join(' · ')}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {item.kind === 'task' && item.artifacts && item.artifacts.length > 0 && (
          <div className="pt-3 border-t space-y-3 border-border">
            <div>
              <div className="text-sm font-medium text-text">
                Artifacts
              </div>
              <div className="mt-1 text-sm text-text-secondary">
                最近产出的工件与摘要引用。
              </div>
            </div>

            <div className="space-y-2">
              {item.artifacts.map((artifact) => (
                <div
                  key={artifact.id}
                  className="rounded-xl border border-border bg-surface-hover px-3 py-3"
                >
                  <div className="text-sm font-medium text-text">
                    {artifact.artifactType || 'artifact'}
                  </div>
                  <div className="mt-1 break-all text-xs text-text-secondary">
                    {artifact.artifactKey || '—'}
                  </div>
                  {(artifact.summary || artifact.sessionId || artifact.createdAt) && (
                    <div className="mt-3 space-y-1">
                      {artifact.summary && (
                        <div className="text-sm text-text">
                          {artifact.summary}
                        </div>
                      )}
                      <div className="text-xs text-text-secondary">
                        {[
                          artifact.sessionId ? `session ${artifact.sessionId}` : '',
                          artifact.runId !== undefined && artifact.runId !== null ? `run ${artifact.runId}` : '',
                          artifact.contentSizeBytes !== undefined ? `${artifact.contentSizeBytes} bytes` : '',
                          formatTimestamp(artifact.createdAt),
                        ].filter(Boolean).join(' · ')}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {item.actionButtons && item.actionButtons.length > 0 && (
          <div
            id="detail-primary-actions"
            className="pt-3 border-t space-y-2 border-border"
          >
            <div className="text-sm font-medium text-text">
              操作
            </div>
            <div className="flex flex-wrap gap-2">
              {item.actionButtons.map((action) => (
                <button
                  key={action.actionUrl}
                  type="button"
                  data-action-url={action.actionUrl}
                  className={`rounded-md px-3 py-2 text-sm font-medium ${
                    action.tone === 'danger' ? 'bg-red-500' : 'bg-primary'
                  } text-white`}
                  onClick={() => onActionSelect?.(action.actionUrl, action.label)}
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {item.kind === 'task' && (
          <div className="pt-3 border-t border-border">
            <div className="flex items-center justify-between text-sm">
              <span className="text-text-secondary">优先级</span>
              <span className="font-medium text-text">
                {getPriorityLabel(item.priority)}
              </span>
            </div>
          </div>
        )}

        {item.githubUrl && (
          <div className="pt-3 border-t border-border">
            <a
              href={item.githubUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-sm transition-colors text-primary hover:text-primary-hover"
            >
              <ExternalLink className="w-4 h-4" />
              <span>GitHub 问题</span>
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
