import type { Aircraft } from './airspace';

export type Position = [number, number];
export const aircraftPath = 'M12 1 Q13.2 1 13.3 3.8 L13.7 9 L22 14 L22 15.9 L13.6 13.4 L13.3 19 L16.1 21.2 L16.1 22.5 L12 21.4 L7.9 22.5 L7.9 21.2 L10.7 19 L10.4 13.4 L2 15.9 L2 14 L10.3 9 L10.7 3.8 Q10.8 1 12 1Z';
export const colors = { air: '#ffd65a', ground: '#97a8b4', selected: '#42e1c9' };
export const tileUrl = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
export const attribution = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>';

// A map symbol has a fixed screen size. Its vertical position uses the reported altitude.
const silhouette = [[0, -11], [1.3, -9], [1.7, -3], [10, 2], [10, 4], [1.5, 1.5],
  [1.3, 7], [4, 9.2], [4, 10.5], [0, 9.4], [-4, 10.5], [-4, 9.2], [-1.3, 7],
  [-1.5, 1.5], [-10, 4], [-10, 2], [-1.7, -3], [-1.3, -9], [0, -11]];
export function elevatedAircraft(a: Aircraft, zoom: number): Position[] {
  const degreesPerPixel = 360 / (512 * 2 ** zoom);
  const latScale = Math.cos(a.lat * Math.PI / 180);
  const bearing = (a.heading ?? 0) * Math.PI / 180;
  const cos = Math.cos(bearing), sin = Math.sin(bearing);
  return silhouette.map(([x, y]) => [
    a.lon + (x * cos - y * sin) * degreesPerPixel,
    a.lat - (x * sin + y * cos) * degreesPerPixel * latScale,
  ]);
}

export function coordinate(value: number, latitude: boolean) {
  const direction = latitude ? (value < 0 ? 'S' : 'N') : (value < 0 ? 'W' : 'E');
  return Math.abs(value).toFixed(2) + '°' + direction;
}
