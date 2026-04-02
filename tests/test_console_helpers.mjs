import test from 'node:test';
import assert from 'node:assert/strict';

import {
  LOCALE_STORAGE_KEY,
  SIDEBAR_COLLAPSED_STORAGE_KEY,
  buildActionConfigFromDataset,
  buildDependencySummary,
  buildItemTitle,
  buildRecentRunSummary,
  buildRunningJobSummary,
  buildDistributionCounts,
  buildWorkspaceCurrentViewLabel,
  buildWorkspaceMenuA11yLabel,
  getActiveTaskTotals,
  getDecompositionTotals,
  getInitialLocaleFromStorage,
  getCompactToken,
  getRepoDisplayParts,
  getInitialSidebarCollapsedFromStorage,
  getRunningJobTotals,
  getSidebarTaskIdentity,
  getSidebarTaskMeta,
  getSidebarTreeViewState,
} from '../src/taskplane/static/console_helpers.mjs';

function makeStorage(values = {}) {
  return {
    getItem(key) {
      return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : null;
    },
  };
}

function makeT(map) {
  return (key, values = {}) => {
    const template = map[key] ?? key;
    return template.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ''));
  };
}

test('getInitialLocaleFromStorage defaults to zh and respects valid stored locales', () => {
  assert.equal(getInitialLocaleFromStorage(makeStorage()), 'zh');
  assert.equal(getInitialLocaleFromStorage(makeStorage({ [LOCALE_STORAGE_KEY]: 'zh' })), 'zh');
  assert.equal(getInitialLocaleFromStorage(makeStorage({ [LOCALE_STORAGE_KEY]: 'en' })), 'en');
  assert.equal(getInitialLocaleFromStorage(makeStorage({ [LOCALE_STORAGE_KEY]: 'fr' })), 'zh');
});

test('getInitialSidebarCollapsedFromStorage only returns true for string true', () => {
  assert.equal(getInitialSidebarCollapsedFromStorage(makeStorage()), false);
  assert.equal(getInitialSidebarCollapsedFromStorage(makeStorage({ [SIDEBAR_COLLAPSED_STORAGE_KEY]: 'false' })), false);
  assert.equal(getInitialSidebarCollapsedFromStorage(makeStorage({ [SIDEBAR_COLLAPSED_STORAGE_KEY]: 'true' })), true);
});

test('getSidebarTreeViewState distinguishes no-repo, idle, loading, empty, and ready', () => {
  const t = makeT({
    'sidebar.noEpicStories': 'no repo',
    'sidebar.epicStoriesNotLoaded': 'idle',
    'sidebar.loadingEpicStories': 'loading title',
    'sidebar.epicStoriesLoadingHint': 'loading hint',
    'sidebar.failedEpicStories': 'error',
    'sidebar.epicStoriesEmpty': 'empty',
  });
  assert.deepEqual(getSidebarTreeViewState({ currentRepo: '', sidebarTreeStatus: 'idle', treeGroupCount: 0, t }), { kind: 'no-repo', message: 'no repo' });
  assert.deepEqual(getSidebarTreeViewState({ currentRepo: 'repo', sidebarTreeStatus: 'idle', treeGroupCount: 0, t }), { kind: 'idle', message: 'idle' });
  assert.deepEqual(getSidebarTreeViewState({ currentRepo: 'repo', sidebarTreeStatus: 'loading', treeGroupCount: 0, t }), { kind: 'loading', title: 'loading title', hint: 'loading hint' });
  assert.deepEqual(getSidebarTreeViewState({ currentRepo: 'repo', sidebarTreeStatus: 'error', treeGroupCount: 0, t }), { kind: 'error', message: 'error' });
  assert.deepEqual(getSidebarTreeViewState({ currentRepo: 'repo', sidebarTreeStatus: 'loaded', treeGroupCount: 0, t }), { kind: 'empty', message: 'empty' });
  assert.deepEqual(getSidebarTreeViewState({ currentRepo: 'repo', sidebarTreeStatus: 'loaded', treeGroupCount: 2, t }), { kind: 'ready', message: null });
});

test('sidebar task helpers build identity and meta strings', () => {
  const t = makeT({
    'sidebar.taskIdentityFallback': 'task {id}',
    'sidebar.taskActiveQueueCue': 'in queue',
    'sidebar.taskDecisionCue': 'decision',
    'common.unknown': 'unknown',
  });
  const localizeStatus = (value) => ({ done: 'done', blocked: 'blocked', unknown: 'unknown' }[value] ?? value);

  assert.equal(getSidebarTaskIdentity({ source_issue_number: 44, title: 'Task title' }, t), '#44 Task title');
  assert.equal(getSidebarTaskIdentity({ work_id: 'issue-99' }, t), 'task issue-99');
  assert.equal(getSidebarTaskMeta({ status: 'blocked', in_active_queue: true, decision_required: true }, { localizeStatus, t }), 'blocked · in queue · decision');
});

