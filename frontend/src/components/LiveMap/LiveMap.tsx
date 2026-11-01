import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Plane, Signal, Gauge, TrendingUp, FlaskConical } from 'lucide-react';
import { slideInRight } from '../../animations/variants';
import type { Aircraft } from '../../types';

interface LiveMapProps {
  aircraft: Aircraft[];
}

export function LiveMap({ aircraft }: LiveMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapRef = useRef<any>(null);
  const [selectedAircraft, setSelectedAircraft] = useState<Aircraft | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const [mapError, setMapError] = useState(false);

  useEffect(() => {
    if (!mapContainer.current) return;
    if (mapRef.current) return;

    // Dynamically import maplibre-gl to avoid SSR issues
    import('maplibre-gl').then(({ Map, NavigationControl }) => {
      if (!mapContainer.current) return;

      const map = new Map({
        container: mapContainer.current,
        style: {
          version: 8,
          sources: {
            'osm-tiles': {
              type: 'raster',
              tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
              tileSize: 256,
              attribution: '© OpenStreetMap contributors',
            },
          },
          layers: [
            {
              id: 'background',
              type: 'background',
              paint: { 'background-color': '#0A1420' },
            },
            {
              id: 'osm-tiles',
              type: 'raster',
              source: 'osm-tiles',
              paint: {
                'raster-opacity': 0.18,
                'raster-brightness-min': 0,
                'raster-saturation': -1,
              },
            },
          ],

        },
        center: [-40, 35],
        zoom: 2.5,
        attributionControl: false,
      });

      map.addControl(new NavigationControl({ showCompass: false }), 'bottom-right');

      map.on('load', () => {
        setMapLoaded(true);

        // Add aircraft markers as custom HTML elements
        aircraft.forEach((ac) => {
          if (ac.latitude == null || ac.longitude == null) return;
          addAircraftMarker(map, ac, setSelectedAircraft);
        });
      });

      map.on('error', () => setMapError(true));

      mapRef.current = map;
    }).catch(() => setMapError(true));

    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Add new markers when aircraft list changes
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return;
    // Re-adding markers for demo — in production, diff and update
    aircraft.forEach((ac) => {
      if (ac.latitude == null || ac.longitude == null) return;
      addAircraftMarker(mapRef.current, ac, setSelectedAircraft);
    });
  }, [aircraft, mapLoaded]);

  return (
    <div className="relative w-full h-full rounded-fp overflow-hidden" style={{ minHeight: 420 }}>
      {/* Map container */}
      <div ref={mapContainer} className="absolute inset-0 rounded-fp" />

      {/* Loading state */}
      {!mapLoaded && !mapError && (
        <div className="absolute inset-0 flex items-center justify-center rounded-fp"
          style={{ background: '#0A1420' }}>
          <div className="flex flex-col items-center gap-3">
            <div className="relative h-8 w-8">
              <div className="absolute inset-0 rounded-full border border-[#25BCEB] opacity-25" />
              <div
                className="absolute inset-0 rounded-full border-t border-[#25BCEB] animate-spin"
              />
            </div>
            <span className="text-[11px] tracking-wider" style={{ color: '#475569' }}>
              INITIALISING MAP
            </span>
          </div>
        </div>
      )}

      {/* Error state */}
      {mapError && (
        <div className="absolute inset-0 flex items-center justify-center rounded-fp"
          style={{ background: '#0A1420', border: '1px solid rgba(241,245,249,0.07)' }}>
          <div className="text-center">
            <Plane size={32} style={{ color: '#25BCEB', margin: '0 auto 12px' }} />
            <div className="text-[13px] font-medium mb-1" style={{ color: '#F1F5F9' }}>
              Map unavailable
            </div>
            <div className="text-[11px]" style={{ color: '#475569' }}>
              MapLibre GL failed to load. Check network connectivity.
            </div>
          </div>
        </div>
      )}

      {/* DEMO badge */}
      <div
        className="absolute top-3 left-3 flex items-center gap-1.5 rounded px-2 py-1 z-10"
        style={{ background: 'rgba(8,13,24,0.85)', border: '1px solid rgba(37,188,235,0.2)' }}
      >
        <FlaskConical size={10} style={{ color: '#25BCEB' }} />
        <span className="text-[10px] font-semibold tracking-wider" style={{ color: '#25BCEB' }}>
          DEMO POSITIONS — NOT LIVE
        </span>
      </div>

      {/* Aircraft count overlay */}
      {mapLoaded && (
        <div
          className="absolute bottom-3 left-3 rounded-lg px-3 py-2 z-10"
          style={{ background: 'rgba(8,13,24,0.85)', border: '1px solid rgba(241,245,249,0.1)' }}
        >
          <div className="flex items-center gap-2">
            <Plane size={12} style={{ color: '#25BCEB' }} />
            <span className="text-[11px] font-medium" style={{ color: '#F1F5F9' }}>
              {aircraft.length} aircraft displayed
            </span>
          </div>
        </div>
      )}

      {/* Aircraft detail panel */}
      <AnimatePresence>
        {selectedAircraft && (
          <motion.div
            key="aircraft-detail"
            variants={slideInRight}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="absolute top-3 right-3 w-72 rounded-fp z-20 overflow-hidden"
            style={{
              background: 'rgba(13,20,32,0.95)',
              border: '1px solid rgba(37,188,235,0.2)',
              backdropFilter: 'blur(16px)',
            }}
          >
            <div
              className="flex items-center justify-between px-4 py-3"
              style={{ borderBottom: '1px solid rgba(241,245,249,0.07)' }}
            >
              <div className="flex items-center gap-2">
                <Plane size={14} style={{ color: '#25BCEB' }} />
                <span className="text-[13px] font-semibold" style={{ color: '#F1F5F9' }}>
                  {selectedAircraft.callsign ?? selectedAircraft.icao24.toUpperCase()}
                </span>
                {selectedAircraft.isDemo && (
                  <span
                    className="rounded px-1 py-0.5 text-[8px] font-bold tracking-wider"
                    style={{ background: 'rgba(37,188,235,0.15)', color: '#25BCEB' }}
                  >
                    DEMO
                  </span>
                )}
              </div>
              <button
                onClick={() => setSelectedAircraft(null)}
                style={{ color: '#475569', background: 'none', border: 'none', cursor: 'pointer' }}
              >
                <X size={14} />
              </button>
            </div>

            <div className="px-4 py-3 grid grid-cols-2 gap-3">
              <DetailItem
                Icon={Signal}
                label="ICAO24"
                value={selectedAircraft.icao24.toUpperCase()}
              />
              <DetailItem
                Icon={Plane}
                label="COUNTRY"
                value={selectedAircraft.originCountry}
              />
              <DetailItem
                Icon={TrendingUp}
                label="ALTITUDE"
                value={
                  selectedAircraft.baroAltitude != null
                    ? `${Math.round(selectedAircraft.baroAltitude).toLocaleString()} m`
                    : 'N/A'
                }
              />
              <DetailItem
                Icon={Gauge}
                label="SPEED"
                value={
                  selectedAircraft.velocity != null
                    ? `${Math.round(selectedAircraft.velocity)} m/s`
                    : 'N/A'
                }
              />
              <DetailItem
                Icon={TrendingUp}
                label="HEADING"
                value={
                  selectedAircraft.trueTrack != null
                    ? `${Math.round(selectedAircraft.trueTrack)}°`
                    : 'N/A'
                }
              />
              <DetailItem
                Icon={Signal}
                label="SQUAWK"
                value={selectedAircraft.squawk ?? 'N/A'}
              />
            </div>

            <div
              className="px-4 py-2.5 flex items-center gap-2"
              style={{ borderTop: '1px solid rgba(241,245,249,0.06)' }}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${selectedAircraft.onGround ? '' : 'animate-pulse-dot'}`}
                style={{ background: selectedAircraft.onGround ? '#475569' : '#22C55E' }}
              />
              <span className="text-[10px]" style={{ color: '#94A3B8' }}>
                {selectedAircraft.onGround ? 'On Ground' : 'Airborne'}
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Detail item helper ────────────────────────

function DetailItem({
  Icon,
  label,
  value,
}: {
  Icon: React.ElementType;
  label: string;
  value: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-1 mb-0.5">
        <Icon size={9} style={{ color: '#475569' }} />
        <span className="text-[9px] font-semibold tracking-wider uppercase" style={{ color: '#475569' }}>
          {label}
        </span>
      </div>
      <div className="text-[12px] font-medium" style={{ color: '#F1F5F9' }}>
        {value}
      </div>
    </div>
  );
}

// ── Aircraft marker helper ────────────────────

function addAircraftMarker(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  map: any,
  ac: Aircraft,
  onSelect: (ac: Aircraft) => void,
) {
  import('maplibre-gl').then(({ Marker }) => {
    const el = document.createElement('div');
    el.style.cssText = `
      width: 20px;
      height: 20px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transform: rotate(${ac.trueTrack ?? 0}deg);
      filter: drop-shadow(0 0 4px rgba(37,188,235,0.5));
    `;
    el.innerHTML = `<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M8 1 L10.5 6 L15 7 L11 10.5 L12 15 L8 13 L4 15 L5 10.5 L1 7 L5.5 6 Z"
        fill="${ac.isDemo ? '#25BCEB' : '#4285F4'}" opacity="0.9"/>
    </svg>`;
    el.addEventListener('click', () => onSelect(ac));

    new Marker({ element: el })
      .setLngLat([ac.longitude!, ac.latitude!])
      .addTo(map);
  });
}
