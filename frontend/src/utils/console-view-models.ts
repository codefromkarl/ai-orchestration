import {
  AgentEfficiencyStat,
  AgentStatusItem,
  AttentionItem,
  EpicOverviewRow,
  EpicStoryTreeRow,
  NotificationItem,
  RepoSummary,
  RunningJobSummary,
  WorkItem,
} from '../types';
import {
  AgentStatsResponse,
  AgentsResponse,
  EpicRowsResponse,
  EpicDetailResponse,
  EpicStoryTreeResponse,
  GovernancePriorityResponse,
  JobDetailResponse,
  NotificationsResponse,
  RepoSummaryResponse,
  RunningJobsResponse,
  StoryDetailResponse,
  TaskDetailResponse,
  WorkItemsResponse,
} from '../api';

export function mapWorkItemToDisplay(item: {
  id: string;
  source_issue_number: number;
  title: string;
  status: string;
  canonical_story_issue_number?: number;
  blocked_reason?: string;
}, repo?: string): WorkItem {
  return {
    id: item.id,
    repo,
    number: item.source_issue_number,
    title: item.title,
    type: 'task',
    status: item.status as WorkItem['status'],
    storyNumber: item.canonical_story_issue_number,
    blockedReason: item.blocked_reason,
  };
}

export function mapEpicStoryTreeRows(response: EpicStoryTreeResponse): EpicStoryTreeRow[] {
  return response.rows.map((epic) => ({
    epic_issue_number: epic.epic_issue_number,
    title: epic.title,
    story_summaries: epic.story_summaries?.map((story) => ({
      ...story,
      task_summaries: story.task_summaries?.map((task) => ({
        ...task,
        status: task.status as WorkItem['status'] | undefined,
      })),
    })),
  }));
}

export function buildRepoSummary(
  repoName: string,
  summaryResponse: RepoSummaryResponse | null,
  workItemsResponse: WorkItemsResponse,
): RepoSummary {
  const summary = summaryResponse?.summary ?? summaryResponse;

  if (summaryResponse) {
    return {
      repo: summaryResponse.repo,
      totalEpics: summary?.total_epics ?? 0,
      totalStories: summary?.total_stories ?? 0,
      totalTasks: summary?.total_tasks ?? 0,
      activeTasks: summary?.active_tasks ?? 0,
      completedTasks: summary?.completed_tasks ?? 0,
      blockedTasks: summary?.blocked_tasks ?? 0,
      snapshotHealth: summaryResponse.snapshot_health,
    };
  }

  return {
    repo: repoName,
    totalEpics: 0,
    totalStories: 0,
    totalTasks: workItemsResponse.count,
    activeTasks: workItemsResponse.items.filter((item) => item.status !== 'done').length,
    completedTasks: workItemsResponse.items.filter((item) => item.status === 'done').length,
    blockedTasks: workItemsResponse.items.filter((item) => item.status === 'blocked').length,
    snapshotHealth: undefined,
  };
}

export function buildAttentionItems(priorityResponse: GovernancePriorityResponse): AttentionItem[] {
  return priorityResponse.tasks.slice(0, 10).map((task, index) => ({
    id: `attention-${index}`,
    issueNumber: task.source_issue_number || task.story_issue_number || task.epic_issue_number || 0,
    title: task.title || task.story_title || task.epic_title || '',
    priorityScore: parseInt(task.priority_score || '0', 10) || 0,
    reason: task.kind || '',
  }));
}

export interface LoadedConsoleData {
  workItems: WorkItem[];
  epicRows: EpicOverviewRow[];
  epicTreeRows: EpicStoryTreeRow[];
  runningJobs: RunningJobSummary[];
  notifications: NotificationItem[];
  failedNotifications: NotificationItem[];
  agents: AgentStatusItem[];
  agentStats: AgentEfficiencyStat[];
  repoSummary: RepoSummary;
  attentionItems: AttentionItem[];
}

export function buildLoadedConsoleData(args: {
  repoName: string;
  workItemsResponse: WorkItemsResponse;
  epicRowsResponse: EpicRowsResponse;
  epicStoryTreeResponse: EpicStoryTreeResponse;
  runningJobsResponse: RunningJobsResponse;
  notificationsResponse: NotificationsResponse;
  failedNotificationsResponse: NotificationsResponse;
  agentsResponse: AgentsResponse;
  agentStatsResponse: AgentStatsResponse;
  summaryResponse: RepoSummaryResponse | null;
  priorityResponse: GovernancePriorityResponse;
}): LoadedConsoleData {
  const {
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
  } = args;

  return {
    workItems: workItemsResponse.items.map((item) => mapWorkItemToDisplay(item, repoName)),
    epicRows: epicRowsResponse.rows,
    epicTreeRows: mapEpicStoryTreeRows(epicStoryTreeResponse),
    runningJobs: runningJobsResponse.jobs,
    notifications: notificationsResponse.notifications,
    failedNotifications: failedNotificationsResponse.notifications,
    agents: agentsResponse.agents,
    agentStats: agentStatsResponse.stats,
    repoSummary: buildRepoSummary(repoName, summaryResponse, workItemsResponse),
    attentionItems: buildAttentionItems(priorityResponse),
  };
}

