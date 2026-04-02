import { create } from 'zustand';
import {
  WorkItem,
  CommandMessage,
  AttentionItem,
  ConsoleTabId,
  ConsoleNavSection,
  RepoSummary,
  EpicOverviewRow,
  DrawerDetailItem,
  WorkspaceViewId,
  RunningJobSummary,
  RuntimeObservationItem,
  NotificationItem,
  AgentStatusItem,
  AgentEfficiencyStat,
  EpicStoryTreeRow,
  TaskStatus,
} from '../types';
import {
  getRepositories,
  getWorkItems,
  getGovernancePriority,
  getRepoSummary,
  getEpicRows,
  getEpicStoryTree,
  getEpicDetail,
  getRunningJobs,
  getRuntimeObservability,
  getJobDetail,
  getNotifications,
  getFailedNotifications,
  getAgents,
  getAgentStats,
  getStoryDetail,
  getTaskDetail,
  postConsoleAction,
} from '../api';
import {
  buildAttentionItems,
  buildEpicDrawerItem,
  buildJobDrawerItem,
  buildLoadedConsoleData,
  buildStoryDrawerItem,
  buildTaskDrawerItem,
  mapWorkItemToDisplay,
} from '../utils/console-view-models';
import { applyTheme, getStoredTheme, Theme } from '../utils/theme-utils';
import {
  CONSOLE_FILTERS_STORAGE_KEY,
  CONSOLE_SIDEBAR_COLLAPSED_STORAGE_KEY,
  getStoredConsoleFilters,
  getStoredSidebarCollapsed,
} from '../utils/console-storage';

// --- Helper types ---
interface RepoAggregateStats {
  repo: string;
  totalTasks: number;
  activeTasks: number;
  blockedTasks: number;
  completedTasks: number;
  attentionCount: number;
}

interface ActionHistoryItem {
  id: string;
  status: 'success' | 'error';
  label: string;
  actionUrl: string;
  message: string;
  timestamp: string;
}

function summarizeActionPayload(payload: Record<string, unknown>): string {
  if (typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail.trim();
  }
  if (typeof payload.error === 'string' && payload.error.trim()) {
    return payload.error.trim();
  }
  const action = typeof payload.action === 'string' ? payload.action : '';
  const accepted = payload.accepted === true ? 'accepted' : '';
  const job = payload.job;
  if (job && typeof job === 'object') {
    const jobKind = typeof (job as { job_kind?: unknown }).job_kind === 'string'
      ? String((job as { job_kind: unknown }).job_kind)
      : '';
    const pid = typeof (job as { pid?: unknown }).pid === 'number'
      ? `pid ${(job as { pid: number }).pid}`
      : '';
    const composed = [action || accepted, jobKind, pid].filter(Boolean).join(' · ');
    if (composed) return composed;
  }
  return action || accepted || '操作已提交';
}

function buildRepoAggregateStats(repo: string, items: WorkItem[], attentionCount: number): RepoAggregateStats {
  const completedTasks = items.filter((item) => item.status === 'done').length;
  const blockedTasks = items.filter((item) => item.status === 'blocked').length;
  const activeTasks = items.length - completedTasks;
  return { repo, totalTasks: items.length, activeTasks, blockedTasks, completedTasks, attentionCount };
}

const DEFAULT_REPO = 'codefromkarl/stardrifter';
const THEMES: Theme[] = ['light', 'dark', 'cyberpunk', 'programmer'];

