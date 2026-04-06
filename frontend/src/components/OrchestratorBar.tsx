import { AttentionItem, RunningJobSummary, WorkItem } from '../types';

interface OrchestratorBarProps {
  blockedItems: WorkItem[];
  decisionItems: WorkItem[];
  runningJobs: RunningJobSummary[];
  attentionItems: AttentionItem[];
  onTaskClick: (workId: string, repo?: string) => void;
  onJobClick: (jobId: number) => void;
}

export function OrchestratorBar({
  blockedItems,
  decisionItems,
  runningJobs,
  attentionItems,
  onTaskClick,
  onJobClick,
}: OrchestratorBarProps) {
  const needsAttention = blockedItems.length + decisionItems.length + attentionItems.length;
  if (needsAttention === 0 && runningJobs.length === 0) return null;

  return (
    <section className="border-b border-border bg-surface">
      {/* Attention row */}
      {needsAttention > 0 && (
        <div className="px-6 py-2">
          <div className="flex items-center gap-4">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-text-secondary">
              需要处理
            </span>
            <div className="flex flex-wrap gap-2">
              {blockedItems.slice(0, 5).map((item) => (
                <button
                  key={item.id || `blocked-${item.number}`}
                  type="button"
                  onClick={() => item.id && onTaskClick(item.id, item.repo)}
                  className="flex items-center gap-1.5 rounded-md bg-red-50 dark:bg-red-900/20 px-2 py-1 text-xs text-red-700 dark:text-red-400 hover:opacity-80"
                >
                  <span className="font-medium">阻塞</span>
                  <span className="max-w-32 truncate">#{item.number} {item.title}</span>
                </button>
              ))}
              {decisionItems.slice(0, 3).map((item) => (
                <button
                  key={item.id || `decision-${item.number}`}
                  type="button"
                  onClick={() => item.id && onTaskClick(item.id, item.repo)}
                  className="flex items-center gap-1.5 rounded-md bg-orange-50 dark:bg-orange-900/20 px-2 py-1 text-xs text-orange-700 dark:text-orange-400 hover:opacity-80"
                >
                  <span className="font-medium">待决策</span>
                  <span className="max-w-32 truncate">#{item.number} {item.title}</span>
                </button>
              ))}
              {attentionItems.slice(0, 3).map((item) => (
                <span
                  key={item.id}
                  className="rounded-md bg-amber-50 dark:bg-amber-900/20 px-2 py-1 text-xs text-amber-700 dark:text-amber-400"
                  title={item.reason}
                >
                  #{item.issueNumber} {item.title}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Running jobs row */}
      {runningJobs.length > 0 && (
        <div className="border-t border-border px-6 py-2">
          <div className="flex items-center gap-4">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-text-secondary">
              运行中
            </span>
            <div className="flex flex-wrap gap-2">
              {runningJobs.slice(0, 6).map((job) => (
                <button
                  key={job.id}
                  type="button"
                  onClick={() => onJobClick(job.id)}
                  className="flex items-center gap-1.5 rounded-md bg-blue-50 dark:bg-blue-900/20 px-2 py-1 text-xs text-blue-700 dark:text-blue-400 hover:opacity-80"
                >
                  <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
                  <span className="font-medium">#{job.id}</span>
                  <span className="max-w-24 truncate">{job.worker_name || job.job_kind || ''}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
