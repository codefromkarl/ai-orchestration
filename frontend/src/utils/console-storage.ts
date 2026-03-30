export const CONSOLE_LOCALE_STORAGE_KEY = 'stardrifter-console-locale';
export const CONSOLE_SIDEBAR_COLLAPSED_STORAGE_KEY = 'stardrifter-console-sidebar-collapsed';
export const CONSOLE_FILTERS_STORAGE_KEY = 'stardrifter-console-filters';

export interface StoredConsoleFilters {
  repoScope?: 'single' | 'all';
  repo?: string;
  taskStatusFilter?: 'all' | 'pending' | 'ready' | 'in_progress' | 'verifying' | 'blocked' | 'done';
  taskSearchQuery?: string;
}

export function getStoredSidebarCollapsed(storageLike: Pick<Storage, 'getItem'> | null | undefined): boolean {
  const stored = storageLike && typeof storageLike.getItem === 'function'
    ? storageLike.getItem(CONSOLE_SIDEBAR_COLLAPSED_STORAGE_KEY)
    : null;
  return stored === 'true';
}

export function getStoredConsoleFilters(
  storageLike: Pick<Storage, 'getItem'> | null | undefined
): StoredConsoleFilters {
  try {
    const stored = storageLike && typeof storageLike.getItem === 'function'
      ? storageLike.getItem(CONSOLE_FILTERS_STORAGE_KEY)
      : null;
    if (!stored) return {};

    const parsed = JSON.parse(stored) as StoredConsoleFilters;
    const repoScope = parsed.repoScope === 'all' ? 'all' : 'single';
    const taskStatusFilterOptions = new Set(['all', 'pending', 'ready', 'in_progress', 'verifying', 'blocked', 'done']);
    const taskStatusFilter = taskStatusFilterOptions.has(String(parsed.taskStatusFilter))
      ? (parsed.taskStatusFilter as StoredConsoleFilters['taskStatusFilter'])
      : 'all';

    return {
      repoScope,
      repo: typeof parsed.repo === 'string' ? parsed.repo : '',
      taskStatusFilter,
      taskSearchQuery: typeof parsed.taskSearchQuery === 'string' ? parsed.taskSearchQuery : '',
    };
  } catch {
    return {};
  }
}
