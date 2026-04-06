import { NavLink } from 'react-router-dom';
import { Diamond, Palette, Cpu, Settings } from 'lucide-react';
import { useConsoleStore } from '../stores/console-store';
import { ConsoleTabId } from '../types';

const tabs: Array<{ id: ConsoleTabId; label: string; path: string }> = [
  { id: 'kanban', label: '总览', path: '/kanban' },
  { id: 'command', label: '指挥所', path: '/command' },
  { id: 'repository', label: '任务', path: '/repository' },
  { id: 'hierarchy', label: '层级', path: '/hierarchy' },
];

export function TopNav() {
  const store = useConsoleStore();

  // Summary stats for top bar
  const blockedCount = store.workItems.filter((i) => i.status === 'blocked').length;
  const inProgressCount = store.workItems.filter((i) => i.status === 'in_progress').length;
  const decisionCount = store.workItems.filter((i) => i.decisionRequired).length;

  return (
    <header className="border-b border-border bg-surface">
      {/* Primary row: logo + tabs + repo + actions */}
      <div className="flex items-center justify-between gap-4 px-6 py-2.5">
        <div className="flex items-center gap-3">
          <Diamond className="h-5 w-5 text-primary" fill="currentColor" />
          <span className="text-base font-semibold text-text">Taskplane</span>
        </div>

        <div className="flex gap-1.5">
          {tabs.map((tab) => (
            <NavLink
              key={tab.id}
              to={tab.path}
              className={({ isActive }) =>
                `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-primary text-white'
                    : 'text-text-secondary hover:bg-surface-hover'
                }`
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <select
            id="repo-input"
            className="w-40 rounded-md border border-border bg-surface-hover px-2.5 py-1.5 text-xs text-text"
            value={store.repo}
            onChange={(e) => store.setRepo(e.target.value)}
          >
            {store.availableRepos.length === 0 && <option value="">加载中...</option>}
            {store.availableRepos.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => store.handleLoadConsole()}
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white"
          >
            刷新
          </button>
          <button
            type="button"
            onClick={() => store.toggleTheme()}
            className="rounded-md p-1.5 text-text-secondary hover:bg-surface-hover hover:text-primary"
            aria-label="切换主题"
          >
            <Palette className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => store.setConfigPanel('model')}
            className="rounded-md p-1.5 text-text-secondary hover:bg-surface-hover hover:text-primary"
            aria-label="模型配置"
          >
            <Cpu className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => store.setConfigPanel('system')}
            className="rounded-md p-1.5 text-text-secondary hover:bg-surface-hover hover:text-primary"
            aria-label="系统配置"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Secondary row: status badges + filters */}
      {store.repoScope === 'all' && store.workItems.length > 0 && (
        <div className="flex items-center gap-3 border-t border-border px-6 py-1.5 text-xs text-text-secondary">
          <span className="font-medium text-text">{store.workItems.length} 任务</span>
          <span className="text-text-secondary">·</span>
          <span className="text-blue-500">{inProgressCount} 进行中</span>
          <span className="text-text-secondary">·</span>
          <span className="text-red-500">{blockedCount} 阻塞</span>
          <span className="text-text-secondary">·</span>
          <span className="text-orange-500">{decisionCount} 待决策</span>
        </div>
      )}
    </header>
  );
}
