const API_BASE = '';

async function buildErrorMessage(res: Response): Promise<string> {
  const fallback = `${res.status} ${res.statusText}`;

  try {
    const text = await res.text();
    if (!text) {
      return fallback;
    }

    try {
      const payload = JSON.parse(text) as { detail?: unknown; error?: unknown; message?: unknown };
      if (typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail.trim();
      if (typeof payload.error === 'string' && payload.error.trim()) return payload.error.trim();
      if (typeof payload.message === 'string' && payload.message.trim()) return payload.message.trim();
    } catch {
      return text.trim() || fallback;
    }

    return text.trim() || fallback;
  } catch {
    return fallback;
  }
}

export async function fetchJson<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, opts);
  if (!res.ok) {
    throw new Error(await buildErrorMessage(res));
  }
  return res.json();
}

export async function postConsoleAction(path: string): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>(path, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
    },
  });
}

export interface WorkItemsResponse {
  repo: string;
  items: Array<{
    id: string;
    source_issue_number: number;
    title: string;
    status: string;
    canonical_story_issue_number?: number;
    blocked_reason?: string;
    task_type?: string;
  }>;
  count: number;
}

export interface RepositoriesResponse {
  repositories: Array<{
    repo: string;
    epic_count?: number;
    story_count?: number;
    task_count?: number;
    active_task_count?: number;
  }>;
}

export interface SystemStatusResponse {
  config_source: string;
  postgres_dsn_configured: boolean;
  database_connected: boolean;
  database_error?: string;
  configured_repos: Array<{
    repo: string;
    workdir: string;
    log_dir: string;
    workdir_exists: boolean;
    log_dir_exists: boolean;
  }>;
  discovered_repositories: string[];
  commands: Record<string, {
    available: boolean;
    path?: string | null;
  }>;
  dev_compose_file: string;
  dev_env_file: string;
  recommended_actions: string[];
}

export interface IntentsResponse {
  repo: string;
  items: Array<{
    id: string;
    repo: string;
    prompt: string;
    status: string;
    summary?: string;
    clarification_questions_json?: string[];
    proposal_json?: {
      epic?: Record<string, unknown>;
      stories?: Array<{
        story_key?: string;
        title: string;
        lane?: string;
        complexity?: string;
        depends_on_story_keys?: string[];
        tasks?: Array<{
          task_key?: string;
          title: string;
          lane?: string;
          wave?: string;
          task_type?: string;
          blocking_mode?: string;
          planned_paths?: string[];
          dod?: string[];
          verification?: string[];
        }>;
      }>;
    };
    promoted_epic_issue_number?: number | null;
    approved_by?: string | null;
    reviewed_at?: string | null;
    reviewed_by?: string | null;
    review_action?: string | null;
    review_feedback?: string | null;
  }>;
  count: number;
}

export interface IntakeMutationResponse {
  intent_id: string;
  repo: string;
  status: string;
  summary?: string;
  questions?: string[];
  proposal?: {
    epic?: Record<string, unknown>;
    stories?: Array<{
      story_key?: string;
      title: string;
      lane?: string;
      complexity?: string;
      depends_on_story_keys?: string[];
      tasks?: Array<{
        task_key?: string;
        title: string;
        lane?: string;
        wave?: string;
        task_type?: string;
        blocking_mode?: string;
        planned_paths?: string[];
        dod?: string[];
        verification?: string[];
      }>;
    }>;
  };
  promoted_epic_issue_number?: number | null;
  approved_by?: string | null;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  review_action?: string | null;
  review_feedback?: string | null;
}

export interface RepoSummaryResponse {
  repo: string;
  total_epics?: number;
  total_stories?: number;
  total_tasks?: number;
  active_tasks?: number;
  completed_tasks?: number;
  blocked_tasks?: number;
  summary?: {
    total_epics?: number;
    total_stories?: number;
    total_tasks?: number;
    active_tasks?: number;
    completed_tasks?: number;
    blocked_tasks?: number;
  };
  snapshot_health?: {
    status?: string;
    summary?: string;
    repository_id?: string;
    snapshot_id?: string;
    schema_version?: string;
    artifact_status?: string;
    artifact_age_seconds?: number | null;
    lock_age_seconds?: number | null;
    lock_is_stale?: boolean;
    observed_at?: string;
  };
}

