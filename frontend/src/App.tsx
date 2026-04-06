import { useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { TopNav } from './components/TopNav';
import { KanbanBoard } from './components/KanbanBoard';
import { CommandCenter } from './components/CommandCenter';
import { TaskTable } from './components/TaskTable';
import { DetailDrawer } from './components/DetailDrawer';
import { SidebarTree } from './components/SidebarTree';
import { SkeletonLoader } from './components/SkeletonLoader';
import { ConfirmationModal } from './components/ConfirmationModal';
import { OrchestratorBar } from './components/OrchestratorBar';
import GovernanceHierarchy from './components/GovernanceHierarchy';
import { SystemPanel } from './components/SystemPanel';
import {
  useConsoleStore,
  useFilteredWorkItems,
  useSummaryStats,
} from './stores/console-store';

const ROUTE_TAB_MAP: Record<string, string> = {
  '/kanban': 'kanban',
  '/command': 'command',
  '/repository': 'repository',
  '/hierarchy': 'hierarchy',
};

export default function App() {
  const location = useLocation();
  const store = useConsoleStore();
  const filteredWorkItems = useFilteredWorkItems();
  const summaryStats = useSummaryStats();
  const activeTab = (ROUTE_TAB_MAP[location.pathname] || 'kanban') as import('./types').ConsoleTabId;

  useEffect(() => { void store.initializeRepos(); }, []);
  useEffect(() => {
    if (!store.actionNotice) return;
    const timer = window.setTimeout(() => useConsoleStore.setState({ actionNotice: null }), 3500);
    return () => window.clearTimeout(timer);
  }, [store.actionNotice]);
  useEffect(() => {
    useConsoleStore.setState({ activeTab });
  }, [activeTab]);
  useEffect(() => {
    if (!store.pendingAction) {
      useConsoleStore.setState({ actionError: null, isActionSubmitting: false });
    }
  }, [store.pendingAction]);

  const blockedCount = store.workItems.filter((i) => i.status === 'blocked').length;
  const decisionCount = store.workItems.filter((i) => i.decisionRequired).length;
  const runningCount = store.runningJobs.length;

  return (
    <div className="h-screen flex flex-col bg-background">
      <TopNav />

      {/* Status bar */}
      {store.repoScope === 'single' && store.workItems.length > 0 && (
        <div className="flex items-center gap-4 border-b border-border bg-surface px-6 py-1.5 text-xs text-text-secondary">
          {summaryStats.map((stat) => (
            <span key={stat.label}>
              {stat.label} <span className="font-medium text-text">{stat.value}</span>
            </span>
          ))}
          {runningCount > 0 && (
            <>
              <span className="text-text-secondary">·</span>
              <span className="text-blue-500">{runningCount} 运行中</span>
            </>
          )}
          {blockedCount > 0 && (
            <>
              <span className="text-text-secondary">·</span>
              <span className="text-red-500">{blockedCount} 阻塞</span>
            </>
          )}
          {decisionCount > 0 && (
            <>
              <span className="text-text-secondary">·</span>
              <span className="text-orange-500">{decisionCount} 待决策</span>
            </>
          )}
        </div>
      )}

      {activeTab === 'kanban' && (
        <OrchestratorBar
          blockedItems={store.workItems.filter((i) => i.status === 'blocked')}
          decisionItems={store.workItems.filter((i) => i.decisionRequired)}
          runningJobs={store.runningJobs}
          attentionItems={store.attentionItems}
          onTaskClick={(id, repo) => void store.openTaskDetail(id, repo)}
          onJobClick={(id) => void store.openJobDetail(id)}
        />
      )}

      {/* Filter bar — only for kanban/repository */}
      {activeTab !== 'command' && activeTab !== 'hierarchy' && (
        <section className="border-b border-border bg-surface px-6 py-2">
          <div className="flex items-center gap-3">
            <div className="inline-flex rounded-md border border-border p-0.5">
              <button
                type="button"
                onClick={() => {
                  if (store.repoScope === 'single') return;
                  store.switchToSingleRepo(store.repo);
                }}
                className={`rounded px-2 py-1 text-xs font-medium ${
                  store.repoScope === 'single' ? 'bg-primary text-white' : 'text-text-secondary'
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
                className={`rounded px-2 py-1 text-xs font-medium ${
                  store.repoScope === 'all' ? 'bg-primary text-white' : 'text-text-secondary'
                }`}
              >
                全仓库
              </button>
            </div>

            <select
              value={store.taskStatusFilter}
              onChange={(e) => store.setTaskStatusFilter(e.target.value as import('./types').TaskStatus | 'all')}
              className="rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-text"
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
              onChange={(e) => store.setTaskSearchQuery(e.target.value)}
              placeholder="搜索..."
              className="min-w-48 flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-text"
            />

            <button
              type="button"
              onClick={() => store.clearFilters()}
              disabled={store.taskSearchQuery.length === 0 && store.taskStatusFilter === 'all'}
              className="rounded-md border border-border bg-surface-hover px-2.5 py-1.5 text-xs text-text disabled:opacity-50"
            >
              清空
            </button>

            <span className="text-xs text-text-secondary">
              {filteredWorkItems.length} / {store.workItems.length}
            </span>
          </div>
        </section>
      )}

      {/* Action History */}
      {store.actionHistory.length > 0 && (
        <section className="border-b border-border bg-surface px-6 py-1.5">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-text-secondary">最近</span>
            {store.actionHistory.slice(0, 4).map((entry) => (
              <span
                key={entry.id}
                className={`rounded-full px-2 py-0.5 text-[11px] ${
                  entry.status === 'success'
                    ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                    : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                }`}
                title={`${entry.label} · ${entry.message}`}
              >
                {entry.label}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-hidden" data-console-tab={activeTab}>
          {store.error && (
            <div className="border-b border-red-200 bg-red-50 p-3 text-sm text-red-600">{store.error}</div>
          )}
          {store.actionNotice && (
            <div className="border-b border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{store.actionNotice}</div>
          )}

          {store.loading ? (
            <SkeletonLoader variant={activeTab === 'repository' ? 'table' : activeTab === 'hierarchy' ? 'hierarchy' : 'kanban'} />
          ) : (
            <Routes>
              <Route path="/kanban" element={<KanbanView />} />
              <Route path="/command" element={<CommandView />} />
              <Route path="/repository" element={<RepositoryView />} />
              <Route path="/hierarchy" element={<GovernanceHierarchy />} />
              <Route path="/" element={<Navigate to="/kanban" replace />} />
            </Routes>
          )}
        </div>

        {/* Sidebar Tree */}
        {activeTab === 'kanban' && (
          <SidebarTree
            rows={store.epicTreeRows}
            collapsed={store.sidebarCollapsed}
            onTaskSelect={(id) => void store.openTaskDetail(id)}
          />
        )}

        {/* Detail Drawer */}
        <DetailDrawer
          item={store.selectedItem}
          onClose={store.closeDrawer}
          onStorySelect={(n) => void store.openStoryDetail(n)}
          onTaskSelect={(id) => void store.openTaskDetail(id)}
          onActionSelect={store.handleActionSelect}
        />

        <ConfirmationModal />
        <SystemPanel
          mode={store.configPanel}
          systemStatus={store.systemStatus}
          onClose={() => store.setConfigPanel(null)}
        />
      </div>
    </div>
  );
}

function KanbanView() {
  const store = useConsoleStore();
  return (
    <KanbanBoard
      epicRows={store.epicRows}
      repo={store.repo}
      systemStatus={store.systemStatus}
      onOpenSystemPanel={() => store.setConfigPanel('system')}
      onOpenEpicDetail={(n) => void store.openEpicDetail(n)}
    />
  );
}

function CommandView() {
  const store = useConsoleStore();
  return (
    <CommandCenter
      intents={store.intents}
      selectedIntentId={store.selectedIntentId}
      isSubmitting={store.isIntakeSubmitting}
      systemStatus={store.systemStatus}
      onSendCommand={store.handleSendCommand}
      onSelectIntent={store.selectIntent}
      onApproveSelectedIntent={store.approveSelectedIntent}
      onRejectSelectedIntent={(reason) => void store.rejectSelectedIntent(reason)}
      onReviseSelectedIntent={(feedback) => void store.reviseSelectedIntent(feedback)}
    />
  );
}

function RepositoryView() {
  const store = useConsoleStore();
  const filteredWorkItems = useFilteredWorkItems();
  return (
    <TaskTable
      items={filteredWorkItems}
      totalCount={store.workItems.length}
      onRowClick={store.openCardDetail}
    />
  );
}
