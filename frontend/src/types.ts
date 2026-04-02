export type TaskStatus = 'pending' | 'ready' | 'in_progress' | 'verifying' | 'blocked' | 'done';

export type SnapshotHealthStatus = 'ready' | 'building' | 'missing' | 'failed' | 'stale_lock' | 'unknown';

export type Priority = 'governance' | 'core_path' | 'cross_cutting';

export type IssueKind = 'epic' | 'story' | 'task' | 'unknown';

export type ConsoleTabId = 'kanban' | 'command' | 'repository' | 'hierarchy';

export type ConsoleNavSection = 'overview' | 'detail';

export type WorkspaceViewId =
  | 'epic_overview'
  | 'running_jobs'
  | 'runtime_observability'
  | 'task_repository'
  | 'command_center'
  | 'story_tree'
  | 'notifications'
  | 'agent_console'
  | 'system_status';

export interface EpicOverviewRow {
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
}

export interface EpicDetailStorySummary {
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
    status?: TaskStatus;
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
    status?: TaskStatus;
    lane?: string;
    wave?: string;
    complexity?: string;
    task_type?: string;
    blocked_reason?: string;
    decision_required?: boolean;
  };
  snapshot_state?: TaskSnapshotState;
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
  stories: EpicDetailStorySummary[];
  active_tasks: Array<{
    work_id: string;
    source_issue_number?: number;
    title: string;
    status?: TaskStatus;
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
}

export interface DrawerDetailItem {
  kind: 'task' | 'epic' | 'job';
  number: number;
  title: string;
  type: IssueKind;
  status?: TaskStatus;
  lane?: string;
  wave?: string;
  complexity?: number | string;
  blockedReason?: string;
  decisionRequired?: boolean;
  githubUrl?: string;
  epicNumber?: number;
  storyNumber?: number;
  priority?: Priority;
  metaSummary?: string;
  snapshotState?: TaskSnapshotState;
  runtimeSessions?: Array<{
    id: string;
    status?: string;
    attemptIndex?: number;
    currentPhase?: string;
    waitingReason?: string | null;
    updatedAt?: string;
    checkpointSummary?: string | null;
    checkpointNextAction?: string | null;
  }>;
  artifacts?: Array<{
    id: number;
    sessionId?: string | null;
    runId?: number | null;
    artifactType?: string;
    artifactKey?: string;
    mimeType?: string;
    contentSizeBytes?: number;
    summary?: string;
    createdAt?: string;
  }>;
  storySummaries?: EpicDetailStorySummary[];
  taskSummaries?: Array<{
    workId: string;
    issueNumber?: number;
    title: string;
    status?: TaskStatus;
  }>;
  actionButtons?: Array<{
    label: string;
    actionUrl: string;
    tone?: 'primary' | 'danger';
  }>;
}

export interface RunningJobSummary {
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
}

export interface RuntimeObservationItem {
  workId: string;
  issueNumber?: number;
  title: string;
  status?: TaskStatus;
  lane?: string;
  wave?: string;
  blockedReason?: string | null;
  decisionRequired?: boolean;
  lastFailureReason?: string | null;
  workerName?: string | null;
  sessionId?: string | null;
  sessionStatus?: string | null;
  sessionAttemptIndex?: number | null;
  sessionCurrentPhase?: string | null;
  sessionWaitingReason?: string | null;
  sessionUpdatedAt?: string | null;
  checkpointSummary?: string | null;
  checkpointNextAction?: string | null;
  artifactId?: number | null;
  artifactType?: string | null;
  artifactKey?: string | null;
  artifactSummary?: string;
  artifactCreatedAt?: string | null;
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

export interface RepoSnapshotHealth {
  status?: SnapshotHealthStatus | string;
  summary?: string;
  repository_id?: string;
  snapshot_id?: string;
  schema_version?: string;
  artifact_status?: string;
  artifact_age_seconds?: number | null;
  lock_age_seconds?: number | null;
  lock_is_stale?: boolean;
  observed_at?: string;
}

export interface TaskSnapshotState {
  status?: SnapshotHealthStatus | string;
  summary?: string;
  repository_id?: string;
  snapshot_id?: string;
  schema_version?: string;
  artifact_status?: string;
  artifact_age_seconds?: number | null;
  lock_age_seconds?: number | null;
  lock_is_stale?: boolean;
  observed_at?: string;
}

export interface NotificationItem {
  id: number;
  status?: string;
  notification_type?: string;
  repo?: string;
  subject?: string;
  title?: string;
}

export interface AgentStatusItem {
  agent_id?: string;
  agent_name?: string;
  repo?: string;
  status?: string;
  current_task?: string;
  worker_name?: string;
}

export interface AgentEfficiencyStat {
  agent_name: string;
  total_executions?: number;
  success_rate_percent?: number;
}

export interface WorkItem {
  id?: string;
  repo?: string;
  number: number;
  title: string;
  type: IssueKind;
  status: TaskStatus;
  epicNumber?: number;
  storyNumber?: number;
  priority?: Priority;
  lane?: string;
  wave?: string;
  complexity?: number;
  blockedReason?: string;
  decisionRequired?: boolean;
  githubUrl?: string;
  githubState?: 'open' | 'closed';
  body?: string;
}

export interface AttentionItem {
  id: string;
  issueNumber: number;
  title: string;
  priorityScore: number;
  reason: string;
}

export interface RepoSummary {
  repo: string;
  totalEpics: number;
  totalStories: number;
  totalTasks: number;
  activeTasks: number;
  completedTasks: number;
  blockedTasks: number;
  snapshotHealth?: RepoSnapshotHealth;
}

export interface CommandMessage {
  id: string;
  type: 'user' | 'system';
  content: string;
  timestamp: Date;
}

export interface WorkItemApiResponse {
  id: string;
  source_issue_number: number;
  title: string;
  status: TaskStatus;
  canonical_story_issue_number?: number;
  blocked_reason?: string;
  task_type?: string;
}

export interface HierarchyNode {
  issue_number: number;
  title: string;
  issue_kind: IssueKind;
  github_state?: string;
  status_label?: string;
  url?: string;
  lane?: string;
  complexity?: number;
  work_status?: TaskStatus;
  blocked_reason?: string;
  decision_required?: boolean;
  children?: HierarchyNode[];
}

export interface EpicStoryTreeRow {
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
      status?: TaskStatus;
      task_type?: string;
      decision_required?: boolean;
      blocked_reason?: string;
      in_active_queue?: boolean;
    }>;
  }>;
}
