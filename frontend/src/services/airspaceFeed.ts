import { API_BASE_URL, apiFetch } from './apiConfig';
import { regions, type Snapshot } from '../features/tracker/airspace';

// Keep only the most recently viewed area. Never reuse positions from another region.
const storageKey = 'flightpulse.last-observation.v1';

function validSnapshot(value: Snapshot | null | undefined): value is Snapshot {
  return !!value && Number.isFinite(value.time) && value.time > 0 && Array.isArray(value.aircraft)
    && value.aircraft.every(a => a && typeof a.id === 'string' && typeof a.callsign === 'string'
      && Number.isFinite(a.lat) && Number.isFinite(a.lon));
}

export function savedAirspace(endpoint: string): Snapshot | undefined {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? 'null');
    if (saved?.endpoint === endpoint && validSnapshot(saved.snapshot)) {
      return { ...saved.snapshot, recorded: true };
    }
  } catch { /* Storage can be disabled in private browsing. */ }
}

export async function fetchAirspace(endpoint: string, center: [number, number], signal: AbortSignal): Promise<Snapshot> {
  try {
    const snapshot = await apiFetch<Snapshot>(API_BASE_URL + '/api/v1/live' + endpoint, { signal });
    if (!validSnapshot(snapshot)) throw new Error('Invalid aircraft response');
    if (!signal.aborted) {
      try { localStorage.setItem(storageKey, JSON.stringify({ endpoint, snapshot })); }
      catch { /* The live report still works when local storage is full. */ }
    }
    return snapshot;
  } catch (error) {
    if (signal.aborted) throw error;
    const saved = savedAirspace(endpoint);
    if (saved) return saved;
    const region = Object.entries(regions).find(([, r]) => r.center[0] === center[0] && r.center[1] === center[1]);
    if (!region) throw error;
    const response = await fetch(import.meta.env.BASE_URL + 'observations/' + region[0] + '.json', { signal });
    if (!response.ok) throw error;
    const snapshot: Snapshot = await response.json();
    if (!validSnapshot(snapshot)) throw error;
    return { ...snapshot, recorded: true };
  }
}
