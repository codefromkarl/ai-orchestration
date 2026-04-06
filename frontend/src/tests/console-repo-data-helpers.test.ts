import { describe, expect, it } from 'vitest';

import type {
  RepoSummaryResponse,
  SystemStatusResponse,
  WorkItemsResponse,
} from '../api';
import type { AttentionItem } from '../types';
import {
  buildAllReposPatch,
  buildSingleRepoPatch,
  buildRuntimeObservations,
  resolveRepoInitialization,
} from '../stores/console-repo-data-helpers';

describe('console repo data helpers', () => {
  it('merges configured and discovered repos, then prefers current repo when available', () => {
    const systemStatus: SystemStatusResponse = {
      config_source: 'taskplane.toml',
      postgres_dsn_configured: true,
      database_connected: true,
      configured_repos: [
        {
          repo: 'demo/configured',
          workdir: '/tmp/configured',
          log_dir: '/tmp/logs',
          workdir_exists: true,
          log_dir_exists: true,
        },
      ],
      discovered_repositories: ['demo/discovered'],
      commands: {},
      dev_compose_file: 'ops/docker-compose.yml',
      dev_env_file: '.env',
      recommended_actions: [],
    };

    expect(
      resolveRepoInitialization({
        currentRepo: 'demo/configured',
        repoScope: 'single',
        repositoryRepos: ['demo/discovered', 'demo/configured'],
        systemStatus,
        defaultRepo: 'demo/default',
      }),
    ).toEqual({
      repoOptions: ['demo/discovered', 'demo/configured'],
      initialRepo: 'demo/configured',
    });
  });

  it('maps runtime observation rows into UI-friendly objects', () => {
    expect(
      buildRuntimeObservations([
        {
          work_id: 'task-1',
          source_issue_number: 12,
          title: '',
          status: 'in_progress',
          lane: 'Lane 01',
          wave: 'wave-1',
          blocked_reason: null,
          decision_required: true,
          last_failure_reason: 'flake',
          active_claim_worker_name: 'worker-a',
          session_id: 'session-1',
          session_status: 'waiting',
          session_attempt_index: 2,
          session_current_phase: 'implementing',
          session_waiting_reason: 'awaiting-review',
          session_updated_at: '2026-04-06T08:00:00Z',
          last_checkpoint_summary: 'checkpointed',
          last_checkpoint_next_action: 'resume after review',
          artifact_id: 9,
          artifact_type: 'stdout',
          artifact_key: 'artifact/stdout/1',
          artifact_metadata: { summary: 'captured logs' },
          artifact_created_at: '2026-04-06T08:00:05Z',
        },
      ]),
    ).toEqual([
      {
        workId: 'task-1',
        issueNumber: 12,
        title: 'task-1',
        status: 'in_progress',
        lane: 'Lane 01',
        wave: 'wave-1',
        blockedReason: null,
        decisionRequired: true,
        lastFailureReason: 'flake',
        workerName: 'worker-a',
        sessionId: 'session-1',
        sessionStatus: 'waiting',
        sessionAttemptIndex: 2,
        sessionCurrentPhase: 'implementing',
        sessionWaitingReason: 'awaiting-review',
        sessionUpdatedAt: '2026-04-06T08:00:00Z',
        checkpointSummary: 'checkpointed',
        checkpointNextAction: 'resume after review',
        artifactId: 9,
        artifactType: 'stdout',
        artifactKey: 'artifact/stdout/1',
        artifactSummary: 'captured logs',
        artifactCreatedAt: '2026-04-06T08:00:05Z',
      },
    ]);
  });

  it('builds single-repo patch with mapped intents and runtime observations', () => {
    const patch = buildSingleRepoPatch({
      loadedData: {
        workItems: [
          {
            id: 'task-1',
            repo: 'demo/api',
            number: 11,
            title: 'Implement auth API',
            type: 'task',
            status: 'ready',
          },
        ],
        epicRows: [],
        epicTreeRows: [],
        runningJobs: [],
        notifications: [],
        failedNotifications: [],
        agents: [],
        agentStats: [],
        repoSummary: {
          repo: 'demo/api',
          totalEpics: 1,
          totalStories: 2,
          totalTasks: 3,
          activeTasks: 2,
          completedTasks: 1,
          blockedTasks: 0,
        },
        attentionItems: [],
      },
      intents: [
        {
          id: 'intent-1',
          repo: 'demo/api',
          prompt: '实现认证系统',
          status: 'awaiting_review',
          summary: '拆解完成',
          clarification_questions_json: ['是否只支持 Web？'],
          proposal_json: {
            epic: { title: 'Auth' },
            stories: [],
          },
          promoted_epic_issue_number: null,
          approved_by: null,
          reviewed_at: null,
          reviewed_by: null,
          review_action: null,
          review_feedback: null,
        },
      ],
      runtimeObservationItems: [
        {
          work_id: 'task-1',
          source_issue_number: 11,
          title: 'Implement auth API',
          status: 'ready',
          lane: 'Lane 01',
          wave: 'wave-1',
          blocked_reason: null,
          decision_required: false,
          last_failure_reason: null,
          active_claim_worker_name: null,
          session_id: null,
          session_status: null,
          session_attempt_index: null,
          session_current_phase: null,
          session_waiting_reason: null,
          session_updated_at: null,
          last_checkpoint_summary: null,
          last_checkpoint_next_action: null,
          artifact_id: null,
          artifact_type: null,
          artifact_key: null,
          artifact_metadata: {},
          artifact_created_at: null,
        },
      ],
      systemStatus: null,
    });

    expect(patch).toMatchObject({
      workItems: [
        {
          id: 'task-1',
          title: 'Implement auth API',
        },
      ],
      intents: [
        {
          id: 'intent-1',
          questions: ['是否只支持 Web？'],
        },
      ],
      runtimeObservations: [
        {
          workId: 'task-1',
          title: 'Implement auth API',
        },
      ],
      repoSummary: {
        repo: 'demo/api',
        totalTasks: 3,
      },
      selectedIntentId: null,
      repoAggregateStats: [],
      loading: false,
    });
  });

  it('builds all-repo patch with aggregate stats and summary totals', () => {
    const workItemResponses: WorkItemsResponse[] = [
      {
        repo: 'demo/api',
        items: [
          {
            id: 'task-1',
            source_issue_number: 11,
            title: 'Implement auth API',
            status: 'ready',
            canonical_story_issue_number: 101,
            task_type: 'core_path',
          },
        ],
        count: 1,
      },
      {
        repo: 'demo/web',
        items: [
          {
            id: 'task-2',
            source_issue_number: 22,
            title: 'Build login form',
            status: 'blocked',
            canonical_story_issue_number: 202,
            blocked_reason: 'waiting backend',
            task_type: 'core_path',
          },
        ],
        count: 1,
      },
    ];
    const attentionItemsByRepo: AttentionItem[][] = [
      [
        {
          id: 'p1',
          issueNumber: 11,
          title: 'API priority',
          priorityScore: 85,
          reason: 'critical path',
        },
      ],
      [
        {
          id: 'p2',
          issueNumber: 22,
          title: 'Web blocked',
          priorityScore: 90,
          reason: 'blocked',
        },
      ],
    ];
    const summaryResponses: Array<RepoSummaryResponse | null> = [
      {
        repo: 'demo/api',
        total_tasks: 4,
        active_tasks: 3,
        completed_tasks: 1,
        blocked_tasks: 0,
      },
      null,
    ];

    const patch = buildAllReposPatch({
      repos: ['demo/api', 'demo/web'],
      workItemResponses,
      attentionItemsByRepo,
      summaryResponses,
      activeTab: 'kanban',
    });

    expect(patch.activeTab).toBe('repository');
    expect(patch.repoSummary).toEqual({
      repo: 'all',
      totalEpics: 0,
      totalStories: 0,
      totalTasks: 2,
      activeTasks: 4,
      completedTasks: 1,
      blockedTasks: 1,
    });
    expect(patch.repoAggregateStats).toEqual([
      {
        repo: 'demo/api',
        totalTasks: 4,
        activeTasks: 3,
        blockedTasks: 0,
        completedTasks: 1,
        attentionCount: 1,
      },
      {
        repo: 'demo/web',
        totalTasks: 1,
        activeTasks: 1,
        blockedTasks: 1,
        completedTasks: 0,
        attentionCount: 1,
      },
    ]);
    expect(patch.attentionItems.map((item) => item.title)).toEqual([
      '[demo/web] Web blocked',
      '[demo/api] API priority',
    ]);
  });
});
