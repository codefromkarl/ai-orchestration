import { EpicStoryTreeRow } from '../types';

interface SidebarTreeProps {
  rows: EpicStoryTreeRow[];
  collapsed: boolean;
  onTaskSelect: (workId: string) => void;
}

export function SidebarTree({ rows, collapsed, onTaskSelect }: SidebarTreeProps) {
  return (
    <aside
      className="w-80 shrink-0 border-r border-border bg-surface px-4 py-4"
      hidden={collapsed}
    >
      <div
        className="mb-3 text-sm font-semibold uppercase tracking-wide text-text-secondary"
      >
        Story 树
      </div>
      {!collapsed && (
        <div id="sidebar-story-tree" className="space-y-3">
          {rows.flatMap((epic) =>
            (epic.story_summaries || []).flatMap((story) =>
              (story.task_summaries || []).map((task) => (
                <button
                  key={task.work_id}
                  type="button"
                  data-work-id={task.work_id}
                  onClick={() => onTaskSelect(task.work_id)}
                  className="block w-full rounded-lg border border-border bg-surface-hover px-3 py-2 text-left text-sm text-text"
                >
                  <div className="font-medium">
                    {task.source_issue_number ? `#${task.source_issue_number} ` : ''}
                    {task.title}
                  </div>
                  <div className="text-text-secondary">
                    {story.title}
                  </div>
                </button>
              ))
            )
          )}
        </div>
      )}
    </aside>
  );
}
