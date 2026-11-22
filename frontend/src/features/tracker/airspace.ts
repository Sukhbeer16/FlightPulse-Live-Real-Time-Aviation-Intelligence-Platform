export const regions = {
  'new-york': { name: 'New York', center: [-73.8, 40.75] },
  london: { name: 'London', center: [-0.45, 51.47] },
  delhi: { name: 'Delhi', center: [77.1, 28.56] },
  amsterdam: { name: 'Amsterdam', center: [4.76, 52.31] },
} satisfies Record<string, {name: string; center: [number, number]}>;
export type Region = keyof typeof regions;
export interface Aircraft {
  provider?: string;
  id: string; callsign: string; registration: string | null; type: string | null;
  lon: number; lat: number; ground: boolean; altitude: number | null;
  speed: number | null; heading: number | null; verticalRate: number | null;
  observed: number; squawk: string | null;
}
export interface Snapshot { time: number; aircraft: Aircraft[]; recorded?: boolean }
export const utc = (ms: number) => new Date(ms).toISOString().slice(11,19) + ' UTC';
export const measure = (n: number | null, unit: string) => n == null ? '—' : Math.round(n).toLocaleString() + ' ' + unit;
