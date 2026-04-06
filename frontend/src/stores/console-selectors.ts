import type { AttentionItem, RepoSummary, TaskStatus, WorkItem } from '../types';

export interface RepoAggregateStats {
  repo: string;
  totalTasks: number;
  activeTasks: number;
  blockedTasks: number;
  completedTasks: number;
  attentionCount: number;
}

export function buildRepoAggregateStats(
  repo: string,
  items: WorkItem[],
  attentionCount: number,
): RepoAggregateStats {
  const completedTasks = items.filter((item) => item.status === 'done').length;
  const blockedTasks = items.filter((item) => item.status === 'blocked').length;
  const activeTasks = items.length - completedTasks;
  return { repo, totalTasks: items.length, activeTasks, blockedTasks, completedTasks, attentionCount };
}

export function filterWorkItems(args: {
  workItems: WorkItem[];
  taskSearchQuery: string;
  taskStatusFilter: TaskStatus | 'all';
}): WorkItem[] {
  const { workItems, taskSearchQuery, taskStatusFilter } = args;
  const keyword = taskSearchQuery.trim().toLowerCase();

  return workItems.filter((item) => {
    const matchesStatus = taskStatusFilter === 'all' || item.status === taskStatusFilter;
    if (!matchesStatus) {
      return false;
    }
    if (!keyword) {
      return true;
    }

    return (
      item.title.toLowerCase().includes(keyword)
      || String(item.number).includes(keyword)
      || (item.repo ? item.repo.toLowerCase().includes(keyword) : false)
    );
  });
}

export function buildSummaryStats(args: {
  repoSummary: RepoSummary | null;
  workItems: WorkItem[];
  attentionItems: AttentionItem[];
}): Array<{ label: string; value: number }> {
  const { repoSummary, workItems, attentionItems } = args;
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

function scoreRepoAggregate(item: RepoAggregateStats): number {
  return item.blockedTasks * 3 + item.attentionCount * 2 + item.activeTasks;
}

export function getTopRepoAggregateStats(
  repoAggregateStats: RepoAggregateStats[],
): RepoAggregateStats[] {
  return [...repoAggregateStats]
    .sort((left, right) => scoreRepoAggregate(right) - scoreRepoAggregate(left))
    .slice(0, 8);
}

export function rankTopRepoAggregateStats(
  repoAggregateStats: RepoAggregateStats[],
): string[] {
  return getTopRepoAggregateStats(repoAggregateStats).map((item) => item.repo);
}
