// ─────────────────────────────────────────────
// FlightPulse Live — Centralized API Configuration
// ─────────────────────────────────────────────

const rawBase = import.meta.env.VITE_API_BASE_URL as string | undefined;

export const API_BASE_URL = (rawBase ?? '').replace(/\/+$/, '');

export const API_ENDPOINTS = {
  health: `${API_BASE_URL}/api/v1/health`,
  databaseHealth: `${API_BASE_URL}/api/v1/health/database`,
  models: `${API_BASE_URL}/api/v1/models`,
  flights: `${API_BASE_URL}/api/v1/flights`,
  flightSearch: `${API_BASE_URL}/api/v1/flights/search`,
  historicalFlights: `${API_BASE_URL}/api/v1/historical/processed-flights`,
  airlines: `${API_BASE_URL}/api/v1/airlines`,
  airports: `${API_BASE_URL}/api/v1/airports`,
  analyticsOverview: `${API_BASE_URL}/api/v1/analytics/overview`,
  analyticsReport: (report: string) =>
    `${API_BASE_URL}/api/v1/analytics/${encodeURIComponent(report)}`,
  providerStatus: `${API_BASE_URL}/api/v1/live/provider-status`,
  streamSummary: `${API_BASE_URL}/api/v1/live/stream-summary`,
  liveStates: `${API_BASE_URL}/api/v1/live/states`,
  liveIdentityMatch: `${API_BASE_URL}/api/v1/live/identity-match`,
  delayPrediction: (model = 'best') =>
    `${API_BASE_URL}/api/v1/predictions/delay?model=${encodeURIComponent(model)}`,
  anomaly: `${API_BASE_URL}/api/v1/intelligence/anomalies`,
  risk: `${API_BASE_URL}/api/v1/intelligence/risk`,
  alerts: `${API_BASE_URL}/api/v1/alerts`,
  evaluateAlert: `${API_BASE_URL}/api/v1/alerts/evaluate`,
  historicalAlert: `${API_BASE_URL}/api/v1/alerts/historical`,
  streamStates: `${API_BASE_URL}/api/v1/live/stream-states`,
} as const;

export const REQUEST_TIMEOUT_MS = 10_000;

export async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (options?.signal?.aborted) cancel();
  options?.signal?.addEventListener('abort', cancel, { once: true });
  const id = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(options?.body ? { 'Content-Type': 'application/json' } : {}),
        ...options?.headers,
      },
    });
    if (!res.ok) {
      let message = `HTTP ${res.status}: ${res.statusText}`;
      try {
        const body = await res.json();
        message = body?.error?.message || body?.detail || message;
      } catch {
        // Keep the status-based message when the response is not JSON.
      }
      throw new Error(message);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(id);
    options?.signal?.removeEventListener('abort', cancel);
  }
}

