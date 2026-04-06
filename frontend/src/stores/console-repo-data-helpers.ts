import type {
  IntentsResponse,
  RepoSummaryResponse,
  RuntimeObservabilityResponse,
  SystemStatusResponse,
  WorkItemsResponse,
} from '../api';
import type {
  AttentionItem,
  ConsoleTabId,
  RuntimeObservationItem,
} from '../types';
import {
  mapWorkItemToDisplay,
  type LoadedConsoleData,
} from '../utils/console-view-models';
import { mapIntentToDisplay } from './console-intake-slice';
import {
  buildRepoAggregateStats,
  type RepoAggregateStats,
} from './console-selectors';

export function resolveRepoInitialization(args: {
  currentRepo: string;
  repoScope: 'single' | 'all';
  repositoryRepos: string[];
  systemStatus: SystemStatusResponse | null;
  defaultRepo: string;
}): {
  repoOptions: string[];
  initialRepo: string;
} {
  const { currentRepo, repositoryRepos, systemStatus, defaultRepo } = args;
  const configuredRepos = systemStatus?.configured_repos
    .map((item) => item.repo)
    .filter(Boolean) ?? [];
  const repoOptions = Array.from(
    new Set([...repositoryRepos.filter(Boolean), ...configuredRepos]),
  );
  const preferredRepo =
    currentRepo && repoOptions.includes(currentRepo) ? currentRepo : '';
  const initialRepo =
    preferredRepo
    || (repoOptions.includes(defaultRepo) ? defaultRepo : repoOptions[0] || '');

  return {
    repoOptions,
    initialRepo,
  };
}

export function buildRuntimeObservations(
  items: RuntimeObservabilityResponse['items'],
): RuntimeObservationItem[] {
  return items.map((item) => ({
    workId: item.work_id,
    issueNumber: item.source_issue_number,
    title: item.title || item.work_id,
    status: item.status as RuntimeObservationItem['status'],
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
    artifactSummary:
      typeof item.artifact_metadata?.summary === 'string'
        ? item.artifact_metadata.summary
        : undefined,
    artifactCreatedAt: item.artifact_created_at,
  }));
}

export function buildSingleRepoPatch(args: {
  loadedData: LoadedConsoleData;
  intents: IntentsResponse['items'];
  runtimeObservationItems: RuntimeObservabilityResponse['items'];
  systemStatus: SystemStatusResponse | null;
}) {
  const { loadedData, intents, runtimeObservationItems, systemStatus } = args;

  return {
    workItems: loadedData.workItems,
    intents: intents.map(mapIntentToDisplay),
    epicRows: loadedData.epicRows,
    epicTreeRows: loadedData.epicTreeRows,
    runningJobs: loadedData.runningJobs,
    runtimeObservations: buildRuntimeObservations(runtimeObservationItems),
    notifications: loadedData.notifications,
    failedNotifications: loadedData.failedNotifications,
    agents: loadedData.agents,
    agentStats: loadedData.agentStats,
    repoSummary: loadedData.repoSummary,
    systemStatus,
    attentionItems: loadedData.attentionItems,
    repoAggregateStats: [] as RepoAggregateStats[],
    selectedItem: null,
    selectedIntentId: null,
    loading: false,
  };
}

export function buildAllReposPatch(args: {
  repos: string[];
  workItemResponses: WorkItemsResponse[];
  attentionItemsByRepo: AttentionItem[][];
  summaryResponses: Array<RepoSummaryResponse | null>;
  activeTab: ConsoleTabId;
}) {
  const {
    repos,
    workItemResponses,
    attentionItemsByRepo,
    summaryResponses,
    activeTab,
  } = args;

  const mergedWorkItems = workItemResponses.flatMap((response, index) => {
    const repoName = repos[index];
    return response.items.map((item) => mapWorkItemToDisplay(item, repoName));
  });

  const mergedAttention = attentionItemsByRepo
    .flatMap((items, index) => {
      const repoName = repos[index];
      return items.map((item) => ({
        ...item,
        id: `${repoName}:${item.id}`,
        title: `[${repoName}] ${item.title}`,
      }));
    })
    .sort((left, right) => right.priorityScore - left.priorityScore)
    .slice(0, 120);

  const repoAggregateStats = repos.map((repoName, index) => {
    const scopedItems = mergedWorkItems.filter((item) => item.repo === repoName);
    const attentionCount = mergedAttention.filter((item) =>
      item.title.startsWith(`[${repoName}]`),
    ).length;
    const summary = summaryResponses[index];
    if (summary) {
      return {
        repo: repoName,
        totalTasks:
          summary.total_tasks ?? summary.summary?.total_tasks ?? scopedItems.length,
        activeTasks:
          summary.active_tasks
          ?? summary.summary?.active_tasks
          ?? scopedItems.filter((item) => item.status !== 'done').length,
        blockedTasks:
          summary.blocked_tasks
          ?? summary.summary?.blocked_tasks
          ?? scopedItems.filter((item) => item.status === 'blocked').length,
        completedTasks:
          summary.completed_tasks
          ?? summary.summary?.completed_tasks
          ?? scopedItems.filter((item) => item.status === 'done').length,
        attentionCount,
      } satisfies RepoAggregateStats;
    }
    return buildRepoAggregateStats(repoName, scopedItems, attentionCount);
  });

  const completedTasks = repoAggregateStats.reduce(
    (sum, item) => sum + item.completedTasks,
    0,
  );
  const blockedTasks = repoAggregateStats.reduce(
    (sum, item) => sum + item.blockedTasks,
    0,
  );
  const activeTasks = repoAggregateStats.reduce(
    (sum, item) => sum + item.activeTasks,
    0,
  );

  return {
    workItems: mergedWorkItems,
    attentionItems: mergedAttention,
    repoAggregateStats,
    epicRows: [],
    epicTreeRows: [],
    runningJobs: [],
    runtimeObservations: [],
    notifications: [],
    failedNotifications: [],
    agents: [],
    agentStats: [],
    intents: [],
    selectedItem: null,
    repoSummary: {
      repo: 'all',
      totalEpics: 0,
      totalStories: 0,
      totalTasks: mergedWorkItems.length,
      activeTasks,
      completedTasks,
      blockedTasks,
    },
    activeTab: activeTab === 'kanban' ? 'repository' : activeTab,
    loading: false,
  };
}
