import { useEffect, useState } from 'react';
import { apiFetch } from '../../services/apiConfig';

export interface Statistics {
  total_flights: number;
  eligible_arrival_records: number;
  delayed_flights: number;
  cancelled_flights: number;
  diverted_flights: number;
  delay_rate: number | null;
  average_arrival_delay_minutes: number | null;
}
export interface OverviewReport { source_period: string; statistics: Statistics }
export interface Report<T> { source_period: string; data: T[] }

export function useReport<T>(url: string) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(undefined);
    setError('');
    apiFetch<T>(url, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [url, attempt]);
  return { data, error, retry: () => setAttempt(n => n + 1) };
}

export function reportingMonth(period?: string) {
  if (!period) return 'Reporting period pending';
  const date = new Date(period + '-01T00:00:00Z');
  return Number.isNaN(date.getTime()) ? period : date.toLocaleDateString('en-US', {
    month: 'long', year: 'numeric', timeZone: 'UTC',
  });
}
