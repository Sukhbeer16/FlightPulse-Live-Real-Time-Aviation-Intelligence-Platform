// ─────────────────────────────────────────────────────────
// FlightPulse Live — Lazy Loaded 3D Globe Wrapper
// Keeps 3D Three.js bundle separated until explicitly requested
// ─────────────────────────────────────────────────────────

import React, { Suspense, lazy } from 'react';
import { Loader2, Globe } from 'lucide-react';
import type { FlightTrack } from '../../types';

const EarthGlobe3D = lazy(() => import('./EarthGlobe3D'));

interface GlobeLazyWrapperProps {
  flights: FlightTrack[];
  selectedFlight: FlightTrack | null;
  onSelectFlight: (flight: FlightTrack | null) => void;
}

export const GlobeLazyWrapper: React.FC<GlobeLazyWrapperProps> = (props) => {
  return (
    <Suspense
      fallback={
        <div className="w-full h-full bg-[#050811] flex flex-col items-center justify-center text-slate-400 font-mono gap-3 select-none">
          <div className="relative flex items-center justify-center">
            <div className="w-16 h-16 rounded-full border-2 border-cyan-500/20 border-t-cyan-400 animate-spin" />
            <Globe className="w-7 h-7 text-cyan-400 absolute animate-pulse" />
          </div>
          <div className="text-center">
            <span className="text-xs text-slate-200 tracking-wider font-bold">
              INITIALIZING THREE.JS 3D ORBITAL GLOBE...
            </span>
            <p className="text-[10px] text-slate-500 mt-1">
              Generating WebGL planetary mesh &amp; Great Circle flight arcs
            </p>
          </div>
        </div>
      }
    >
      <EarthGlobe3D {...props} />
    </Suspense>
  );
};
