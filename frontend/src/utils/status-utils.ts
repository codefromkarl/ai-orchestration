import { TaskStatus, Priority } from '../types';

export const statusColors: Record<TaskStatus, { bg: string; text: string; color: string }> = {
  pending: {
    bg: 'var(--badge-pending-bg)',
    text: 'var(--badge-pending-text)',
    color: 'var(--badge-pending-text)',
  },
  ready: {
    bg: 'var(--badge-ready-bg)',
    text: 'var(--badge-ready-text)',
    color: 'var(--badge-ready-text)',
  },
  in_progress: {
    bg: 'var(--badge-in_progress-bg)',
    text: 'var(--badge-in_progress-text)',
    color: 'var(--badge-in_progress-text)',
  },
  verifying: {
    bg: 'var(--badge-verifying-bg)',
    text: 'var(--badge-verifying-text)',
    color: 'var(--badge-verifying-text)',
  },
  blocked: {
    bg: 'var(--badge-blocked-bg)',
    text: 'var(--badge-blocked-text)',
    color: 'var(--badge-blocked-text)',
  },
  done: {
    bg: 'var(--badge-done-bg)',
    text: 'var(--badge-done-text)',
    color: 'var(--badge-done-text)',
  },
};

export const statusLabels: Record<TaskStatus, string> = {
  pending: '待办',
  ready: '就绪',
  in_progress: '进行中',
  verifying: '验证中',
  blocked: '阻塞',
  done: '完成',
};

export const priorityLabels: Record<Priority, string> = {
  governance: '治理',
  core_path: '核心路径',
  cross_cutting: '横切关注',
};

export function getStatusColor(status: TaskStatus) {
  return statusColors[status] || statusColors.pending;
}

export function getStatusLabel(status: TaskStatus) {
  return statusLabels[status] || status;
}

export function getPriorityLabel(priority?: Priority) {
  if (!priority) return '—';
  return priorityLabels[priority] || priority;
}

export function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[c] || c));
}