export function buildEpicDrawerItem(args: {
  detail: EpicDetailResponse;
  matchingRow?: EpicOverviewRow;
}): import('../types').DrawerDetailItem {
  const { detail, matchingRow } = args;
  const metaParts = [
    matchingRow?.verification_summary,
    matchingRow?.verification_status === 'failed' ? 'verify failed' : undefined,
    detail.epic.execution_status,
    detail.execution_state.status,
    detail.epic.lane,
    detail.stories.length ? `${detail.stories.length} stories` : undefined,
    detail.active_tasks.length ? `${detail.active_tasks.length} active tasks` : undefined,
  ].filter((value, index, array) => Boolean(value) && array.indexOf(value) === index) as string[];

  return {
    kind: 'epic',
    number: detail.epic.issue_number,
    title: detail.epic.title,
    type: 'epic',
    lane: detail.epic.lane,
    wave: detail.epic.active_wave,
    metaSummary: metaParts.join(' · '),
    storySummaries: detail.stories,
    actionButtons: [
      {
        label: 'Split epic',
        actionUrl: `/api/repos/${encodeURIComponent(detail.repo)}/epics/${detail.epic.issue_number}/split`,
      },
    ],
  };
}

export function buildJobDrawerItem(detail: JobDetailResponse): import('../types').DrawerDetailItem {
  const metaParts = [
    detail.job.worker_name,
    detail.job.command,
    detail.story?.story_title,
    detail.task?.title,
  ].filter(Boolean) as string[];

  return {
    kind: 'job',
    number: detail.job.id,
    title: detail.job.job_kind || 'Job',
    type: 'task',
    metaSummary: metaParts.join(' · '),
  };
}

export function buildStoryDrawerItem(args: {
  detail: StoryDetailResponse;
  repo: string;
  storyIssueNumber: number;
}): import('../types').DrawerDetailItem {
  const { detail, repo, storyIssueNumber } = args;

  return {
    kind: 'epic',
    number: detail.story.story_issue_number,
    title: detail.story.title,
    type: 'story',
    lane: detail.story.lane,
    wave: detail.story.active_wave,
    metaSummary: [
      detail.story.verification_summary,
      detail.story.verification_status === 'failed' ? 'verify failed' : undefined,
      detail.story.execution_status,
      detail.tasks.length ? `${detail.tasks.length} tasks` : undefined,
    ].filter(Boolean).join(' · '),
    taskSummaries: detail.tasks.map((task) => ({
      workId: task.work_id,
      issueNumber: task.source_issue_number,
      title: task.title,
      status: task.status as WorkItem['status'] | undefined,
    })),
    actionButtons: [
      {
        label: 'Split story',
        actionUrl: `/api/repos/${encodeURIComponent(repo)}/stories/${storyIssueNumber}/split`,
      },
    ],
  };
}

export function buildTaskDrawerItem(args: {
  detail: TaskDetailResponse;
  repo: string;
  workId: string;
}): import('../types').DrawerDetailItem {
  const { detail, repo, workId } = args;

  return {
    kind: 'task',
    number: detail.task.source_issue_number ?? 0,
    title: `${workId} ${detail.task.source_issue_title || detail.task.title || ''}`.trim(),
    type: 'task',
    status: detail.task.status as WorkItem['status'] | undefined,
    lane: detail.task.lane,
    wave: detail.task.wave,
    complexity: detail.task.complexity,
    blockedReason: detail.task.blocked_reason || detail.retry_context.latest_failure_reason_code,
    decisionRequired: detail.task.decision_required,
    epicNumber: detail.task.epic_issue_number,
    storyNumber: detail.task.story_issue_number,
    metaSummary: [
      workId,
      detail.active_claim.worker_name,
      detail.retry_context.latest_failure_reason_code,
    ].filter(Boolean).join(' · '),
    snapshotState: detail.snapshot_state,
    actionButtons: [
      {
        label: 'Retry task',
        actionUrl: `/api/repos/${encodeURIComponent(repo)}/tasks/${encodeURIComponent(workId)}/retry`,
        tone: 'danger',
      },
    ],
  };
}
