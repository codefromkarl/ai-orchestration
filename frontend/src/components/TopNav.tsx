import { NavLink, useNavigate } from 'react-router-dom';
import { Diamond, Settings, Cpu, Palette } from 'lucide-react';
import { useConsoleStore } from '../stores/console-store';
import { ConsoleTabId } from '../types';

const tabs: Array<{ id: ConsoleTabId; label: string; path: string }> = [
  { id: 'kanban', label: '信息室', path: '/kanban' },
  { id: 'command', label: '指挥所', path: '/command' },
  { id: 'repository', label: '任务仓库', path: '/repository' },
  { id: 'hierarchy', label: '治理层级', path: '/hierarchy' },
];

export function TopNav() {
  const navigate = useNavigate();
  const store = useConsoleStore();

  return (
    <header className="border-b border-border bg-surface px-6 py-3">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Diamond
            className="h-5 w-5 text-primary"
            fill="currentColor"
          />
          <span className="text-lg font-semibold text-text">
            Stardrifter
          </span>
        </div>

        <div className="flex gap-2">
          {tabs.map((tab) => (
            <NavLink
              key={tab.id}
              to={tab.path}
              className={({ isActive }) =>
                `rounded-full px-4 py-1.5 text-sm font-medium transition-all ${
                  isActive
                    ? 'text-white shadow-sm'
                    : 'text-text-secondary hover:bg-surface-hover'
                }`
              }
              style={({ isActive }) =>
                isActive
                  ? { background: 'linear-gradient(to right, var(--color-primary), var(--color-primary-hover))' }
                  : { backgroundColor: 'transparent' }
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <select
            id="repo-input"
            className="w-48 rounded-md border border-border bg-surface-hover px-3 py-1 text-sm text-text"
            value={store.repo}
            onChange={(e) => store.setRepo(e.target.value)}
          >
            {store.availableRepos.length === 0 && <option value="">可用仓库加载中...</option>}
            {store.availableRepos.map((repoOption) => (
              <option key={repoOption} value={repoOption}>
                {repoOption}
              </option>
            ))}
          </select>
          <button
            id="load-console-btn"
            type="button"
            onClick={() => store.handleLoadConsole()}
            className="rounded-md px-3 py-1 text-sm font-medium text-white"
            style={{
              background: 'linear-gradient(to right, var(--color-primary), var(--color-primary-hover))',
            }}
          >
            加载
          </button>
          <div className="flex items-center gap-1 rounded-md border border-border px-1 py-1">
            <button
              id="locale-en-btn"
              type="button"
              onClick={() => store.setLocale('en')}
              className={`rounded px-2 py-1 text-xs font-medium ${
                store.locale === 'en' ? 'bg-primary text-white' : 'bg-transparent text-text-secondary'
              }`}
            >
              EN
            </button>
            <button
              id="locale-zh-btn"
              type="button"
              onClick={() => store.setLocale('zh')}
              className={`rounded px-2 py-1 text-xs font-medium ${
                store.locale === 'zh' ? 'bg-primary text-white' : 'bg-transparent text-text-secondary'
              }`}
            >
              中文
            </button>
          </div>
          <button
            type="button"
            onClick={() => store.toggleTheme()}
            className="rounded-md p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-primary"
            title={`主题：${store.currentTheme}`}
            aria-label={`切换主题，当前为 ${store.currentTheme}`}
          >
            <Palette className="h-5 w-5" />
          </button>
          <button
            type="button"
            onClick={() => store.setConfigPanel('model')}
            className="rounded-md p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-primary"
            title="模型配置"
          >
            <Cpu className="h-5 w-5" />
          </button>
          <button
            type="button"
            onClick={() => store.setConfigPanel('system')}
            className="rounded-md p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-primary"
            title="系统配置"
          >
            <Settings className="h-5 w-5" />
          </button>
        </div>
      </div>
    </header>
  );
}
