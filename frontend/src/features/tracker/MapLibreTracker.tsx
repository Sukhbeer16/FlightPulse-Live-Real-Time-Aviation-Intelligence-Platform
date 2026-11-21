import { useEffect, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { Aircraft } from './airspace';

function aircraftIcon(fill: string) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 48;
  const ctx = canvas.getContext('2d')!;
  ctx.scale(2, 2);
  const path = new Path2D('M12 1 Q13.4 1 13.4 4 L13.5 9 L22 14 L22 16 L13.6 13.4 L13.5 19 L16 21 L16 22.5 L12 21.4 L8 22.5 L8 21 L10.5 19 L10.4 13.4 L2 16 L2 14 L10.5 9 L10.6 4 Q10.6 1 12 1Z');
  ctx.strokeStyle = '#24364a'; ctx.lineWidth = 1.5; ctx.lineJoin = 'round';
  ctx.stroke(path); ctx.fillStyle = fill; ctx.fill(path);
  return ctx.getImageData(0, 0, 48, 48);
}

interface Props {
  aircraft: Aircraft[]; selected: Aircraft | undefined; onSelect: (id: string) => void;
  center: [number, number]; globe: boolean; onMove: (center: [number, number]) => void;
}

export function MapLibreTracker({ aircraft, selected, onSelect, center, globe, onMove }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map>();
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const initial = useRef(center);
  useEffect(() => {
    let map: maplibregl.Map;
    try {
      map = new maplibregl.Map({
        container: container.current!, center: initial.current, zoom: 7,
        maxZoom: 18, attributionControl: {compact: true},
        style: { version: 8, sources: { streets: {
          type: 'raster', tileSize: 256, maxzoom: 19,
          tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        } }, layers: [
          { id: 'base', type: 'background', paint: {'background-color': '#bfdae3'} },
          { id: 'streets', source: 'streets', type: 'raster', paint: {'raster-saturation': -0.48, 'raster-opacity': 0.91} },
        ] },
      });
    } catch { setFailed(true); return; }
    mapRef.current = map;
    map.on('moveend', () => { const p = map.getCenter().wrap(); onMove([p.lng, p.lat]); });
    map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
    map.addControl(new maplibregl.ScaleControl({unit: 'nautical'}), 'bottom-left');
    map.on('style.load', () => {
      map.addImage('aircraft', aircraftIcon('#ffca3a'), {pixelRatio: 2});
      map.addImage('focused', aircraftIcon('#30cbe6'), {pixelRatio: 2});
      map.addSource('traffic', {type: 'geojson', data: {type: 'FeatureCollection', features: []}});
      map.addLayer({ id: 'traffic', type: 'symbol', source: 'traffic', layout: {
        'icon-image': ['case', ['get', 'selected'], 'focused', 'aircraft'],
        'icon-rotate': ['get', 'heading'], 'icon-rotation-alignment': 'map',
        'icon-pitch-alignment': 'viewport',
        'icon-size': ['interpolate', ['linear'], ['zoom'], 4, 0.45, 7, 0.82, 10, 1.15],
        'icon-allow-overlap': true, 'icon-ignore-placement': true,
        'symbol-sort-key': ['case', ['get','selected'], 1, 0],
      }});
      setReady(true);
    });
    map.on('click', 'traffic', e => { const id = e.features?.[0]?.properties.id; if (id) onSelect(id); });
    map.on('mouseenter', 'traffic', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'traffic', () => { map.getCanvas().style.cursor = ''; });
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(container.current!);
    return () => { observer.disconnect(); map.remove(); mapRef.current = undefined; };
  }, [onSelect, onMove]);
  useEffect(() => {
    if (!ready) return;
    mapRef.current!.getSource<GeoJSONSource>('traffic')?.setData({
      type: 'FeatureCollection', features: aircraft.map(a => ({
        type: 'Feature', geometry: {type: 'Point', coordinates: [a.lon, a.lat]},
        properties: {id: a.id, heading: a.heading ?? 0, selected: a.id === selected?.id},
      })),
    });
  }, [aircraft, selected, ready]);
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current!;
    map.setProjection({type: globe ? 'globe' : 'mercator'});
    map.easeTo({center, zoom: globe ? 7.2 : 7, pitch: globe ? 56 : 0, duration: 500});
  }, [globe, center, ready]);
  const focus = selected?.id;
  const current = useRef(selected);
  current.current = selected;
  useEffect(() => {
    const a = current.current;
    if (a && ready) mapRef.current?.easeTo({center: [a.lon, a.lat], duration: 420});
  }, [focus, ready, globe]);
  return <><div className="radar-canvas" ref={container} aria-label="Aircraft map" />{failed && <p className="map-error" role="alert">WebGL is unavailable. Aircraft observations are available in the flight list.</p>}</>;
}