// --- Store interface ---
export interface ConsoleStore {
  // Navigation
  activeTab: ConsoleTabId;
  activeNavSection: ConsoleNavSection;
  activeWorkspaceView: WorkspaceViewId;
  sidebarCollapsed: boolean;
  // Data
  repo: string;
  repoScope: 'single' | 'all';
  availableRepos: string[];
  workItems: WorkItem[];
  epicRows: EpicOverviewRow[];
  epicTreeRows: EpicStoryTreeRow[];
  runningJobs: RunningJobSummary[];
  runtimeObservations: RuntimeObservationItem[];
  notifications: NotificationItem[];
  failedNotifications: NotificationItem[];
  agents: AgentStatusItem[];
  agentStats: AgentEfficiencyStat[];
  attentionItems: AttentionItem[];
  repoAggregateStats: RepoAggregateStats[];
  repoSummary: RepoSummary | null;
  // Filters
  taskSearchQuery: string;
  taskStatusFilter: TaskStatus | 'all';
  // UI
  loading: boolean;
  error: string | null;
  selectedItem: DrawerDetailItem | null;
  commandHistory: CommandMessage[];
  currentTheme: Theme;
  locale: 'zh' | 'en';
  pendingAction: { actionUrl: string; label: string } | null;
  isActionSubmitting: boolean;
  actionError: string | null;
  actionNotice: string | null;
  actionHistory: ActionHistoryItem[];
  configPanel: 'model' | 'system' | null;

  // Actions — Navigation
  setActiveTab: (tab: ConsoleTabId) => void;
  setActiveNavSection: (section: ConsoleNavSection) => void;
  setActiveWorkspaceView: (view: WorkspaceViewId) => void;
  toggleSidebar: () => void;

  // Actions — Data loading
  initializeRepos: () => Promise<void>;
  loadRepo: (repoName: string) => Promise<void>;
  loadAllRepos: (reposOverride?: string[]) => Promise<void>;
  handleLoadConsole: () => void;
  switchToSingleRepo: (targetRepo: string) => void;

  // Actions — Detail
  openEpicDetail: (epicIssueNumber: number) => Promise<void>;
  openJobDetail: (jobId: number) => Promise<void>;
  openStoryDetail: (storyIssueNumber: number) => Promise<void>;
  openTaskDetail: (workId: string, repoOverride?: string) => Promise<void>;
  openCardDetail: (item: WorkItem) => void;
  closeDrawer: () => void;

  // Actions — Actions
  handleActionSelect: (actionUrl: string, label: string) => void;
  handleConfirmAction: () => Promise<void>;
  handleCancelAction: () => void;

  // Actions — Command
  handleSendCommand: (command: string) => void;

  // Actions — Theme & Locale
  toggleTheme: () => void;
  setLocale: (locale: 'zh' | 'en') => void;

  // Actions — Filters
  setRepo: (repo: string) => void;
  setRepoScope: (scope: 'single' | 'all') => void;
  setTaskSearchQuery: (query: string) => void;
  setTaskStatusFilter: (filter: TaskStatus | 'all') => void;
  clearFilters: () => void;

  // Actions — Config
  setConfigPanel: (panel: 'model' | 'system' | null) => void;
}

const storedFilters = typeof window !== 'undefined' ? getStoredConsoleFilters(window.localStorage) : {};