export interface EpicRowsResponse {
  repo: string;
  rows: Array<{
    epic_issue_number: number;
    title: string;
    lane?: string;
    program_status?: string;
    execution_status?: string;
    active_wave?: string;
    notes?: string | null;
    story_count: number;
    task_count: number;
    done_task_count: number;
    blocked_task_count: number;
    ready_task_count: number;
    in_progress_task_count: number;
    decision_required_task_count: number;
    active_queue_task_count: number;
    queued_story_decomposition_count: number;
    queued_for_epic_decomposition: boolean;
    dependency_count: number;
    running_job_count: number;
    execution_state_status?: string;
    completed_story_count?: number;
    execution_state_blocked_story_count?: number;
    remaining_story_count?: number;
    verification_status?: string;
    verification_reason_code?: string;
    verification_summary?: string;
  }>;
}

export interface EpicStoryTreeResponse {
  repo: string;
  rows: Array<{
    epic_issue_number: number;
    title: string;
    story_summaries?: Array<{
      story_issue_number: number;
      title: string;
      lane?: string;
      complexity?: string;
      execution_status?: string;
      program_status?: string;
      active_wave?: string;
      task_count?: number;
      done_task_count?: number;
      blocked_task_count?: number;
      ready_task_count?: number;
      in_progress_task_count?: number;
      decision_required_task_count?: number;
      active_queue_task_count?: number;
      running_job_count?: number;
      queued_for_story_decomposition?: boolean;
      task_summaries?: Array<{
        work_id: string;
        source_issue_number?: number;
        title: string;
        status?: string;
        task_type?: string;
        decision_required?: boolean;
        blocked_reason?: string;
        in_active_queue?: boolean;
      }>;
    }>;
  }>;
}

export interface EpicDetailResponse {
  repo: string;
  epic: {
    issue_number: number;
    repo?: string;
    title: string;
    lane?: string;
    program_status?: string;
    execution_status?: string;
    active_wave?: string;
    notes?: string | null;
  };
  stories: Array<{
    story_issue_number: number;
    title: string;
    lane?: string;
    complexity?: string;
    program_status?: string;
    execution_status?: string;
    active_wave?: string;
    notes?: string | null;
    task_count?: number;
    done_task_count?: number;
    blocked_task_count?: number;
    ready_task_count?: number;
    active_queue_task_count?: number;
    queued_for_story_decomposition?: boolean;
    story_pull_number?: number;
    story_pull_url?: string;
  }>;
  active_tasks: Array<{
    work_id: string;
    source_issue_number?: number;
    title: string;
    status?: string;
    task_type?: string;
    blocking_mode?: string;
    blocked_reason?: string;
    decision_required?: boolean;
    attempt_count?: number;
    last_failure_reason?: string;
    next_eligible_at?: string;
    canonical_story_issue_number?: number;
  }>;
  dependencies: Array<{
    epic_issue_number: number;
    title: string;
    execution_status?: string;
    direction: string;
  }>;
  execution_state: {
    status?: string;
    completed_story_issue_numbers_json?: number[];
    blocked_story_issue_numbers_json?: number[];
    remaining_story_issue_numbers_json?: number[];
    updated_at?: string;
  };
  running_jobs: Array<{
    id: number;
    job_kind?: string;
    status?: string;
    story_issue_number?: number;
    worker_name?: string;
    pid?: number;
    command?: string;
    log_path?: string;
    started_at?: string;
  }>;
  operator_requests: Array<{
    repo?: string;
    epic_issue_number?: number;
    reason_code: string;
    summary: string;
    remaining_story_issue_numbers_json?: number[];
    blocked_story_issue_numbers_json?: number[];
    status?: string;
    opened_at?: string;
    closed_at?: string | null;
    closed_reason?: string | null;
  }>;
}

export interface RunningJobsResponse {
  repo: string;
  jobs: Array<{
    id: number;
    job_kind?: string;
    status?: string;
    story_issue_number?: number;
    work_id?: string;
    worker_name?: string;
    pid?: number;
    command?: string;
    log_path?: string;
    started_at?: string;
  }>;
}

