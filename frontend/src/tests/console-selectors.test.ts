import { describe, expect, it } from 'vitest';

import type { RepoSummary, WorkItem } from '../types';
import {
  buildSummaryStats,
  filterWorkItems,
  rankTopRepoAggregateStats,
} from '../stores/console-selectors';

describe('console selectors', () => {
  it('filters work items by status and keyword across title, number, and repo', () => {
    const items: WorkItem[] = [
      {
        id: 'task-1',
        repo: 'demo/api',
        number: 101,
        title: 'Implement auth API',
        type: 'task',
        status: 'ready',
      },
      {
        id: 'task-2',
        repo: 'demo/web',
        number: 202,
        title: 'Build sign-in form',
        type: 'task',
        status: 'blocked',
      },
    ];

    expect(
      filterWorkItems({
        workItems: items,
        taskSearchQuery: 'demo/api',
        taskStatusFilter: 'ready',
      }),
    ).toEqual([items[0]]);

    expect(
      filterWorkItems({
        workItems: items,
        taskSearchQuery: '202',
        taskStatusFilter: 'all',
      }),
    ).toEqual([items[1]]);
  });

  it('prefers repo summary when building summary stats and falls back to items plus attention count', () => {
    const repoSummary: RepoSummary = {
      repo: 'demo/api',
      totalEpics: 3,
      totalStories: 6,
      totalTasks: 18,
      activeTasks: 7,
      completedTasks: 11,
      blockedTasks: 2,
    };

    expect(
      buildSummaryStats({
        repoSummary,
        workItems: [],
        attentionItems: [],
      }),
    ).toEqual([
      { label: '史诗', value: 3 },
      { label: '故事', value: 6 },
      { label: '任务', value: 18 },
      { label: '活跃', value: 7 },
      { label: '阻塞', value: 2 },
    ]);

    expect(
      buildSummaryStats({
        repoSummary: null,
        workItems: [
          {
            number: 1,
            title: 'one',
            type: 'task',
            status: 'ready',
          },
          {
            number: 2,
            title: 'two',
            type: 'task',
            status: 'blocked',
          },
        ],
        attentionItems: [
          {
            id: 'a1',
            issueNumber: 7,
            title: 'needs review',
            priorityScore: 90,
            reason: 'blocked',
          },
        ],
      }),
    ).toEqual([
      { label: '任务', value: 2 },
      { label: '关注项', value: 1 },
    ]);
  });

  it('ranks repo aggregate stats by blocked tasks, attention, and active work', () => {
    expect(
      rankTopRepoAggregateStats([
        {
          repo: 'demo/low',
          totalTasks: 4,
          activeTasks: 2,
          blockedTasks: 0,
          completedTasks: 2,
          attentionCount: 0,
        },
        {
          repo: 'demo/high',
          totalTasks: 10,
          activeTasks: 4,
          blockedTasks: 2,
          completedTasks: 6,
          attentionCount: 1,
        },
        {
          repo: 'demo/mid',
          totalTasks: 8,
          activeTasks: 5,
          blockedTasks: 1,
          completedTasks: 3,
          attentionCount: 2,
        },
      ]),
    ).toEqual(['demo/high', 'demo/mid', 'demo/low']);
  });
});
