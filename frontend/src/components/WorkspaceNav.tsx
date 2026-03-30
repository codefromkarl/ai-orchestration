import { WorkspaceViewId } from '../types';

interface WorkspaceNavItem {
  id: WorkspaceViewId;
  label: string;
}

interface WorkspaceNavProps {
  items: WorkspaceNavItem[];
  activeView: WorkspaceViewId;
  onSelect: (view: WorkspaceViewId) => void;
}

export function WorkspaceNav({ items, activeView, onSelect }: WorkspaceNavProps) {
  return (
    <aside
      className="w-72 shrink-0 border-r border-border bg-surface px-4 py-4"
    >
      <div
        className="mb-3 text-sm font-semibold uppercase tracking-wide text-text-secondary"
      >
        工作区
      </div>
      <div id="nav-workspace-list" className="space-y-2">
        {items.map((item) => {
          const isActive = item.id === activeView;
          return (
            <button
              key={item.id}
              type="button"
              data-workspace-view={item.id}
              onClick={() => onSelect(item.id)}
              className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                isActive
                  ? 'bg-primary text-white'
                  : 'bg-surface-hover text-text'
              }`}
            >
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