export const useConsoleStore = create<ConsoleStore>((set, get) => ({
  // Navigation
  activeTab: 'kanban',
  activeNavSection: 'overview',
  activeWorkspaceView: 'epic_overview',
  sidebarCollapsed: typeof window !== 'undefined' ? getStoredSidebarCollapsed(window.localStorage) : false,
  // Data
  repo: storedFilters.repo ?? '',
  repoScope: storedFilters.repoScope ?? 'single',
  availableRepos: [],
  workItems: [],
  epicRows: [],
  epicTreeRows: [],
  runningJobs: [],
  runtimeObservations: [],
  notifications: [],
  failedNotifications: [],
  agents: [],
  agentStats: [],
  attentionItems: [],
  repoAggregateStats: [],
  repoSummary: null,
  // Filters
  taskSearchQuery: storedFilters.taskSearchQuery ?? '',
  taskStatusFilter: storedFilters.taskStatusFilter ?? 'all',
  // UI
  loading: false,
  error: null,
  selectedItem: null,
  commandHistory: [],
  currentTheme: getStoredTheme(),
  locale: 'zh',
  pendingAction: null,
  isActionSubmitting: false,
  actionError: null,
  actionNotice: null,
  actionHistory: [],
  configPanel: null,

  // --- Navigation actions ---
  setActiveTab: (tab) => set({ activeTab: tab }),
  setActiveNavSection: (section) => set({ activeNavSection: section }),
  setActiveWorkspaceView: (view) => set({ activeWorkspaceView: view }),
  toggleSidebar: () => set((state) => {
    const next = !state.sidebarCollapsed;
    try { window.localStorage.setItem(CONSOLE_SIDEBAR_COLLAPSED_STORAGE_KEY, next ? 'true' : 'false'); } catch { /* ignore */ }
    return { sidebarCollapsed: next };
  }),

  // --- Data loading ---
  initializeRepos: async () => {
    try {
      const response = await getRepositories();
      const repoOptions = response.repositories.map((item) => item.repo).filter(Boolean);
      const { repo, repoScope } = get();

      set({ availableRepos: repoOptions });

      const preferredRepo = repo && repoOptions.includes(repo) ? repo : '';
      const initialRepo = preferredRepo || (repoOptions.includes(DEFAULT_REPO)
        ? DEFAULT_REPO
        : repoOptions[0] || '');

      if (!initialRepo && repoScope !== 'all') return;

      if (initialRepo) set({ repo: initialRepo });

      if (repoScope === 'all') {
        void get().loadAllRepos(repoOptions);
      } else if (initialRepo) {
        void get().loadRepo(initialRepo);
      }
    } catch {
      set({ availableRepos: [] });
    }
  },

  loadRepo: async (repoName: string) => {
    if (!repoName) return;
    set({ loading: true, error: null });

    try {
      const [
        workItemsResponse,
        priorityResponse,
        epicRowsResponse,
        epicStoryTreeResponse,
        runningJobsResponse,
        runtimeObservabilityResponse,
        notificationsResponse,
        failedNotificationsResponse,
        agentsResponse,
        agentStatsResponse,
      ] = await Promise.all([
        getWorkItems(repoName),
        getGovernancePriority(repoName).catch(() => ({ tasks: [] })),
        getEpicRows(repoName).catch(() => ({ repo: repoName, rows: [] })),
        getEpicStoryTree(repoName).catch(() => ({ repo: repoName, rows: [] })),
        getRunningJobs(repoName).catch(() => ({ repo: repoName, jobs: [] })),
        getRuntimeObservability(repoName).catch(() => ({ repo: repoName, items: [] })),
        getNotifications(repoName).catch(() => ({ notifications: [] })),
        getFailedNotifications(repoName).catch(() => ({ notifications: [] })),
        getAgents(repoName).catch(() => ({ agents: [] })),
        getAgentStats().catch(() => ({ stats: [] })),
      ]);

      const summaryResponse = await getRepoSummary(repoName).catch(() => null);
      const loadedData = buildLoadedConsoleData({
        repoName,
        workItemsResponse,
        epicRowsResponse,
        epicStoryTreeResponse,
        runningJobsResponse,
        notificationsResponse,
        failedNotificationsResponse,
        agentsResponse,
        agentStatsResponse,
        summaryResponse,
        priorityResponse,
      });

      set({
        workItems: loadedData.workItems,
        epicRows: loadedData.epicRows,
        epicTreeRows: loadedData.epicTreeRows,
        runningJobs: loadedData.runningJobs,
        runtimeObservations: runtimeObservabilityResponse.items.map((item) => ({
          workId: item.work_id,
          issueNumber: item.source_issue_number,
          title: item.title || item.work_id,
          status: item.status as TaskStatus | undefined,
          lane: item.lane,
          wave: item.wave,
          blockedReason: item.blocked_reason,
          decisionRequired: item.decision_required,
          lastFailureReason: item.last_failure_reason,
          workerName: item.active_claim_worker_name,
          sessionId: item.session_id,
          sessionStatus: item.session_status,
          sessionAttemptIndex: item.session_attempt_index,
          sessionCurrentPhase: item.session_current_phase,
          sessionWaitingReason: item.session_waiting_reason,
          sessionUpdatedAt: item.session_updated_at,
          checkpointSummary: item.last_checkpoint_summary,
          checkpointNextAction: item.last_checkpoint_next_action,
          artifactId: item.artifact_id,
          artifactType: item.artifact_type,
          artifactKey: item.artifact_key,
          artifactSummary: typeof item.artifact_metadata?.summary === 'string'
            ? item.artifact_metadata.summary
            : undefined,
          artifactCreatedAt: item.artifact_created_at,
        })),
        notifications: loadedData.notifications,
        failedNotifications: loadedData.failedNotifications,
        agents: loadedData.agents,
        agentStats: loadedData.agentStats,
        repoSummary: loadedData.repoSummary,
        attentionItems: loadedData.attentionItems,
        repoAggregateStats: [],
        selectedItem: null,
        activeNavSection: 'overview',
        activeWorkspaceView: 'epic_overview',
        loading: false,
      });
    } catch (err) {
      set({
        epicRows: [],
        epicTreeRows: [],
        runningJobs: [],
        runtimeObservations: [],
        notifications: [],
        failedNotifications: [],
        agents: [],
        agentStats: [],
        repoSummary: null,
        repoAggregateStats: [],
        error: err instanceof Error ? err.message : '加载失败',
        loading: false,
      });
    }
  },

  loadAllRepos: async (reposOverride?: string[]) => {
    const { availableRepos, repoScope, activeTab } = get();
    const repos = (reposOverride ?? availableRepos).filter(Boolean);
    if (repos.length === 0) {
      set({ error: '当前没有可用仓库，无法切换到全仓库视角。', repoAggregateStats: [] });
      return;
    }

    set({ loading: true, error: null });

    try {
      const [workItemResponses, priorityResponses, summaryResponses] = await Promise.all([
        Promise.all(repos.map(async (repoName) => {
          try { return await getWorkItems(repoName); } catch { return { repo: repoName, items: [], count: 0 }; }
        })),
        Promise.all(repos.map(async (repoName) => {
          try { return await getGovernancePriority(repoName); } catch { return { tasks: [] }; }
        })),
        Promise.all(repos.map(async (repoName) => {
          try { return await getRepoSummary(repoName); } catch { return null; }
        })),
      ]);

      const mergedWorkItems = workItemResponses.flatMap((response, index) => {
        const repoName = repos[index];
        return response.items.map((item) => mapWorkItemToDisplay(item, repoName));
      });

      const mergedAttention = priorityResponses
        .flatMap((response, index) => {
          const repoName = repos[index];
          return buildAttentionItems(response).map((item) => ({
            ...item,
            id: `${repoName}:${item.id}`,
            title: `[${repoName}] ${item.title}`,
          }));
        })
        .sort((a, b) => b.priorityScore - a.priorityScore)
        .slice(0, 120);

      const aggregateStats = repos.map((repoName, index) => {
        const scopedItems = mergedWorkItems.filter((item) => item.repo === repoName);
        const attentionCount = mergedAttention.filter((item) => item.title.startsWith(`[${repoName}]`)).length;
        const summary = summaryResponses[index];
        if (summary) {
          return {
            repo: repoName,
            totalTasks: summary.total_tasks ?? summary.summary?.total_tasks ?? scopedItems.length,
            activeTasks: summary.active_tasks ?? summary.summary?.active_tasks ?? scopedItems.filter((item) => item.status !== 'done').length,
            blockedTasks: summary.blocked_tasks ?? summary.summary?.blocked_tasks ?? scopedItems.filter((item) => item.status === 'blocked').length,
            completedTasks: summary.completed_tasks ?? summary.summary?.completed_tasks ?? scopedItems.filter((item) => item.status === 'done').length,
            attentionCount,
          } as RepoAggregateStats;
        }
        return buildRepoAggregateStats(repoName, scopedItems, attentionCount);
      });

      const completedTasks = aggregateStats.reduce((sum, item) => sum + item.completedTasks, 0);
      const blockedTasks = aggregateStats.reduce((sum, item) => sum + item.blockedTasks, 0);
      const activeTasks = aggregateStats.reduce((sum, item) => sum + item.activeTasks, 0);

      const newTab = activeTab === 'kanban' ? 'repository' as ConsoleTabId : activeTab;

      set({
        workItems: mergedWorkItems,
        attentionItems: mergedAttention,
        repoAggregateStats: aggregateStats,
        epicRows: [],
        epicTreeRows: [],
        runningJobs: [],
        runtimeObservations: [],
        notifications: [],
        failedNotifications: [],
        agents: [],
        agentStats: [],
        selectedItem: null,
        activeNavSection: 'overview',
        activeWorkspaceView: 'task_repository',
        repoSummary: {
          repo: 'all',
          totalEpics: 0,
          totalStories: 0,
          totalTasks: mergedWorkItems.length,
          activeTasks,
          completedTasks,
          blockedTasks,
        },
        activeTab: newTab,
        loading: false,
      });
    } catch (err) {
      set({
        repoAggregateStats: [],
        error: err instanceof Error ? err.message : '全仓库数据加载失败',
        loading: false,
      });
    }
  },

  handleLoadConsole: () => {
    const { repoScope, repo, loadAllRepos, loadRepo } = get();
    if (repoScope === 'all') {
      void loadAllRepos();
    } else {
      void loadRepo(repo);
    }
  },

  switchToSingleRepo: (targetRepo: string) => {
    const { availableRepos } = get();
    const fallbackRepo = targetRepo || availableRepos[0] || '';
    if (!fallbackRepo) {
      set({ error: '没有可用仓库可切换。' });
      return;
    }
    set({ repoScope: 'single', repo: fallbackRepo });
    void get().loadRepo(fallbackRepo);
  },

  // --- Detail actions ---
  openEpicDetail: async (epicIssueNumber: number) => {
    const { repo, epicRows } = get();
    if (!repo) return;
    try {
      const detail = await getEpicDetail(repo, epicIssueNumber);
      const matchingRow = epicRows.find((row) => row.epic_issue_number === epicIssueNumber);
      set({
        selectedItem: buildEpicDrawerItem({ detail, matchingRow }),
        activeNavSection: 'detail',
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Epic 详情加载失败' });
    }
  },

  openJobDetail: async (jobId: number) => {
    const { repo } = get();
    if (!repo) return;
    try {
      const detail = await getJobDetail(repo, jobId);
      set({
        selectedItem: buildJobDrawerItem(detail),
        activeNavSection: 'detail',
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Job 详情加载失败' });
    }
  },

  openStoryDetail: async (storyIssueNumber: number) => {
    const { repo } = get();
    if (!repo) return;
    try {
      const detail = await getStoryDetail(repo, storyIssueNumber);
      set({
        selectedItem: buildStoryDrawerItem({ detail, repo, storyIssueNumber }),
        activeNavSection: 'detail',
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Story 详情加载失败' });
    }
  },

  openTaskDetail: async (workId: string, repoOverride?: string) => {
    const { repo } = get();
    const targetRepo = repoOverride || repo;
    if (!targetRepo) return;
    try {
      const detail = await getTaskDetail(targetRepo, workId);
      set({
        selectedItem: buildTaskDrawerItem({ detail, repo: targetRepo, workId }),
        activeNavSection: 'detail',
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Task 详情加载失败' });
    }
  },

  openCardDetail: (item: WorkItem) => {
    if (item.id) {
      void get().openTaskDetail(item.id, item.repo);
      return;
    }
    set({
      selectedItem: {
        kind: 'task',
        number: item.number,
        title: item.title,
        type: item.type,
        status: item.status,
        lane: item.lane,
        wave: item.wave,
        complexity: item.complexity,
        blockedReason: item.blockedReason,
        decisionRequired: item.decisionRequired,
        githubUrl: item.githubUrl,
        epicNumber: item.epicNumber,
        storyNumber: item.storyNumber,
        priority: item.priority,
        metaSummary: item.repo ? `repo: ${item.repo}` : undefined,
      },
      activeNavSection: 'detail',
    });
  },

  closeDrawer: () => set({ selectedItem: null, activeNavSection: 'overview' }),

  // --- Action handlers ---
  handleActionSelect: (actionUrl: string, label: string) => {
    set({ pendingAction: { actionUrl, label }, actionError: null });
  },

  handleConfirmAction: async () => {
    const { pendingAction, repoScope, repo } = get();
    if (!pendingAction) return;
    if (repoScope === 'single' && !repo) {
      set({ actionError: '请先选择仓库后再执行操作。' });
      return;
    }

    const action = pendingAction;
    set({ isActionSubmitting: true, actionError: null });

    try {
      const payload = await postConsoleAction(action.actionUrl);
      const message = summarizeActionPayload(payload);
      const { actionHistory } = get();
      const newHistory: ActionHistoryItem = {
        id: `action-${Date.now()}`,
        status: 'success',
        label: action.label,
        actionUrl: action.actionUrl,
        message,
        timestamp: new Date().toISOString(),
      };
      set({
        pendingAction: null,
        selectedItem: null,
        activeNavSection: 'overview',
        actionNotice: `已提交操作：${action.label} · ${message}`,
        actionHistory: [newHistory, ...actionHistory].slice(0, 12),
        isActionSubmitting: false,
      });

      // Reload data
      if (repoScope === 'all') {
        await get().loadAllRepos();
      } else {
        await get().loadRepo(repo);
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '操作执行失败';
      const { actionHistory } = get();
      const newHistory: ActionHistoryItem = {
        id: `action-${Date.now()}`,
        status: 'error',
        label: action.label,
        actionUrl: action.actionUrl,
        message: errorMessage,
        timestamp: new Date().toISOString(),
      };
      set({
        actionError: errorMessage,
        actionHistory: [newHistory, ...actionHistory].slice(0, 12),
        isActionSubmitting: false,
      });
    }
  },

  handleCancelAction: () => {
    const { isActionSubmitting } = get();
    if (!isActionSubmitting) {
      set({ pendingAction: null, actionError: null });
    }
  },

  // --- Command ---
  handleSendCommand: (command: string) => {
    const { commandHistory } = get();
    const userMessage: CommandMessage = {
      id: `msg-${Date.now()}-user`,
      type: 'user',
      content: command,
      timestamp: new Date(),
    };
    const systemMessage: CommandMessage = {
      id: `msg-${Date.now()}-system`,
      type: 'system',
      content: `收到指令：${command}。正在处理...`,
      timestamp: new Date(),
    };
    set({ commandHistory: [...commandHistory, userMessage, systemMessage] });
  },

  // --- Theme & Locale ---
  toggleTheme: () => {
    const { currentTheme } = get();
    const nextTheme = THEMES[(THEMES.indexOf(currentTheme) + 1) % THEMES.length];
    applyTheme(nextTheme);
    set({ currentTheme: nextTheme });
  },

  setLocale: (locale: 'zh' | 'en') => {
    const { repoSummary } = get();
    if (locale === 'zh' && repoSummary?.repo) {
      set({ locale, repoSummary: { ...repoSummary, repo: '' } });
    } else {
      set({ locale });
    }
  },

  // --- Filters ---
  setRepo: (repo: string) => {
    set({ repo });
    persistFilters({ ...getFilterSnapshot(get()), repo });
  },
  setRepoScope: (scope: 'single' | 'all') => set({ repoScope: scope }),
  setTaskSearchQuery: (query: string) => {
    set({ taskSearchQuery: query });
    persistFilters({ ...getFilterSnapshot(get()), taskSearchQuery: query });
  },
  setTaskStatusFilter: (filter: TaskStatus | 'all') => {
    set({ taskStatusFilter: filter });
    persistFilters({ ...getFilterSnapshot(get()), taskStatusFilter: filter });
  },
  clearFilters: () => {
    set({ taskSearchQuery: '', taskStatusFilter: 'all' });
    persistFilters({ repoScope: get().repoScope, repo: get().repo, taskSearchQuery: '', taskStatusFilter: 'all' });
  },

  // --- Config ---
  setConfigPanel: (panel) => set({ configPanel: panel }),
}));

// --- Helpers ---
function getFilterSnapshot(state: ConsoleStore) {
  return {
    repoScope: state.repoScope,
    repo: state.repo,
    taskStatusFilter: state.taskStatusFilter,
    taskSearchQuery: state.taskSearchQuery,
  };
}

function persistFilters(filters: {
  repoScope: 'single' | 'all';
  repo: string;
  taskStatusFilter: TaskStatus | 'all';
  taskSearchQuery: string;
}) {
  try {
    window.localStorage.setItem(CONSOLE_FILTERS_STORAGE_KEY, JSON.stringify(filters));
  } catch { /* ignore */ }
}

// --- Computed selectors ---
export function useFilteredWorkItems() {
  const workItems = useConsoleStore((s) => s.workItems);
  const taskSearchQuery = useConsoleStore((s) => s.taskSearchQuery);
  const taskStatusFilter = useConsoleStore((s) => s.taskStatusFilter);

  const keyword = taskSearchQuery.trim().toLowerCase();
  return workItems.filter((item) => {
    const matchesStatus = taskStatusFilter === 'all' || item.status === taskStatusFilter;
    if (!matchesStatus) return false;
    if (!keyword) return true;
    const numberText = String(item.number);
    return (
      item.title.toLowerCase().includes(keyword) ||
      numberText.includes(keyword) ||
      (item.repo ? item.repo.toLowerCase().includes(keyword) : false)
    );
  });
}

export function useSummaryTitle() {
  const { repoScope, repoSummary, locale } = useConsoleStore();
  if (repoScope === 'all') {
    return locale === 'zh' ? '仓库控制台 · 全仓库' : 'Repository Console · All Repositories';
  }
  if (repoSummary?.repo) {
    return locale === 'zh' ? `仓库控制台 · ${repoSummary.repo}` : `Repository Console · ${repoSummary.repo}`;
  }
  return locale === 'zh' ? '仓库控制台' : 'Repository Console';
}

export function useSummarySubtitle() {
  const { repoScope, repoSummary, locale } = useConsoleStore();
  if (repoScope === 'all') {
    return locale === 'zh' ? '跨仓库聚合任务视图' : 'Cross-repository aggregated task view';
  }
  if (repoSummary?.repo) {
    return repoSummary.repo;
  }
  return locale === 'zh' ? '静态 /console 兼容壳层' : 'Static /console compatibility shell';
}

export function useSummaryStats() {
  const { repoSummary, workItems, attentionItems } = useConsoleStore();
  if (repoSummary) {
    return [
      { label: '史诗', value: repoSummary.totalEpics },
      { label: '故事', value: repoSummary.totalStories },
      { label: '任务', value: repoSummary.totalTasks },
      { label: '活跃', value: repoSummary.activeTasks },
      { label: '阻塞', value: repoSummary.blockedTasks },
    ];
  }
  return [
    { label: '任务', value: workItems.length },
    { label: '关注项', value: attentionItems.length },
  ];
}

export function useTopRepoAggregateStats() {
  const repoAggregateStats = useConsoleStore((s) => s.repoAggregateStats);
  return [...repoAggregateStats]
    .sort((a, b) => {
      const scoreA = a.blockedTasks * 3 + a.attentionCount * 2 + a.activeTasks;
      const scoreB = b.blockedTasks * 3 + b.attentionCount * 2 + b.activeTasks;
      return scoreB - scoreA;
    })
    .slice(0, 8);
}
