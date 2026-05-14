const DEFAULT_API_BASE_URL = '/api/v1';

function normalizeApiBaseUrl(baseUrl: string): string {
  const trimmed = baseUrl.trim();
  if (!trimmed) {
    return DEFAULT_API_BASE_URL;
  }
  return trimmed.replace(/\/+$/, '');
}

export function getApiBaseUrl(): string {
  const envBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;
  return normalizeApiBaseUrl(envBaseUrl || DEFAULT_API_BASE_URL);
}

export function buildApiUrl(path: string): string {
  const baseUrl = getApiBaseUrl();
  const suffix = path.replace(/^\/+/, '');
  return `${baseUrl}/${suffix}`;
}

export function buildWebSocketUrl(path: string): string {
  const apiBaseUrl = getApiBaseUrl();
  const suffix = path.replace(/^\/+/, '');
  const [suffixPath, suffixQuery = ''] = suffix.split('?');

  if (/^https?:\/\//i.test(apiBaseUrl)) {
    const url = new URL(apiBaseUrl);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = `${url.pathname.replace(/\/+$/, '')}/${suffixPath}`;
    url.search = suffixQuery ? `?${suffixQuery}` : '';
    return url.toString();
  }

  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${protocol}://${window.location.host}${apiBaseUrl}/${suffixPath}${suffixQuery ? `?${suffixQuery}` : ''}`;
}
