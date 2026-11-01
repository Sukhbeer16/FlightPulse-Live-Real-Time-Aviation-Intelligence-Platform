// ─────────────────────────────────────────────
// FlightPulse Live — Centralized API Configuration
// ─────────────────────────────────────────────

const rawBase = import.meta.env.VITE_API_BASE_URL as string | undefined;

export const API_BASE_URL = (rawBase ?? 'http://127.0.0.1:8000').replace(/\/+$/, '');

export const API_ENDPOINTS = {
  health: `${API_BASE_URL}/health`,

  // Live Tracking
  liveAircraft: `${API_BASE_URL}/api/v1/live/aircraft`,
  aircraftDetail: (icao24: string) => `${API_BASE_URL}/api/v1/live/aircraft/${icao24}`,

  // Historical Analytics
  delayTrend: `${API_BASE_URL}/api/v1/analytics/delay-trend`,
  airlinePerformance: `${API_BASE_URL}/api/v1/analytics/airline-performance`,
  flightActivity: `${API_BASE_URL}/api/v1/analytics/flight-activity`,

  // Prediction
  predictDelay: `${API_BASE_URL}/api/v1/predict/delay`,

  // Anomaly Detection
  anomalies: `${API_BASE_URL}/api/v1/anomalies`,

  // System
  systemStatus: `${API_BASE_URL}/api/v1/system/status`,
} as const;

export const REQUEST_TIMEOUT_MS = 10_000;

export async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(id);
  }
}

