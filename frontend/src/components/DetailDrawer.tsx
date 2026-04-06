import { useState } from 'react';
import { X, ExternalLink } from 'lucide-react';
import { DrawerDetailItem } from '../types';
import { Badge } from './Badge';
import { getPriorityLabel } from '../utils/status-utils';

type DetailTab = 'overview' | 'sessions' | 'artifacts' | 'actions';

interface DetailDrawerProps {
  item: DrawerDetailItem | null;
  onClose: () => void;
  onStorySelect?: (storyIssueNumber: number) => void;
  onTaskSelect?: (workId: string) => void;
  onActionSelect?: (actionUrl: string, label: string) => void;
}

export function DetailDrawer({ item, onClose, onStorySelect, onTaskSelect, onActionSelect }: DetailDrawerProps) {
  const [activeTab, setActiveTab] = useState<DetailTab>('overview');

  if (!item) return null;

  const tabs: Array<{ id: DetailTab; label: string; count?: number }> = [
    { id: 'overview' as const, label: '概览' },
    { id: 'sessions' as const, label: 'Session', count: item.runtimeSessions?.length || 0 },
    { id: 'artifacts' as const, label: 'Artifacts', count: item.artifacts?.length || 0 },
    { id: 'actions' as const, label: '操作', count: item.actionButtons?.length || 0 },
  ].filter((t) => t.id === 'overview' || (t.count && t.count > 0));

  return (
    <div className="w-[360px] border-l flex flex-col h-full border-border bg-surface">
      {/* Header */}
      <div className="flex items-start justify-between p-3 border-b border-border">
        <div className="flex-1 pr-2 min-w-0">
          <h3 className="text-sm font-semibold text-text truncate">
            #{item.number} {item.title}
          </h3>
          <div className="mt-1 flex items-center gap-2 text-xs text-text-secondary">
            <span className="capitalize">{item.type}</span>
            {item.status && <Badge status={item.status} />}
          </div>
        </div>
        <button onClick={onClose} className="text-text-secondary hover:text-text">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 px-2 py-2 text-xs font-medium transition-colors ${
              activeTab === tab.id
                ? 'border-b-2 border-primary text-text'
                : 'text-text-secondary hover:text-text'
            }`}
          >
            {tab.label}
            {tab.count !== undefined && tab.count > 0 && (
              <span className="ml-1 text-[10px] text-text-secondary">({tab.count})</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {activeTab === 'overview' && <OverviewTab item={item} onStorySelect={onStorySelect} onTaskSelect={onTaskSelect} />}
        {activeTab === 'sessions' && item.runtimeSessions && <SessionsTab sessions={item.runtimeSessions} />}
        {activeTab === 'artifacts' && item.artifacts && <ArtifactsTab artifacts={item.artifacts} />}
        {activeTab === 'actions' && item.actionButtons && <ActionsTab actions={item.actionButtons} onActionSelect={onActionSelect} />}
      </div>

      {/* Footer */}
      {item.githubUrl && (
        <div className="border-t border-border px-3 py-2">
          <a
            href={item.githubUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs text-primary hover:text-primary-hover"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            GitHub
          </a>
        </div>
      )}
    </div>
  );
}

function OverviewTab({ item, onStorySelect, onTaskSelect }: {
  item: DrawerDetailItem;
  onStorySelect?: (n: number) => void;
  onTaskSelect?: (id: string) => void;
}) {
  return (
    <>
      {item.metaSummary && (
        <div className="rounded-lg border border-border bg-surface-hover px-3 py-2 text-xs text-text-secondary">
          {item.metaSummary}
        </div>
      )}

      <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
        {item.lane && (
          <>
            <span className="text-text-secondary">泳道</span>
            <span className="font-medium text-text">{item.lane}</span>
          </>
        )}
        {item.wave && (
          <>
            <span className="text-text-secondary">波次</span>
            <span className="font-medium text-text">{item.wave}</span>
          </>
        )}
        {item.complexity !== undefined && (
          <>
            <span className="text-text-secondary">复杂度</span>
            <span className="font-medium text-text">{item.complexity}</span>
          </>
        )}
        <span className="text-text-secondary">优先级</span>
        <span className="font-medium text-text">{getPriorityLabel(item.priority)}</span>
      </div>

      {(item.blockedReason || item.decisionRequired) && (
        <div className="pt-2 border-t border-border space-y-1.5">
          {item.blockedReason && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-text-secondary">阻塞</span>
              <span className="text-red-600 font-medium">{item.blockedReason}</span>
            </div>
          )}
          {item.decisionRequired && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-text-secondary">需要决策</span>
              <span className="text-orange-600 font-medium">是</span>
            </div>
          )}
        </div>
      )}

      {item.storySummaries && item.storySummaries.length > 0 && (
        <div className="pt-2 border-t border-border">
          <div className="text-xs font-medium text-text mb-1.5">故事</div>
          <div className="flex flex-wrap gap-1.5">
            {item.storySummaries.map((story) => (
              <button
                key={story.story_issue_number}
                type="button"
                onClick={() => onStorySelect?.(story.story_issue_number)}
                className="rounded-full border border-border bg-surface-hover px-2 py-1 text-[11px] text-text"
              >
                #{story.story_issue_number}
              </button>
            ))}
          </div>
        </div>
      )}

      {item.taskSummaries && item.taskSummaries.length > 0 && (
        <div className="pt-2 border-t border-border">
          <div className="text-xs font-medium text-text mb-1.5">活跃任务</div>
          <div className="space-y-1">
            {item.taskSummaries.map((task) => (
              <button
                key={task.workId}
                type="button"
                onClick={() => onTaskSelect?.(task.workId)}
                className="flex w-full items-center justify-between rounded-md border border-border bg-surface-hover px-2 py-1.5 text-left text-[11px] text-text"
              >
                <span className="truncate">#{task.issueNumber} {task.title}</span>
                {task.status && <Badge status={task.status} />}
              </button>
            ))}
          </div>
        </div>
      )}

      {item.kind === 'task' && item.snapshotState && (
        <div className="pt-2 border-t border-border">
          <div className="flex items-center justify-between text-xs">
            <span className="text-text-secondary">Snapshot</span>
            <span className="font-medium text-text">{item.snapshotState.snapshot_id || '—'}</span>
          </div>
          {item.snapshotState.summary && (
            <div className="mt-1 text-[11px] text-text-secondary">{item.snapshotState.summary}</div>
          )}
        </div>
      )}
    </>
  );
}

function SessionsTab({ sessions }: { sessions: NonNullable<DrawerDetailItem['runtimeSessions']> }) {
  return (
    <div className="space-y-2">
      {sessions.map((session) => (
        <div key={session.id} className="rounded-lg border border-border bg-surface-hover px-3 py-2">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-text truncate">{session.id}</span>
            {session.status && (
              <span className="rounded-full bg-surface px-1.5 py-0.5 text-[10px] text-text-secondary">
                {session.status}
              </span>
            )}
          </div>
          <div className="mt-1 text-[11px] text-text-secondary">
            {session.currentPhase || 'session'}{session.attemptIndex !== undefined ? ` · attempt ${session.attemptIndex}` : ''}
          </div>
          {session.checkpointSummary && (
            <div className="mt-1.5 text-xs text-text">{session.checkpointSummary}</div>
          )}
          {(session.checkpointNextAction || session.waitingReason) && (
            <div className="mt-1 text-[11px] text-text-secondary">
              {[session.checkpointNextAction, session.waitingReason].filter(Boolean).join(' · ')}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function ArtifactsTab({ artifacts }: { artifacts: NonNullable<DrawerDetailItem['artifacts']> }) {
  return (
    <div className="space-y-2">
      {artifacts.map((a) => (
        <div key={a.id} className="rounded-lg border border-border bg-surface-hover px-3 py-2">
          <div className="text-xs font-medium text-text">{a.artifactType || 'artifact'}</div>
          {a.artifactKey && (
            <div className="mt-0.5 break-all text-[11px] text-text-secondary">{a.artifactKey}</div>
          )}
          {a.summary && <div className="mt-1.5 text-xs text-text">{a.summary}</div>}
          <div className="mt-1 text-[11px] text-text-secondary">
            {[
              a.contentSizeBytes !== undefined ? `${a.contentSizeBytes} bytes` : '',
              a.createdAt ? new Date(a.createdAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '',
            ].filter(Boolean).join(' · ')}
          </div>
        </div>
      ))}
    </div>
  );
}

function ActionsTab({ actions, onActionSelect }: {
  actions: NonNullable<DrawerDetailItem['actionButtons']>;
  onActionSelect?: (url: string, label: string) => void;
}) {
  return (
    <div className="space-y-2">
      {actions.map((action) => (
        <button
          key={action.actionUrl}
          type="button"
          onClick={() => onActionSelect?.(action.actionUrl, action.label)}
          className={`w-full rounded-md px-3 py-2 text-sm font-medium text-white ${
            action.tone === 'danger' ? 'bg-red-500' : 'bg-primary'
          }`}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
