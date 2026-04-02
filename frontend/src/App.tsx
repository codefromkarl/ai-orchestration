import { useEffect } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { TopNav } from './components/TopNav';
import { KanbanBoard } from './components/KanbanBoard';
import { CommandCenter } from './components/CommandCenter';
import { TaskTable } from './components/TaskTable';
import { DetailDrawer } from './components/DetailDrawer';
import { WorkspaceNav } from './components/WorkspaceNav';
import { WorkspacePanel } from './components/WorkspacePanel';
import { SidebarTree } from './components/SidebarTree';
import { SkeletonLoader } from './components/SkeletonLoader';
import { ConfirmationModal } from './components/ConfirmationModal';
import GovernanceHierarchy from './components/GovernanceHierarchy';
import { TaskStatus } from './types';
import {
  useConsoleStore,
  useFilteredWorkItems,
  useSummaryTitle,
  useSummarySubtitle,
  useSummaryStats,
  useTopRepoAggregateStats,
} from './stores/console-store';

// --- Route path ↔ tab mapping ---
const ROUTE_TAB_MAP: Record<string, string> = {
  '/kanban': 'kanban',
  '/command': 'command',
  '/repository': 'repository',
  '/hierarchy': 'hierarchy',
};

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeTab = (ROUTE_TAB_MAP[location.pathname] || 'kanban') as import('./types').ConsoleTabId;

  // --- Store bindings ---
  const store = useConsoleStore();
  const filteredWorkItems = useFilteredWorkItems();
  const summaryTitle = useSummaryTitle();
  const summarySubtitle = useSummarySubtitle();
  const summaryStats = useSummaryStats();
  const topRepoAggregateStats = useTopRepoAggregateStats();

  // Initialize repos on mount
  useEffect(() => {
    void store.initializeRepos();
  }, []);

  // Auto-dismiss action notice
  useEffect(() => {
    if (!store.actionNotice) return;
    const timer = window.setTimeout(() => useConsoleStore.setState({ actionNotice: null }), 3500);
    return () => window.clearTimeout(timer);
  }, [store.actionNotice]);

  // Sync tab with URL
  useEffect(() => {
    useConsoleStore.setState({ activeTab });
  }, [activeTab]);

  // Clear action state when pendingAction is cleared
  useEffect(() => {
    if (!store.pendingAction) {
      useConsoleStore.setState({ actionError: null, isActionSubmitting: false });
    }
  }, [store.pendingAction]);

  const workspaceItems: Array<{ id: import('./types').WorkspaceViewId; label: string }> = [
    { id: 'epic_overview', label: 'Epic 视图' },
    { id: 'running_jobs', label: '运行中的作业' },
    { id: 'runtime_observability', label: '运行态观测' },
    { id: 'task_repository', label: '任务仓库' },
    { id: 'command_center', label: '指挥中心' },
    { id: 'story_tree', label: '故事树' },
    { id: 'notifications', label: '通知' },
    { id: 'agent_console', label: '智能体控制台' },
    { id: 'system_status', label: '系统状态' },
  ];

  const recentActionHistory = store.actionHistory.slice(0, 6);

  return (
    <div className="h-screen flex flex-col bg-background">
      <TopNav />

      {/* Summary Section */}
      <section className="border-b border-border bg-background px-6 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <h1 id="summary-title" className="text-xl font-semibold text-text">
              {summaryTitle}
            </h1>
            <p className="text-sm text-text-secondary">
              {summarySubtitle}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {summaryStats.map((stat) => (
              <div
                key={stat.label}
                className="min-w-20 rounded-lg border border-border bg-surface px-3 py-2"
              >
                <div className="text-xs uppercase tracking-wide text-text-secondary">
                  {stat.label}
                </div>
                <div className="text-base font-semibold text-text">
                  {stat.value}
                </div>
              </div>
            ))}
          </div>
        </div>

        {store.repoScope === 'all' && topRepoAggregateStats.length > 0 && (
          <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            {topRepoAggregateStats.map((item) => (
              <button
                key={item.repo}
                type="button"
                onClick={() => store.switchToSingleRepo(item.repo)}
                className="rounded-lg border border-border bg-surface px-3 py-2 text-left transition-colors hover:opacity-95"
              >
                <div className="truncate text-sm font-semibold text-text">
                  {item.repo}
                </div>
                <div className="mt-1 text-xs text-text-secondary">
                  任务 {item.totalTasks} · 活跃 {item.activeTasks} · 阻塞 {item.blockedTasks} · 关注 {item.attentionCount}
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Nav Section */}
      <nav
        id="app-nav"
        aria-label="控制台导航"
        className="border-b border-border bg-surface px-6 py-2"
      >
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-nav-l1="overview"
            data-nav-l1-toggle="overview"
            aria-pressed={store.activeNavSection === 'overview'}
            onClick={() => {
              useConsoleStore.setState({ activeNavSection: 'overview', activeWorkspaceView: 'epic_overview' });
            }}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              store.activeNavSection === 'overview'
                ? 'bg-primary text-white'
                : 'bg-transparent text-text-secondary hover:bg-surface-hover'
            }`}
          >
            总览
          </button>
          <button
            type="button"
            data-nav-l1="detail"
            data-nav-l1-toggle="detail"
            aria-pressed={store.activeNavSection === 'detail'}
            onClick={() => useConsoleStore.setState({ activeNavSection: store.selectedItem ? 'detail' : 'overview' })}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              store.activeNavSection === 'detail'
                ? 'bg-primary text-white'
                : 'bg-transparent text-text-secondary hover:bg-surface-hover'
            }`}
          >
            详情
          </button>
        </div>
      </nav>

      {/* Filter Bar */}
      {activeTab !== 'command' && activeTab !== 'hierarchy' && (
        <section className="border-b border-border bg-surface px-6 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="inline-flex rounded-md border border-border p-1">
              <button
                type="button"
                onClick={() => {
                  if (store.repoScope === 'single') return;
                  store.switchToSingleRepo(store.repo);
                }}
                className={`rounded px-2.5 py-1 text-xs font-medium ${
                  store.repoScope === 'single' ? 'bg-primary text-white' : 'bg-transparent text-text-secondary'
                }`}
              >
                单仓库
              </button>
              <button
                type="button"
                onClick={() => {
                  if (store.repoScope === 'all') return;
                  store.setRepoScope('all');
                  void store.loadAllRepos();
                }}
                className={`rounded px-2.5 py-1 text-xs font-medium ${
                  store.repoScope === 'all' ? 'bg-primary text-white' : 'bg-transparent text-text-secondary'
                }`}
              >
                全仓库
              </button>
            </div>

            <select
              value={store.taskStatusFilter}
              onChange={(event) => store.setTaskStatusFilter(event.target.value as TaskStatus | 'all')}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm text-text"
            >
              <option value="all">所有状态</option>
              <option value="pending">待办</option>
              <option value="ready">就绪</option>
              <option value="in_progress">进行中</option>
              <option value="verifying">验证中</option>
              <option value="blocked">阻塞</option>
              <option value="done">完成</option>
            </select>

            <input
              type="text"
              value={store.taskSearchQuery}
              onChange={(event) => store.setTaskSearchQuery(event.target.value)}
              placeholder="搜索仓库 / 任务标题 / 编号..."
              className="min-w-64 flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-text"
            />

            <button
              type="button"
              onClick={() => store.clearFilters()}
              disabled={store.taskSearchQuery.length === 0 && store.taskStatusFilter === 'all'}
              className="rounded-md border border-border bg-surface-hover px-3 py-2 text-sm text-text disabled:cursor-not-allowed disabled:opacity-50"
            >
              清空筛选
            </button>

            <span className="text-sm text-text-secondary">
              任务 {filteredWorkItems.length} / {store.workItems.length}
            </span>
          </div>
        </section>
      )}

      {/* Action History */}
      {recentActionHistory.length > 0 && (
        <section className="border-b border-border bg-surface px-6 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-text-secondary">
              最近操作
            </span>
            {recentActionHistory.map((entry) => (
              <span
                key={entry.id}
                className={`rounded-full px-2 py-1 text-xs ${
                  entry.status === 'success'
                    ? 'bg-[rgba(34,197,94,0.14)] text-[#166534] dark:text-[#86efac]'
                    : 'bg-[rgba(239,68,68,0.14)] text-[#b91c1c] dark:text-[#fca5a5]'
                }`}
                title={`${entry.label} · ${entry.message}`}
              >
                {entry.label} · {entry.message}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-hidden" data-console-tab={activeTab}>
          {store.error && (
            <div className="border-b border-red-200 bg-red-50 p-4 text-red-600">
              {store.error}
            </div>
          )}
          {store.actionNotice && (
            <div className="border-b border-emerald-200 bg-emerald-50 p-4 text-emerald-700">
              {store.actionNotice}
            </div>
          )}

          {store.loading ? (
            <SkeletonLoader variant={activeTab === 'repository' ? 'table' : activeTab === 'hierarchy' ? 'hierarchy' : 'kanban'} />
          ) : (
            <Routes>
              <Route path="/kanban" element={<KanbanView />} />
              <Route path="/command" element={<CommandView />} />
              <Route path="/repository" element={<RepositoryView />} />
              <Route path="/hierarchy" element={<HierarchyPlaceholder />} />
              <Route path="/" element={<Navigate to="/kanban" replace />} />
            </Routes>
          )}
        </div>

        {/* Detail Drawer */}
        <aside
          id="detail-drawer"
          aria-hidden={store.selectedItem ? 'false' : 'true'}
          hidden={!store.selectedItem}
          className="h-full"
        >
          <DetailDrawer
            item={store.selectedItem}
            onClose={store.closeDrawer}
            onStorySelect={(n) => void store.openStoryDetail(n)}
            onTaskSelect={(id, repo) => void store.openTaskDetail(id, repo)}
            onActionSelect={store.handleActionSelect}
          />
        </aside>

        {/* Config Panel */}
        {store.configPanel && (
          <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 px-4">
            <div className="w-full max-w-lg rounded-xl border border-border bg-surface p-5">
              <div className="mb-2 text-lg font-semibold text-text">
                {store.configPanel === 'model' ? '模型配置' : '系统配置'}
              </div>
              <div className="mb-4 text-sm text-text-secondary">
                {store.configPanel === 'model'
                  ? '模型配置入口已恢复，下一步可接入真实模型参数与提供商设置。'
                  : '系统配置入口已恢复，下一步可接入真实控制台级别设置。'}
              </div>
              <div className="rounded-lg border border-border bg-surface-hover px-4 py-3 text-sm text-text">
                {store.configPanel === 'model'
                  ? `当前主题：${store.currentTheme}。此面板当前提供入口恢复与结构占位。`
                  : '该面板当前提供入口恢复与结构占位。'}
              </div>
              <div className="mt-4 flex justify-end">
                <button
                  type="button"
                  onClick={() => store.setConfigPanel(null)}
                  className="rounded-md border border-border bg-surface-hover px-3 py-2 text-sm text-text"
                >
                  关闭
                </button>
              </div>
            </div>
          </div>
        )}

        <ConfirmationModal />
      </div>
    </div>
  );
}

// --- Route sub-views ---

function KanbanView() {
  const store = useConsoleStore();
  const filteredWorkItems = useFilteredWorkItems();
  const workspaceItems: Array<{ id: import('./types').WorkspaceViewId; label: string }> = [
    { id: 'epic_overview', label: 'Epic 视图' },
    { id: 'running_jobs', label: '运行中的作业' },
    { id: 'runtime_observability', label: '运行态观测' },
    { id: 'task_repository', label: '任务仓库' },
    { id: 'command_center', label: '指挥中心' },
    { id: 'story_tree', label: '故事树' },
    { id: 'notifications', label: '通知' },
    { id: 'agent_console', label: '智能体控制台' },
    { id: 'system_status', label: '系统状态' },
  ];

  return (
    <section className="h-full">
      <div className="flex h-full overflow-hidden">
        <div className="flex h-full">
          <button
            id="sidebar-toggle-btn"
            type="button"
            aria-expanded={store.sidebarCollapsed ? 'false' : 'true'}
            onClick={() => store.toggleSidebar()}
            className="m-4 h-10 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text"
          >
            {store.sidebarCollapsed ? '显示侧边栏' : '隐藏侧边栏'}
          </button>
          <SidebarTree
            rows={store.epicTreeRows}
            collapsed={store.sidebarCollapsed}
            onTaskSelect={(id) => void store.openTaskDetail(id)}
          />
          {!store.sidebarCollapsed && (
            <WorkspaceNav
              items={workspaceItems}
              activeView={store.activeWorkspaceView}
              onSelect={(view) => useConsoleStore.setState({ activeWorkspaceView: view })}
            />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <KanbanBoard
            epicRows={store.epicRows}
            onOpenEpicDetail={(n) => void store.openEpicDetail(n)}
            hidden={store.activeWorkspaceView !== 'epic_overview'}
          />
        </div>

        <div
          hidden={store.activeWorkspaceView === 'epic_overview'}
          className="w-[420px] shrink-0 border-l border-border min-w-0"
        >
          <WorkspacePanel
            activeView={store.activeWorkspaceView}
            jobs={store.runningJobs}
            runtimeObservations={store.runtimeObservations}
            tasks={filteredWorkItems}
            notifications={store.notifications}
            failedNotifications={store.failedNotifications}
            agents={store.agents}
            agentStats={store.agentStats}
            attentionItems={store.attentionItems}
            epicRows={store.epicRows}
            epicTreeRows={store.epicTreeRows}
            repoSummary={store.repoSummary}
            onJobClick={(id) => void store.openJobDetail(id)}
            onEpicClick={(n) => void store.openEpicDetail(n)}
            onStoryClick={(n) => void store.openStoryDetail(n)}
            onTaskClick={(id, repo) => void store.openTaskDetail(id, repo)}
          />
        </div>
      </div>
    </section>
  );
}

function CommandView() {
  const store = useConsoleStore();
  return (
    <section className="h-full">
      <CommandCenter
        attentionItems={store.attentionItems}
        commandHistory={store.commandHistory}
        onSendCommand={store.handleSendCommand}
      />
    </section>
  );
}

function RepositoryView() {
  const store = useConsoleStore();
  const filteredWorkItems = useFilteredWorkItems();
  return (
    <section className="h-full">
      <TaskTable
        items={filteredWorkItems}
        totalCount={store.workItems.length}
        onRowClick={store.openCardDetail}
      />
    </section>
  );
}

function HierarchyView() {
  return (
    <GovernanceHierarchy />
  );
}