export interface RuntimeObservabilityResponse {
  repo: string;
  items: Array<{
    work_id: string;
    source_issue_number?: number;
    title?: string;
    status?: string;
    lane?: string;
    wave?: string;
    blocked_reason?: string | null;
    decision_required?: boolean;
    last_failure_reason?: string | null;
    active_claim_worker_name?: string | null;
    session_id?: string | null;
    session_status?: string | null;
    session_attempt_index?: number | null;
    session_current_phase?: string | null;
    session_waiting_reason?: string | null;
    session_updated_at?: string | null;
    last_checkpoint_summary?: string | null;
    last_checkpoint_next_action?: string | null;
    artifact_id?: number | null;
    artifact_session_id?: string | null;
    artifact_run_id?: number | null;
    artifact_type?: string | null;
    artifact_key?: string | null;
    artifact_mime_type?: string | null;
    artifact_content_size_bytes?: number | null;
    artifact_metadata?: Record<string, unknown>;
    artifact_created_at?: string | null;
  }>;
}

export interface JobDetailResponse {
  repo: string;
  job: {
    id: number;
    job_kind?: string;
    status?: string;
    story_issue_number?: number;
    work_id?: string;
    launch_backend?: string;
    worker_name?: string;
    pid?: number;
    command?: string;
    log_path?: string;
    started_at?: string;
    finished_at?: string | null;
    exit_code?: number | null;
  };
  story?: {
    story_issue_number?: number;
    story_title?: string;
    story_execution_status?: string;
    epic_issue_number?: number;
    epic_title?: string;
    epic_execution_status?: string;
  };
  task?: {
    work_id?: string;
    source_issue_number?: number;
    title?: string;
    status?: string;
    task_type?: string;
    attempt_count?: number;
    last_failure_reason?: string | null;
    next_eligible_at?: string | null;
  };
}

export interface StoryDetailResponse {
  repo: string;
  story: {
    story_issue_number: number;
    epic_issue_number?: number;
    title: string;
    lane?: string;
    complexity?: string;
    program_status?: string;
    execution_status?: string;
    active_wave?: string;
    notes?: string | null;
    verification_status?: string;
    verification_summary?: string;
    verification_check_type?: string;
  };
  tasks: Array<{
    work_id: string;
    source_issue_number?: number;
    title: string;
    status?: string;
    task_type?: string;
    decision_required?: boolean;
    blocked_reason?: string;
    in_active_queue?: boolean;
  }>;
  task_drafts: Array<Record<string, unknown>>;
  dependencies: Array<Record<string, unknown>>;
  jobs: Array<{
    id: number;
    job_kind?: string;
    status?: string;
    story_issue_number?: number;
    work_id?: string;
    worker_name?: string;
    pid?: number;
    command?: string;
    log_path?: string;
    started_at?: string;
  }>;
  decomposition_queue: Record<string, unknown>;
}

export interface TaskDetailResponse {
  repo: string;
  task: {
    id: string;
    story_issue_number?: number;
    epic_issue_number?: number;
    source_issue_number?: number;
    source_issue_title?: string;
    title?: string;
    status?: string;
    lane?: string;
    wave?: string;
    complexity?: string;
    task_type?: string;
     blocked_reason?: string;
     decision_required?: boolean;
  };
  snapshot_state?: {
    status?: string;
    summary?: string;
    repository_id?: string;
    snapshot_id?: string;
    schema_version?: string;
    artifact_status?: string;
    artifact_age_seconds?: number | null;
    lock_age_seconds?: number | null;
    lock_is_stale?: boolean;
    observed_at?: string;
  };
  retry_context: {
    latest_failure_reason_code?: string;
    blocked_reason?: string | null;
    decision_required?: boolean;
  };
  recent_runs: Array<Record<string, unknown>>;
  active_claim: {
    worker_name?: string;
  };
  approval_events: Array<Record<string, unknown>>;
  commit_link: Record<string, unknown>;
  pull_requests: Array<Record<string, unknown>>;
  jobs: Array<{
    id: number;
    job_kind?: string;
    status?: string;
    story_issue_number?: number;
    work_id?: string;
    worker_name?: string;
    pid?: number;
    command?: string;
    log_path?: string;
    started_at?: string;
  }>;
  sessions: Array<{
    id: string;
    status?: string;
    attempt_index?: number;
    current_phase?: string;
    waiting_reason?: string | null;
    created_at?: string;
    updated_at?: string;
    last_checkpoint_phase?: string | null;
    last_checkpoint_index?: number | null;
    last_checkpoint_summary?: string | null;
    last_checkpoint_next_action?: string | null;
  }>;
  artifacts: Array<{
    id: number;
    session_id?: string | null;
    run_id?: number | null;
    artifact_type?: string;
    artifact_key?: string;
    mime_type?: string;
    content_size_bytes?: number;
    metadata?: Record<string, unknown>;
    created_at?: string;
  }>;
}

