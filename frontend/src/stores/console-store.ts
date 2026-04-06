import { create } from 'zustand';
import {
  WorkItem,
  AttentionItem,
  ConsoleTabId,
  RepoSummary,
  SystemStatus,
  EpicOverviewRow,
  DrawerDetailItem,
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
  getSystemStatus,
  getIntents,
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
  submitIntent,
  answerIntent,
  approveIntent,
  rejectIntent,
  reviseIntent,
} from '../api';
import {
  createInitialIntakeState,
  createIntakeSlice,
  type IntakeSliceActions,
  type IntakeSliceState,
} from './console-intake-slice';
import {
  buildSummaryStats,
  filterWorkItems,
  getTopRepoAggregateStats,
  type RepoAggregateStats,
} from './console-selectors';
import {
  buildAllReposPatch,
  buildSingleRepoPatch,
  resolveRepoInitialization,
} from './console-repo-data-helpers';
import {
  buildAttentionItems,
  buildEpicDrawerItem,
  buildJobDrawerItem,
  buildLoadedConsoleData,
  buildStoryDrawerItem,
  buildTaskDrawerItem,
} from '../utils/console-view-models';
import { applyTheme, getStoredTheme, Theme } from '../utils/theme-utils';
import {
  CONSOLE_FILTERS_STORAGE_KEY,
  CONSOLE_SIDEBAR_COLLAPSED_STORAGE_KEY,
  getStoredConsoleFilters,
  getStoredSidebarCollapsed,
} from '../utils/console-storage';

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

const DEFAULT_REPO = 'codefromkarl/stardrifter';
const THEMES: Theme[] = ['light', 'dark', 'cyberpunk', 'programmer'];
const intakeDependencies = {
  submitIntent,
  answerIntent,
  approveIntent,
  rejectIntent,
  reviseIntent,
};

// --- Store interface ---
export interface ConsoleStore extends IntakeSliceState, IntakeSliceActions {
  // Navigation
  activeTab: ConsoleTabId;
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
  systemStatus: SystemStatus | null;
  // Filters
  taskSearchQuery: string;
  taskStatusFilter: TaskStatus | 'all';
  // UI
  loading: boolean;
  error: string | null;
  selectedItem: DrawerDetailItem | null;
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

export const useConsoleStore = create<ConsoleStore>((set, get, store) => ({
  // Navigation
  activeTab: 'kanban',
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
  ...createInitialIntakeState(),
  repoAggregateStats: [],
  repoSummary: null,
  systemStatus: null,
  // Filters
  taskSearchQuery: storedFilters.taskSearchQuery ?? '',
  taskStatusFilter: storedFilters.taskStatusFilter ?? 'all',
  // UI
  loading: false,
  error: null,
  selectedItem: null,
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
  toggleSidebar: () => set((state) => {
    const next = !state.sidebarCollapsed;
    try { window.localStorage.setItem(CONSOLE_SIDEBAR_COLLAPSED_STORAGE_KEY, next ? 'true' : 'false'); } catch { /* ignore */ }
    return { sidebarCollapsed: next };
  }),
  ...createIntakeSlice(intakeDependencies)(set, get, store),

  // --- Data loading ---
  initializeRepos: async () => {
    try {
      const [systemStatusResponse, repositoryResponse] = await Promise.all([
        getSystemStatus().catch(() => null),
        getRepositories().catch(() => ({ repositories: [] })),
      ]);
      const { repo, repoScope } = get();
      const { repoOptions, initialRepo } = resolveRepoInitialization({
        currentRepo: repo,
        repoScope,
        repositoryRepos: repositoryResponse.repositories.map((item) => item.repo).filter(Boolean),
        systemStatus: systemStatusResponse,
        defaultRepo: DEFAULT_REPO,
      });

      set({ availableRepos: repoOptions, systemStatus: systemStatusResponse });

      if (!initialRepo && repoScope !== 'all') return;

      if (initialRepo) set({ repo: initialRepo });

      if (repoScope === 'all') {
        void get().loadAllRepos(repoOptions);
      } else if (initialRepo) {
        void get().loadRepo(initialRepo);
      }
    } catch {
      set({ availableRepos: [], systemStatus: null });
    }
  },

  loadRepo: async (repoName: string) => {
    if (!repoName) return;
    set({ loading: true, error: null });

    try {
      const [
        workItemsResponse,
        intentsResponse,
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
        getIntents(repoName).catch(() => ({ repo: repoName, items: [], count: 0 })),
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
        intentsResponse,
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

      set(
        buildSingleRepoPatch({
          loadedData,
          intents: intentsResponse.items,
          runtimeObservationItems: runtimeObservabilityResponse.items,
          systemStatus: get().systemStatus,
        }),
      );
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
        intents: [],
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

      set(
        buildAllReposPatch({
          repos,
          workItemResponses,
          attentionItemsByRepo: priorityResponses.map((response) => buildAttentionItems(response)),
          summaryResponses,
          activeTab,
        }),
      );
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
    });
  },

  closeDrawer: () => set({ selectedItem: null }),

  // --- Action handlers ---
  handleActionSelect: (actionUrl: string, label: string) => {
    set({ pendingAction: { actionUrl, label }, actionError: null });
  },

  handleConfirmAction: async () => {
    const { pendingAction, repoScope, repo, selectedItem } = get();
    if (!pendingAction) return;
    if (repoScope === 'single' && !repo) {
      set({ actionError: '请先选择仓库后再执行操作。' });
      return;
    }

    const action = pendingAction;
    const selectedDetail = selectedItem;
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
        actionNotice: `已提交操作：${action.label} · ${message}`,
        actionHistory: [newHistory, ...actionHistory].slice(0, 12),
        isActionSubmitting: false,
      });

      // Reload data
      if (repoScope === 'all') {
        await get().loadAllRepos();
      } else {
        await get().loadRepo(repo);
        if (selectedDetail?.type === 'epic') {
          await get().openEpicDetail(selectedDetail.number);
        } else if (selectedDetail?.type === 'story') {
          await get().openStoryDetail(selectedDetail.number);
        }
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
  setConfigPanel: (panel) => set((state) => ({ configPanel: state.configPanel === panel ? null : panel })),
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
  return filterWorkItems({
    workItems,
    taskSearchQuery,
    taskStatusFilter,
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
  return buildSummaryStats({
    repoSummary,
    workItems,
    attentionItems,
  });
}

export function useTopRepoAggregateStats() {
  const repoAggregateStats = useConsoleStore((s) => s.repoAggregateStats);
  return getTopRepoAggregateStats(repoAggregateStats);
}