test('buildActionConfigFromDataset maps dataset fields predictably', () => {
  assert.deepEqual(
    buildActionConfigFromDataset(
      {
        actionMethod: 'POST',
        actionUrl: '/api/foo',
        actionLabel: 'Retry task',
        actionTarget: 'Task issue-44',
        actionMode: 'repository retry reset',
        actionConfirmLabel: 'Confirm retry',
      },
      true,
    ),
    {
      method: 'POST',
      url: '/api/foo',
      label: 'Retry task',
      target: 'Task issue-44',
      mode: 'repository retry reset',
      confirmLabel: 'Confirm retry',
      tone: 'danger',
    },
  );
});

test('getCompactToken and getRepoDisplayParts build stable compact identities', () => {
  const t = makeT({ 'common.unknown': 'unknown' });
  assert.equal(getCompactToken('Epic Queue'), 'EQ');
  assert.equal(getCompactToken('stardrifter'), 'ST');
  assert.equal(getCompactToken('故事'), '故');
  assert.deepEqual(getRepoDisplayParts('codefromkarl/stardrifter', t), { badge: 'ST', shortLabel: 'stardrifter' });
  assert.deepEqual(getRepoDisplayParts('', t), { badge: 'RP', shortLabel: 'unknown' });
});

test('workspace menu helpers build current-view and aria labels', () => {
  const t = makeT({
    'sidebar.currentViewLabel': 'Current view',
    'sidebar.views.epics.title': 'Epic queue',
  });
  assert.equal(buildWorkspaceCurrentViewLabel({ title: 'Running jobs' }, t), 'Current view: Running jobs');
  assert.equal(buildWorkspaceCurrentViewLabel(null, t), 'Current view: Epic queue');
  assert.equal(buildWorkspaceMenuA11yLabel({ title: 'Running jobs', meta: 'Live decomposition and orchestration jobs.', count: 4 }), 'Running jobs. Live decomposition and orchestration jobs.. 4');
});

test('workspace aggregate helpers compute governance/decomposition/task/job totals', () => {
  const rows = [
    {
      program_status: 'approved',
      execution_status: 'active',
      execution_state_status: 'active',
      queued_story_decomposition_count: 2,
      queued_for_epic_decomposition: true,
      remaining_story_count: 3,
      ready_task_count: 1,
      in_progress_task_count: 2,
      blocked_task_count: 0,
      decision_required_task_count: 1,
      active_queue_task_count: 3,
      running_job_count: 2,
    },
    {
      program_status: 'archived',
      execution_status: 'backlog',
      execution_state_status: null,
      queued_story_decomposition_count: 0,
      queued_for_epic_decomposition: false,
      remaining_story_count: 0,
      ready_task_count: 2,
      in_progress_task_count: 0,
      blocked_task_count: 1,
      decision_required_task_count: 0,
      active_queue_task_count: 2,
      running_job_count: 0,
    },
  ];

  assert.deepEqual(buildDistributionCounts(rows, 'program_status'), { approved: 1, archived: 1 });
  assert.deepEqual(buildDistributionCounts(rows, 'execution_status'), { active: 1, backlog: 1 });
  assert.deepEqual(buildDistributionCounts(rows.filter((row) => row.execution_state_status), 'execution_state_status'), { active: 1 });

  assert.deepEqual(getDecompositionTotals(rows), {
    filtered: [rows[0]],
    queuedStories: 2,
    queuedEpics: 1,
    remainingStories: 3,
  });

  assert.deepEqual(getActiveTaskTotals(rows), {
    ready: 3,
    inProgress: 2,
    blocked: 1,
    decision: 1,
    activeQueue: 5,
  });

  assert.deepEqual(getRunningJobTotals(rows), {
    filtered: [rows[0]],
    total: 2,
  });
});

test('detail helper functions build stable titles and summary strings', () => {
  const t = makeT({
    'common.emDash': '—',
    'common.unknown': 'unknown',
    'detail.overview.jobFallback': 'job',
    'detail.overview.workerFallback': 'worker',
    'detail.execution.exit': 'exit {code}',
  });
  const localizeDirection = (value) => ({ blocked_by: 'blocked by' }[value] ?? value);
  const localizeStatus = (value) => ({ active: 'active', done: 'done', unknown: 'unknown' }[value] ?? value);

  assert.equal(buildItemTitle((values) => `Task ${values.id}`, { id: 'issue-44' }), 'Task issue-44');
  assert.equal(
    buildDependencySummary(
      { direction: 'blocked_by', epic_issue_number: 13, title: 'Campaign Topology', execution_status: 'active' },
      { localizeDirection, localizeStatus, t },
    ),
    'blocked by · #13 · Campaign Topology · active',
  );
  assert.equal(
    buildRunningJobSummary(
      { id: 7, job_kind: 'story_decomposition', worker_name: 'console-story-21', started_at: '2026-03-25T10:00:00+00:00' },
      { t },
    ),
    '#7 · story_decomposition · console-story-21 · 2026-03-25T10:00:00+00:00',
  );
  assert.equal(
    buildRecentRunSummary(
      { id: 4, status: 'done', exit_code: 0, started_at: '2026-03-25T09:00:00+00:00' },
      { localizeStatus, t },
    ),
    '#4 · done · exit 0 · 2026-03-25T09:00:00+00:00',
  );
});