export interface NotificationsResponse {
  notifications: Array<{
    id: number;
    status?: string;
    notification_type?: string;
    repo?: string;
    subject?: string;
    title?: string;
  }>;
}

export interface AgentsResponse {
  agents: Array<{
    agent_id?: string;
    agent_name?: string;
    repo?: string;
    status?: string;
    current_task?: string;
    worker_name?: string;
  }>;
}

export interface AgentStatsResponse {
  stats: Array<{
    agent_name: string;
    total_executions?: number;
    success_rate_percent?: number;
  }>;
}

export interface GovernancePriorityResponse {
  tasks: Array<{
    source_issue_number?: number;
    story_issue_number?: number;
    epic_issue_number?: number;
    title?: string;
    story_title?: string;
    epic_title?: string;
    kind?: string;
    priority_score?: string;
  }>;
}

export async function getWorkItems(repo: string, status?: string): Promise<WorkItemsResponse> {
  const query = status && status !== 'all' ? `?status=${encodeURIComponent(status)}` : '';
  return fetchJson<WorkItemsResponse>(`/api/repos/${encodeURIComponent(repo)}/work-items${query}`);
}

export async function getRepositories(): Promise<RepositoriesResponse> {
  return fetchJson<RepositoriesResponse>('/api/repos');
}

export async function getSystemStatus(): Promise<SystemStatusResponse> {
  return fetchJson<SystemStatusResponse>('/api/system/status');
}

export async function getIntents(repo: string): Promise<IntentsResponse> {
  return fetchJson<IntentsResponse>(`/api/repos/${encodeURIComponent(repo)}/intents`);
}

export async function submitIntent(repo: string, prompt: string): Promise<IntakeMutationResponse> {
  return fetchJson<IntakeMutationResponse>(`/api/repos/${encodeURIComponent(repo)}/intents`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ prompt }),
  });
}

export async function answerIntent(intentId: string, answer: string): Promise<IntakeMutationResponse> {
  return fetchJson<IntakeMutationResponse>(`/api/intents/${encodeURIComponent(intentId)}/answer`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ answer }),
  });
}

export async function approveIntent(intentId: string, approver: string): Promise<IntakeMutationResponse> {
  return fetchJson<IntakeMutationResponse>(`/api/intents/${encodeURIComponent(intentId)}/approve`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ approver }),
  });
}

export async function rejectIntent(
  intentId: string,
  reviewer: string,
  reason: string,
): Promise<IntakeMutationResponse> {
  return fetchJson<IntakeMutationResponse>(`/api/intents/${encodeURIComponent(intentId)}/reject`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ reviewer, reason }),
  });
}

export async function reviseIntent(
  intentId: string,
  reviewer: string,
  feedback: string,
): Promise<IntakeMutationResponse> {
  return fetchJson<IntakeMutationResponse>(`/api/intents/${encodeURIComponent(intentId)}/revise`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ reviewer, feedback }),
  });
}

export async function getRepoSummary(repo: string): Promise<RepoSummaryResponse> {
  return fetchJson<RepoSummaryResponse>(`/api/repos/${encodeURIComponent(repo)}/summary`);
}

export async function getEpicRows(repo: string): Promise<EpicRowsResponse> {
  return fetchJson<EpicRowsResponse>(`/api/repos/${encodeURIComponent(repo)}/epics`);
}

