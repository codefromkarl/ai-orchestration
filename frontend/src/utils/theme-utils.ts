import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export type Theme = 'light' | 'dark' | 'cyberpunk' | 'programmer';

const THEME_STORAGE_KEY = 'stardrifter-theme';

export function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'cyberpunk' || stored === 'programmer') {
      return stored;
    }
  } catch {
    // ignore
  }
  return 'light';
}

export function applyTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // ignore
  }

  const root = document.documentElement;
  root.classList.remove('dark', 'theme-cyberpunk', 'theme-programmer');

  if (theme === 'dark') {
    root.classList.add('dark');
  } else if (theme === 'cyberpunk') {
    root.classList.add('theme-cyberpunk');
  } else if (theme === 'programmer') {
    root.classList.add('theme-programmer');
  }
}