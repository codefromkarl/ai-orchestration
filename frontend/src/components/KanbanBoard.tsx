import { useMemo, useState } from 'react';
import { MoreHorizontal } from 'lucide-react';
import { EpicOverviewRow, SystemStatus } from '../types';
import { ConsoleOnboarding } from './ConsoleOnboarding';

interface KanbanBoardProps {
  epicRows: EpicOverviewRow[];
  onOpenEpicDetail: (epicIssueNumber: number) => void;
  repo: string;
  systemStatus: SystemStatus | null;
  onOpenSystemPanel: () => void;
  hidden?: boolean;
}

function localizeMetaPart(part: string): string {
  const normalized = part.trim().toLowerCase();
  if (normalized === 'verify failed' || normalized === 'epic verification failed') {
    return '验证失败';
  }
  if (normalized === 'awaiting operator') {
    return '等待操作';
  }
  return part.replace(/_/g, ' ');
}

function buildEpicMeta(row: EpicOverviewRow): string[] {
  const status = row.execution_state_status || row.execution_status || row.program_status;
  const parts = [
    `${row.story_count} 个故事`,
    `${row.task_count} 个任务`,
  ];

  if (status) {
    parts.push(localizeMetaPart(status));
  }

  if (row.verification_summary) {
    parts.push(localizeMetaPart(row.verification_summary));
  } else if (row.verification_status === 'failed') {
    parts.push('验证失败');
  }

  if (row.verification_status === 'failed' && !parts.some((part) => part.includes('验证失败'))) {
    parts.push('验证失败');
  }

  return parts;
}

function EpicIssueCard({
  row,
  menuOpen,
  onToggleMenu,
  onOpenDetail,
  exposeEpicDataAttr,
}: {
  row: EpicOverviewRow;
  menuOpen: boolean;
  onToggleMenu: () => void;
  onOpenDetail: () => void;
  exposeEpicDataAttr: boolean;
}) {
  const metaParts = useMemo(() => buildEpicMeta(row), [row]);

  return (
    <article
      data-epic-issue-number={exposeEpicDataAttr ? row.epic_issue_number : undefined}
      className="relative rounded-xl border border-border bg-surface p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
      onClick={onOpenDetail}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <div
            className="text-xs font-semibold uppercase tracking-wide text-text-secondary"
          >
            史诗 #{row.epic_issue_number}
          </div>
          <h3
            className="text-base font-semibold text-text"
          >
            {row.title}
          </h3>
          <div
            className="text-sm leading-6 text-text-secondary"
          >
            {metaParts.join(' · ')}
          </div>
        </div>

        <button
          type="button"
          aria-label={`打开史诗 ${row.epic_issue_number} 菜单`}
          className="issue-card__action shrink-0 rounded-md p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text"
          onClick={(event) => {
            event.stopPropagation();
            onToggleMenu();
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape' && menuOpen) {
              event.preventDefault();
              event.stopPropagation();
              onToggleMenu();
            }
          }}
        >
          <MoreHorizontal className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-4 flex flex-wrap gap-2 text-xs">
        <span
          className="rounded-full bg-surface-hover px-2 py-1 text-text-secondary"
        >
          就绪 {row.ready_task_count}
        </span>
        <span
          className="rounded-full bg-surface-hover px-2 py-1 text-text-secondary"
        >
          进行中 {row.in_progress_task_count}
        </span>
        <span
          className={`rounded-full px-2 py-1 ${row.blocked_task_count > 0 ? 'bg-[var(--badge-blocked-bg)] text-[var(--badge-blocked-text)]' : 'bg-surface-hover text-text-secondary'}`}
        >
          阻塞 {row.blocked_task_count}
        </span>
      </div>

      <div
        className="issue-card__menu absolute right-4 top-12 z-10 min-w-40 rounded-lg border border-border bg-surface p-2 shadow-lg"
        hidden={!menuOpen}
        onClick={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          data-epic-menu-action="open-detail"
          className="w-full rounded-md px-3 py-2 text-left text-sm text-text transition-colors hover:bg-surface-hover"
          onClick={onOpenDetail}
        >
          打开详情
        </button>
      </div>
    </article>
  );
}

export function KanbanBoard({
  epicRows,
  onOpenEpicDetail,
  repo,
  systemStatus,
  onOpenSystemPanel,
  hidden = false,
}: KanbanBoardProps) {
  const [openMenuEpic, setOpenMenuEpic] = useState<number | null>(null);

  return (
    <section
      id="issue-card-section"
      className="h-full overflow-auto bg-background px-6 py-6"
      hidden={hidden}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2
            className="text-lg font-semibold text-text"
          >
            总览
          </h2>
          <p
            className="text-sm text-text-secondary"
          >
            面向渐进迁移的 Epic 卡片总览。
          </p>
        </div>
        <div
          className="text-sm text-text-secondary"
        >
          {epicRows.length} 个 Epic
        </div>
      </div>

      <div id="issue-card-list" className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {epicRows.map((row) => (
          <EpicIssueCard
            key={row.epic_issue_number}
            row={row}
            menuOpen={openMenuEpic === row.epic_issue_number}
            exposeEpicDataAttr={!hidden}
            onToggleMenu={() => {
              setOpenMenuEpic((current) =>
                current === row.epic_issue_number ? null : row.epic_issue_number
              );
            }}
            onOpenDetail={() => {
              setOpenMenuEpic(null);
              onOpenEpicDetail(row.epic_issue_number);
            }}
          />
        ))}
      </div>

      {epicRows.length === 0 && (
        <ConsoleOnboarding
          repo={repo}
          systemStatus={systemStatus}
          onOpenSystemPanel={onOpenSystemPanel}
        />
      )}
    </section>
  );
}