export async function getEpicStoryTree(repo: string): Promise<EpicStoryTreeResponse> {
  return fetchJson<EpicStoryTreeResponse>(`/api/repos/${encodeURIComponent(repo)}/epic-story-tree`);
}

export async function getEpicDetail(repo: string, epicIssueNumber: number): Promise<EpicDetailResponse> {
  return fetchJson<EpicDetailResponse>(`/api/repos/${encodeURIComponent(repo)}/epics/${encodeURIComponent(epicIssueNumber)}`);
}

export async function getRunningJobs(repo: string): Promise<RunningJobsResponse> {
  return fetchJson<RunningJobsResponse>(`/api/repos/${encodeURIComponent(repo)}/jobs`);
}

export async function getRuntimeObservability(repo: string): Promise<RuntimeObservabilityResponse> {
  return fetchJson<RuntimeObservabilityResponse>(`/api/repos/${encodeURIComponent(repo)}/runtime-observability`);
}

export async function getJobDetail(repo: string, jobId: number): Promise<JobDetailResponse> {
  return fetchJson<JobDetailResponse>(`/api/repos/${encodeURIComponent(repo)}/jobs/${encodeURIComponent(jobId)}`);
}

export async function getStoryDetail(repo: string, storyIssueNumber: number): Promise<StoryDetailResponse> {
  return fetchJson<StoryDetailResponse>(`/api/repos/${encodeURIComponent(repo)}/stories/${encodeURIComponent(storyIssueNumber)}`);
}

export async function getTaskDetail(repo: string, workId: string): Promise<TaskDetailResponse> {
  return fetchJson<TaskDetailResponse>(`/api/repos/${encodeURIComponent(repo)}/tasks/${encodeURIComponent(workId)}`);
}

export async function getGovernancePriority(repo: string): Promise<GovernancePriorityResponse> {
  return fetchJson<GovernancePriorityResponse>(`/api/repos/${encodeURIComponent(repo)}/governance/priority`);
}

export async function getNotifications(repo: string): Promise<NotificationsResponse> {
  return fetchJson<NotificationsResponse>(`/api/notifications?repo=${encodeURIComponent(repo)}`);
}

export async function getFailedNotifications(repo: string): Promise<NotificationsResponse> {
  return fetchJson<NotificationsResponse>(`/api/notifications/failed?repo=${encodeURIComponent(repo)}&limit=100`);
}

export async function getAgents(repo: string): Promise<AgentsResponse> {
  return fetchJson<AgentsResponse>(`/api/agents?repo=${encodeURIComponent(repo)}`);
}

export async function getAgentStats(): Promise<AgentStatsResponse> {
  return fetchJson<AgentStatsResponse>('/api/agents/stats');
}

export interface HierarchyResponse {
  epics: Array<{
    issue_number: number;
    title: string;
    issue_kind: string;
    github_state?: string;
    status_label?: string;
    url?: string;
    lane?: string;
    complexity?: number;
    work_status?: string;
    blocked_reason?: string;
    decision_required?: boolean;
    body?: string;
    parents?: number[];
    relations?: Array<{ dir: string; number: number; type: string }>;
    children?: Array<import('./types').HierarchyNode>;
  }>;
  orphan_stories: Array<import('./types').HierarchyNode>;
  orphan_tasks: Array<import('./types').HierarchyNode>;
}

export async function getHierarchy(repo: string): Promise<HierarchyResponse> {
  return fetchJson<HierarchyResponse>(`/api/hierarchy?repo=${encodeURIComponent(repo)}`);
}

export async function getIssueDetail(issueNumber: number, repo: string): Promise<{
  issue_number: number;
  title: string;
  issue_kind: string;
  github_state?: string;
  lane?: string;
  complexity?: number;
  body?: string;
  url?: string;
  work_item?: {
    status: string;
    wave?: string;
    blocked_reason?: string;
    decision_required?: boolean;
  };
}> {
  return fetchJson(`/api/issue/${encodeURIComponent(issueNumber)}?repo=${encodeURIComponent(repo)}`);
}
