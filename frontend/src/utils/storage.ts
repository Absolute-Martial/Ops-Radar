export type Theme = 'light' | 'dark';

const OPSRADAR_TOKEN_KEY = 'opsradar_token';
const FLOWMINER_TOKEN_KEY = 'flowminer_token';
const OPSRADAR_THEME_KEY = 'opsradar-theme';
const FLOWMINER_THEME_KEY = 'flowminer-theme';

function canUseStorage(): boolean {
  return typeof window !== 'undefined' && typeof localStorage !== 'undefined';
}

function readMigratingValue(preferredKey: string, legacyKey: string): string | null {
  if (!canUseStorage()) return null;
  const preferred = localStorage.getItem(preferredKey);
  if (preferred) return preferred;
  const legacy = localStorage.getItem(legacyKey);
  if (legacy) {
    localStorage.setItem(preferredKey, legacy);
    return legacy;
  }
  return null;
}

function writeMigratingValue(preferredKey: string, legacyKey: string, value: string): void {
  if (!canUseStorage()) return;
  localStorage.setItem(preferredKey, value);
  localStorage.setItem(legacyKey, value);
}

function removeMigratingValue(preferredKey: string, legacyKey: string): void {
  if (!canUseStorage()) return;
  localStorage.removeItem(preferredKey);
  localStorage.removeItem(legacyKey);
}

export function getAuthToken(): string | null {
  return readMigratingValue(OPSRADAR_TOKEN_KEY, FLOWMINER_TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  writeMigratingValue(OPSRADAR_TOKEN_KEY, FLOWMINER_TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  removeMigratingValue(OPSRADAR_TOKEN_KEY, FLOWMINER_TOKEN_KEY);
}

export function getStoredTheme(): Theme | null {
  const stored = readMigratingValue(OPSRADAR_THEME_KEY, FLOWMINER_THEME_KEY);
  return stored === 'light' || stored === 'dark' ? stored : null;
}

export function setStoredTheme(theme: Theme): void {
  writeMigratingValue(OPSRADAR_THEME_KEY, FLOWMINER_THEME_KEY, theme);
}
