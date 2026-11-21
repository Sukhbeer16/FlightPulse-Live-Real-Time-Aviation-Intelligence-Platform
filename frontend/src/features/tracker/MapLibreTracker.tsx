// ─────────────────────────────────────────────────────────
// FlightPulse Live — MapLibre Aviation Flight Tracker
// High-performance dark tactical map with heading-oriented markers & route arcs
// ─────────────────────────────────────────────────────────

import React, { useEffect, useRef, useState, useCallback } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Plane, Compass, Maximize2, Layers, RefreshCw } from 'lucide-react';
import type { FlightTrack } from '../../types';

interface MapLibreTrackerProps {
  flights: FlightTrack[];
  selectedFlight: FlightTrack | null;
  onSelectFlight: (flight: FlightTrack | null) => void;
  showRoutes?: boolean;
  showLabels?: boolean;
  radarSweeps?: boolean;
}

export const MapLibreTracker: React.FC<MapLibreTrackerProps> = ({
  flights,
  selectedFlight,
  onSelectFlight,
  showRoutes = true,
  showLabels = true,
  radarSweeps = true,
}) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<Map<string, maplibregl.Marker>>(new Map());
  const [mapLoaded, setMapLoaded] = useState(false);
  const [mapBearing, setMapBearing] = useState(0);
  const [mapZoom, setMapZoom] = useState(3);
  const [cursorCoords, setCursorCoords] = useState<[number, number] | null>(null);

  const latestFlights = useRef(flights);
  latestFlights.current = flights;
  // Initialize MapLibre
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          'osm': {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            maxzoom: 19,
            tileSize: 256,
            attribution: '<a href="https://www.openstreetmap.org/copyright">&copy; OpenStreetMap contributors</a>',
          },
        },
        layers: [
          {
            id: 'background',
            type: 'background',
            paint: { 'background-color': '#060A13' },
          },
          {
            id: 'osm-layer',
            type: 'raster',
            source: 'osm',
            paint: {
              'raster-opacity': 0.85,
              'raster-contrast': 0.15,
              'raster-brightness-min': 0.05,
              'raster-brightness-max': 0.5,
            },
          },
        ],
      },
      center: [-35, 38],
      zoom: 2.8,
      pitch: 0,
      bearing: 0,
      attributionControl: { compact: false },
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'bottom-right');

    map.on('load', () => {
      setMapLoaded(true);

      // Add GeoJSON source for selected flight route
      map.addSource('route-source', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: [],
        },
      });

      // Route Glow Layer (outer cyan blur)
      map.addLayer({
        id: 'route-glow',
        type: 'line',
        source: 'route-source',
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
        },
        paint: {
          'line-color': '#00E5FF',
          'line-width': 5,
          'line-opacity': 0.35,
          'line-blur': 3,
        },
      });

      // Route Main Line (crisp dashed line)
      map.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'route-source',
        layout: {
          'line-cap': 'round',
          'line-join': 'round',
        },
        paint: {
          'line-color': '#00E5FF',
          'line-width': 2,
          'line-dasharray': [2, 2],
          'line-opacity': 0.9,
        },
      });

      // Airport points source
      map.addSource('airports-source', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: [],
        },
      });

      // Airport halo circle
      map.addLayer({
        id: 'airport-halos',
        type: 'circle',
        source: 'airports-source',
        paint: {
          'circle-radius': 10,
          'circle-color': '#00E5FF',
          'circle-opacity': 0.2,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#00E5FF',
        },
      });

      // Airport center dot
      map.addLayer({
        id: 'airport-dots',
        type: 'circle',
        source: 'airports-source',
        paint: {
          'circle-radius': 4,
          'circle-color': '#FFFFFF',
        },
      });
    });

    map.on('rotate', () => {
      setMapBearing(Math.round(map.getBearing()));
    });

    map.on('zoom', () => {
      setMapZoom(parseFloat(map.getZoom().toFixed(1)));
    });

    map.on('mousemove', (e) => {
      setCursorCoords([
        parseFloat(e.lngLat.lng.toFixed(3)),
        parseFloat(e.lngLat.lat.toFixed(3)),
      ]);
    });

    mapRef.current = map;

    return () => {
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current.clear();
      map.remove();
      mapRef.current = null;
      setMapLoaded(false);
    };
  }, []);

  // Update Route visualization when selected flight changes
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return;
    const map = mapRef.current;

    const routeSource = map.getSource('route-source') as maplibregl.GeoJSONSource | undefined;
    const airportsSource = map.getSource('airports-source') as maplibregl.GeoJSONSource | undefined;

    if (!routeSource || !airportsSource) return;

    if (
      selectedFlight &&
      showRoutes &&
      selectedFlight.origin.coordinates &&
      selectedFlight.destination.coordinates &&
      selectedFlight.routeWaypoints.length > 1
    ) {
      // Set route line
      routeSource.setData({
        type: 'Feature',
        properties: {
          callsign: selectedFlight.callsign,
        },
        geometry: {
          type: 'LineString',
          coordinates: selectedFlight.routeWaypoints,
        },
      });

      // Set origin and destination airport pins
      airportsSource.setData({
        type: 'FeatureCollection',
        features: [
          {
            type: 'Feature',
            properties: { label: selectedFlight.origin.iata, type: 'origin' },
            geometry: {
              type: 'Point',
              coordinates: selectedFlight.origin.coordinates,
            },
          },
          {
            type: 'Feature',
            properties: { label: selectedFlight.destination.iata, type: 'destination' },
            geometry: {
              type: 'Point',
              coordinates: selectedFlight.destination.coordinates,
            },
          },
        ],
      });
    } else {
      // Clear route
      routeSource.setData({
        type: 'FeatureCollection',
        features: [],
      });
      airportsSource.setData({
        type: 'FeatureCollection',
        features: [],
      });
    }
  }, [selectedFlight, showRoutes, mapLoaded]);

  // Update or create Aircraft Markers
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return;
    const map = mapRef.current;
    const activeFlightIds = new Set(flights.map((f) => f.id));

    // Remove obsolete markers
    markersRef.current.forEach((marker, id) => {
      if (!activeFlightIds.has(id)) {
        marker.remove();
        markersRef.current.delete(id);
      }
    });

    // Create or update markers
    flights.forEach((flight) => {
      if (
        flight.telemetry.longitude === null ||
        flight.telemetry.latitude === null ||
        !Number.isFinite(flight.telemetry.longitude) ||
        !Number.isFinite(flight.telemetry.latitude)
      ) {
        const obsolete = markersRef.current.get(flight.id);
        if (obsolete) {
          obsolete.remove();
          markersRef.current.delete(flight.id);
        }
        return;
      }
      const altitudeLabel = flight.telemetry.altitudeFt == null ? 'Altitude unknown' : 'FL' + Math.round(flight.telemetry.altitudeFt / 100);
      const isSelected = selectedFlight?.id === flight.id;
      const isCritical = flight.intelligence.riskLevel === 'critical';
      const isDelayed = flight.delayMinutes > 15;
      const existing = markersRef.current.get(flight.id);

      const color = isCritical
        ? '#EF4444'
        : isSelected
        ? '#00E5FF'
        : isDelayed
        ? '#F59E0B'
        : '#38BDF8';

      if (!existing) {
        // Create custom HTML element for marker
        const el = document.createElement('div');
        el.className = 'flight-marker-container cursor-pointer select-none group';
        el.id = `flight-marker-${flight.id}`;

        el.innerHTML = `
          <div class="relative flex items-center justify-center">
            ${
              isCritical
                ? '<div class="absolute -inset-2 rounded-full border border-red-500 bg-red-500/20 animate-ping"></div>'
                : ''
            }
            ${
              isSelected
                ? '<div class="absolute -inset-2.5 rounded-full border border-cyan-400 bg-cyan-400/15 animate-pulse"></div>'
                : ''
            }
            <div class="aircraft-icon-wrapper transition-transform duration-500 ease-out" style="transform: rotate(${
              flight.telemetry.headingDeg
            }deg);">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="${color}" stroke="#060A13" stroke-width="1.2">
                <path d="M12 2L13.5 9L21 13L21 15L13.5 13.5L13.5 19L16 21L16 22L12 21L8 22L8 21L10.5 19L10.5 13.5L3 15L3 13L10.5 9L12 2Z" />
              </svg>
            </div>
            ${
              showLabels
                ? `
              <div class="flight-tag absolute left-6 top-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded bg-slate-900/90 border border-slate-700/80 text-[10px] font-mono text-slate-200 whitespace-nowrap pointer-events-none shadow-md backdrop-blur-sm flex items-center gap-1.5 z-10 transition-opacity">
                <span class="font-bold text-${
                  isSelected ? 'cyan-400' : isCritical ? 'red-400' : 'slate-200'
                }" data-callsign></span>
                <span class="text-slate-400 text-[9px]" data-altitude>${altitudeLabel}</span>
              </div>
            `
                : ''
            }
          </div>
        `;

        const label = el.querySelector('[data-callsign]');
        if (label) label.textContent = flight.callsign;
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          onSelectFlight(latestFlights.current.find(item => item.id === flight.id) ?? null);
        });

        const marker = new maplibregl.Marker({
          element: el,
          anchor: 'center',
        })
          .setLngLat([flight.telemetry.longitude, flight.telemetry.latitude])
          .addTo(map);

        markersRef.current.set(flight.id, marker);
      } else {
        // Smoothly update position
        existing.setLngLat([flight.telemetry.longitude, flight.telemetry.latitude]);

        // Update heading rotation and styling in DOM
        const el = existing.getElement();
        const iconWrapper = el.querySelector('.aircraft-icon-wrapper') as HTMLElement | null;
        if (iconWrapper) {
          iconWrapper.style.transform = `rotate(${flight.telemetry.headingDeg}deg)`;
        }

        // Update tag if needed
        const tag = el.querySelector('.flight-tag') as HTMLElement | null;
        const altitude = el.querySelector('[data-altitude]');
        const label = el.querySelector('[data-callsign]');
        if (altitude) altitude.textContent = altitudeLabel;
        if (label) label.textContent = flight.callsign;
        if (tag) {
          tag.style.display = showLabels ? 'flex' : 'none';
        }
      }
    });
  }, [flights, selectedFlight, showLabels, mapLoaded, onSelectFlight]);

  // Center on selected flight smoothly
  const handleFlyToSelected = useCallback(() => {
    if (
      !mapRef.current ||
      !selectedFlight ||
      selectedFlight.telemetry.longitude === null ||
      selectedFlight.telemetry.latitude === null
    ) return;
    mapRef.current.flyTo({
      center: [selectedFlight.telemetry.longitude, selectedFlight.telemetry.latitude],
      zoom: 6.5,
      speed: 1.2,
      curve: 1.4,
      essential: true,
    });
  }, [selectedFlight]);

  // Auto fly-to when selected flight changes from external click
  useEffect(() => {
    if (
      selectedFlight &&
      mapRef.current &&
      selectedFlight.telemetry.longitude !== null &&
      selectedFlight.telemetry.latitude !== null
    ) {
      mapRef.current.flyTo({
        center: [selectedFlight.telemetry.longitude, selectedFlight.telemetry.latitude],
        zoom: Math.max(mapRef.current.getZoom(), 5.2),
        speed: 1.4,
        essential: true,
      });
    }
  }, [selectedFlight?.id]);

  // Reset view to global overview
  const handleResetView = () => {
    if (!mapRef.current) return;
    mapRef.current.flyTo({
      center: [-35, 38],
      zoom: 2.8,
      pitch: 0,
      bearing: 0,
      speed: 1.2,
      essential: true,
    });
  };

  return (
    <div className="relative w-full h-full overflow-hidden bg-[#060A13]">
      {/* Map Container */}
      <div ref={mapContainer} className="w-full h-full" />

      {/* Radar Sweep Effect Overlay */}
      {radarSweeps && (
        <div className="absolute inset-0 pointer-events-none opacity-20 overflow-hidden">
          <div className="absolute -top-[50%] -left-[50%] w-[200%] h-[200%] bg-[radial-gradient(circle_at_center,transparent_45%,rgba(0,229,255,0.06)_46%,transparent_47%)] animate-[radar-sweep_12s_linear_infinite]" />
          <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(255,255,255,0.015)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.015)_1px,transparent_1px)] bg-[size:40px_40px]" />
        </div>
      )}

      {/* Tactical Map HUD Controls (Top Left & Top Right) */}
      <div className="absolute top-3 left-3 z-10 flex items-center gap-2">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/85 border border-slate-800/90 backdrop-blur-md shadow-lg text-xs font-mono text-slate-300">
          <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
          <span className="font-semibold text-slate-100">AIRSPACE RADAR</span>
          <span className="text-slate-500">|</span>
          <span className="text-cyan-400 font-bold">{flights.length}</span>
          <span className="text-slate-400">TARGETS</span>
        </div>
      </div>

      {/* Map Quick View Buttons (Right Side) */}
      <div className="absolute top-3 right-3 z-10 flex flex-col gap-2">
        <button
          onClick={handleResetView}
          title="Reset Global View"
          className="p-2 rounded-lg bg-slate-900/85 hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-cyan-400 transition-colors shadow-lg backdrop-blur-md"
        >
          <Maximize2 className="w-4 h-4" />
        </button>
        {selectedFlight && (
          <button
            onClick={handleFlyToSelected}
            title="Focus on Selected Aircraft"
            className="p-2 rounded-lg bg-cyan-950/80 hover:bg-cyan-900 border border-cyan-500/50 text-cyan-400 transition-colors shadow-lg backdrop-blur-md animate-pulse"
          >
            <Compass className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Tactical Telemetry Ribbon (Bottom Left) */}
      <div className="absolute bottom-3 left-3 z-10 hidden sm:flex items-center gap-3 px-3 py-1 rounded bg-slate-950/80 border border-slate-800/80 backdrop-blur-md text-[11px] font-mono text-slate-400">
        <div>
          LAT/LON:{' '}
          <span className="text-slate-200">
            {cursorCoords ? `${cursorCoords[1]}°, ${cursorCoords[0]}°` : '0.000°, 0.000°'}
          </span>
        </div>
        <span className="text-slate-600">|</span>
        <div>
          ZOOM: <span className="text-slate-200">{mapZoom}x</span>
        </div>
        <span className="text-slate-600">|</span>
        <div>
          HDG: <span className="text-slate-200">{mapBearing}°</span>
        </div>
        <span className="text-slate-600">|</span>
        <div className="flex items-center gap-1.5 text-cyan-400">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
          <span>LIVE ADS-B UNVERIFIED</span>
        </div>
      </div>
    </div>
  );
};
