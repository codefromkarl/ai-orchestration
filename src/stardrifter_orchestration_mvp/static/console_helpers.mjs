// Legacy internal helper module retained for direct utility tests and historical
// reference only. The React-backed /console runtime no longer imports this file
// over HTTP, and new frontend logic should prefer typed utilities under
// frontend/src/utils/.

export const LOCALE_STORAGE_KEY = 'stardrifter-console-locale';
export const SIDEBAR_COLLAPSED_STORAGE_KEY = 'stardrifter-console-sidebar-collapsed';

export function getInitialLocaleFromStorage(storageLike) {
  const stored = storageLike && typeof storageLike.getItem === 'function'
    ? storageLike.getItem(LOCALE_STORAGE_KEY)
    : null;
  return stored === 'zh' || stored === 'en' ? stored : 'zh';
}

export function getInitialSidebarCollapsedFromStorage(storageLike) {
  const stored = storageLike && typeof storageLike.getItem === 'function'
    ? storageLike.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)
    : null;
  return stored === 'true';
}

export function getSidebarTreeViewState({ currentRepo, sidebarTreeStatus, treeGroupCount, t }) {
  if (!currentRepo) {
    return { kind: 'no-repo', message: t('sidebar.noEpicStories') };
  }
  if (sidebarTreeStatus === 'idle') {
    return { kind: 'idle', message: t('sidebar.epicStoriesNotLoaded') };
  }
  if (sidebarTreeStatus === 'loading') {
    return {
      kind: 'loading',
      title: t('sidebar.loadingEpicStories'),
      hint: t('sidebar.epicStoriesLoadingHint'),
    };
  }
  if (sidebarTreeStatus === 'error') {
    return { kind: 'error', message: t('sidebar.failedEpicStories') };
  }
  if (!treeGroupCount) {
    return { kind: 'empty', message: t('sidebar.epicStoriesEmpty') };
  }
  return { kind: 'ready', message: null };
}

export function getSidebarTaskIdentity(task, t) {
  if (task && task.source_issue_number) {
    const suffix = task.title ? ` ${task.title}` : '';
    return `#${task.source_issue_number}${suffix}`;
  }
  return t('sidebar.taskIdentityFallback', { id: task && task.work_id ? task.work_id : t('common.unknown') });
}

export function getSidebarTaskMeta(task, { localizeStatus, t }) {
  const parts = [localizeStatus(task && task.status ? task.status : t('common.unknown'))];
  if (task && task.in_active_queue) {
    parts.push(t('sidebar.taskActiveQueueCue'));
  }
  if (task && task.decision_required) {
    parts.push(t('sidebar.taskDecisionCue'));
  }
  return parts.join(' · ');
}

export function buildActionConfigFromDataset(dataset, isDanger) {
  return {
    method: dataset.actionMethod,
    url: dataset.actionUrl,
    label: dataset.actionLabel,
    target: dataset.actionTarget,
    mode: dataset.actionMode,
    confirmLabel: dataset.actionConfirmLabel || dataset.actionLabel,
    tone: isDanger ? 'danger' : 'primary',
  };
}

export function getCompactToken(label) {
  const normalized = String(label || '').trim();
  if (!normalized) {
    return '•';
  }
  const tokens = normalized.match(/[A-Za-z0-9]+|[^\s]/g) || [];
  if (tokens.length >= 2 && /^[A-Za-z0-9]+$/.test(tokens[0]) && /^[A-Za-z0-9]+$/.test(tokens[1])) {
    return `${tokens[0][0] || ''}${tokens[1][0] || ''}`.toUpperCase();
  }
  const firstToken = tokens[0] || normalized;
  if (/^[A-Za-z0-9]+$/.test(firstToken)) {
    return firstToken.slice(0, 2).toUpperCase();
  }
  return Array.from(firstToken).slice(0, 2).join('');
}

export function getRepoDisplayParts(repo, t) {
  const safeRepo = String(repo || '').trim();
  if (!safeRepo) {
    return { badge: 'RP', shortLabel: t('common.unknown') };
  }
  const parts = safeRepo.split('/').filter(Boolean);
  const shortLabel = parts[parts.length - 1] || safeRepo;
  return {
    badge: getCompactToken(shortLabel),
    shortLabel,
  };
}

export function buildWorkspaceCurrentViewLabel(activeItem, t) {
  return `${t('sidebar.currentViewLabel')}: ${activeItem ? activeItem.title : t('sidebar.views.epics.title')}`;
}

export function buildWorkspaceMenuA11yLabel(item) {
  return `${item.title}. ${item.meta}. ${item.count || 0}`;
}

export function buildDistributionCounts(rows, field) {
  return rows.reduce((acc, row) => {
    const key = String((row && row[field]) || 'unknown');
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

export function getDecompositionTotals(rows) {
  const filtered = rows.filter((row) => Number(row.queued_story_decomposition_count || 0) > 0 || row.queued_for_epic_decomposition || Number(row.remaining_story_count || 0) > 0);
  return {
    filtered,
    queuedStories: filtered.reduce((sum, row) => sum + Number(row.queued_story_decomposition_count || 0), 0),
    queuedEpics: filtered.reduce((sum, row) => sum + (row.queued_for_epic_decomposition ? 1 : 0), 0),
    remainingStories: filtered.reduce((sum, row) => sum + Number(row.remaining_story_count || 0), 0),
  };
}

export function getActiveTaskTotals(rows) {
  return rows.reduce((acc, row) => ({
    ready: acc.ready + Number(row.ready_task_count || 0),
    inProgress: acc.inProgress + Number(row.in_progress_task_count || 0),
    blocked: acc.blocked + Number(row.blocked_task_count || 0),
    decision: acc.decision + Number(row.decision_required_task_count || 0),
    activeQueue: acc.activeQueue + Number(row.active_queue_task_count || 0),
  }), { ready: 0, inProgress: 0, blocked: 0, decision: 0, activeQueue: 0 });
}

export function getRunningJobTotals(rows) {
  const filtered = rows.filter((row) => Number(row.running_job_count || 0) > 0);
  return {
    filtered,
    total: filtered.reduce((sum, row) => sum + Number(row.running_job_count || 0), 0),
  };
}

export function buildItemTitle(templateFn, values) {
  return String(templateFn(values || {})).trim();
}

export function buildDependencySummary(item, { localizeDirection, localizeStatus, t }) {
  const id = item.epic_issue_number ?? item.story_issue_number ?? t('common.emDash');
  return `${localizeDirection(item.direction)} · #${id} · ${item.title || ''} · ${localizeStatus(item.execution_status || t('common.unknown'))}`;
}

export function buildRunningJobSummary(job, { t }) {
  return `#${job.id} · ${job.job_kind || t('detail.overview.jobFallback')} · ${job.worker_name || t('detail.overview.workerFallback')} · ${job.started_at || t('common.emDash')}`;
}

export function buildRecentRunSummary(run, { localizeStatus, t }) {
  return `#${run.id} · ${localizeStatus(run.status || t('common.unknown'))} · ${t('detail.execution.exit', { code: run.exit_code ?? t('common.emDash') })} · ${run.started_at || t('common.emDash')}`;
}

export function buildJobDetailTitle(job, t) {
  return buildItemTitle((values) => t('detail.job.title', values), { id: job.id || '' });
}
