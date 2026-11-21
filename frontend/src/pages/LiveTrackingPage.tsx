// ─────────────────────────────────────────────────────────
// FlightPulse Live — PRIMARY SCREEN: Live Flight Tracker
// MapLibre tactical operations center with 3D Globe toggle & intelligence drawer
// ─────────────────────────────────────────────────────────

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Globe,
  Map as MapIcon,
  Play,
  Pause,
  FastForward,
  Filter,
  Search,
  Eye,
  EyeOff,
  Layers,
  Radio,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { MapLibreTracker } from '../features/tracker/MapLibreTracker';
import { GlobeLazyWrapper } from '../features/globe/GlobeLazyWrapper';
import { FlightSearchFilter } from '../features/tracker/FlightSearchFilter';
import { FlightRosterPanel } from '../features/tracker/FlightRosterPanel';
import { FlightDetailDrawer } from '../features/flights/FlightDetailDrawer';
import {
  fetchFlights,
  fetchHistoricalFlights,
  fetchLiveFlights,
  mapLiveStatesToFlightTracks,
  stepAviationSimulation,
  setSimulationSpeed,
  getSimulationSpeed,
  filterFlights,
  isUsingLiveBackend,
  setUseLiveBackend,
} from '../services/flightsService';
import type { FlightTrack, TrackerFilterState } from '../types';

export const LiveTrackingPage: React.FC = () => {
  const [flights, setFlights] = useState<FlightTrack[]>([]);
  const [selectedFlight, setSelectedFlight] = useState<FlightTrack | null>(null);
  const [isRosterOpen, setIsRosterOpen] = useState(true);
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d');
  const [simSpeed, setSimSpeed] = useState<number>(1);
  const [dataSource, setDataSource] = useState<
    'demo' | 'historical_fastapi' | 'live_fastapi' | 'live_unavailable'
  >('historical_fastapi');
  const [liveUnavailable, setLiveUnavailable] = useState<string | null>(null);
  const [sourceStamp, setSourceStamp] = useState('');
  const [loading, setLoading] = useState(true);

  // Filter state
  const [filters, setFilters] = useState<TrackerFilterState>({
    searchQuery: '',
    selectedAirline: 'all',
    selectedAirport: 'all',
    delayFilter: 'all',
    riskFilter: 'all',
    statusFilter: 'all',
    altitudeRange: [0, 50000],
    showRoutes: true,
    showLabels: true,
    radarSweeps: true,
    viewMode: '2d',
  });

  const [attempt, setAttempt] = useState(0);
  // Initial load
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setLiveUnavailable(null);
    fetchHistoricalFlights({ page: 1, pageSize: 50 }).then(({ flights: data }) => {
      if (mounted) {
        setFlights(data);
        setDataSource('historical_fastapi');
        setLoading(false);
        setSelectedFlight(data[0] ?? null);
      }
    }).catch((error) => {
      if (mounted) {
        setLiveUnavailable(error instanceof Error ? error.message : "Historical request failed");
        setLoading(false);
      }
    });
    return () => {
      mounted = false;
    };
  }, [attempt]);

  // Periodic simulation tick loop (smooth aircraft progression)
  useEffect(() => {
    const interval = setInterval(() => {
      if (dataSource === 'demo') {
        const updated = stepAviationSimulation(2);
        setFlights([...updated]);

        // Keep selected flight in sync with updated telemetry
        setSelectedFlight((current) => {
          if (!current) return null;
          const match = updated.find((f) => f.id === current.id);
          return match || current;
        });
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [dataSource]);

  useEffect(() => {
    if (dataSource !== 'live_fastapi') return;
    let active = true;
    const timer = window.setInterval(async () => {
      const update = await fetchLiveFlights();
      if (!active) return;
      if (update.unavailable) {
        setFlights([]);
        setSelectedFlight(null);
        setLiveUnavailable(update.unavailable);
        setDataSource('live_unavailable');
        return;
      }
      setSourceStamp(new Date(update.sourceTime*1000).toISOString() + (update.cached ? ' (cached)' : ' (fresh response)'));
      const next = mapLiveStatesToFlightTracks(update.states, update.sourceTime);
      setFlights(next);
      setSelectedFlight(current => next.find(item => item.id === current?.id) ?? null);
    }, 120000);
    return () => { active = false; window.clearInterval(timer); };
  }, [dataSource]);

  // Handle simulation speed toggles
  const handleSpeedChange = (speed: number) => {
    setSimSpeed(speed);
    setSimulationSpeed(speed);
  };

  // Filter flights
  const filteredFlights = useMemo(() => {
    return filterFlights(flights, filters);
  }, [flights, filters]);

  const handleUpdateFilter = (updates: Partial<TrackerFilterState>) => {
    setFilters((prev) => ({ ...prev, ...updates }));
  };

  // Toggle backend live vs demo
  const handleToggleBackend = async () => {
    setLoading(true);
    if (dataSource === 'live_fastapi' || dataSource === 'live_unavailable') {
      try {
        const historical = await fetchHistoricalFlights({ page: 1, pageSize: 50 });
        setFlights(historical.flights);
        setDataSource('historical_fastapi');
        setLiveUnavailable(null);
        setSelectedFlight(historical.flights[0] ?? null);
      } catch (error) {
        setDataSource('historical_fastapi');
        setFlights([]);
        setSelectedFlight(null);
        setLiveUnavailable(error instanceof Error ? error.message : 'Historical API unavailable.');
      }
      setLoading(false);
      return;
    }
    const live = await fetchLiveFlights();
    if (live.unavailable) {
      setFlights([]);
      setSelectedFlight(null);
      setDataSource('live_unavailable');
      setLiveUnavailable(live.unavailable);
    } else {
      setSourceStamp(new Date(live.sourceTime*1000).toISOString() + (live.cached ? ' (cached)' : ' (fresh response)'));
      setFlights(mapLiveStatesToFlightTracks(live.states, live.sourceTime));
      setDataSource('live_fastapi');
      setLiveUnavailable(null);
      setSelectedFlight(null);
    }
    setLoading(false);
  };

  return (
    <div className="relative w-full h-[calc(100vh-64px)] overflow-hidden bg-[#060A13]">
      {/* Primary Map or 3D Globe */}
      <div className="absolute inset-0">
        {viewMode === '2d' ? (
          <MapLibreTracker
            flights={filteredFlights}
            selectedFlight={selectedFlight}
            onSelectFlight={(flight) => setSelectedFlight(flight)}
            showRoutes={filters.showRoutes}
            showLabels={filters.showLabels}
            radarSweeps={filters.radarSweeps}
          />
        ) : (
          <GlobeLazyWrapper
            flights={filteredFlights}
            selectedFlight={selectedFlight}
            onSelectFlight={(flight) => setSelectedFlight(flight)}
          />
        )}
      </div>

      {dataSource === 'live_fastapi' && <p className="absolute bottom-12 left-3 z-20 bg-slate-950/90 p-2 text-xs text-cyan-300">OpenSky ? {sourceStamp} ? {flights.length} aircraft with positions</p>}
      {(liveUnavailable || loading) && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-30 px-3 py-2 rounded-lg border border-slate-800 bg-slate-950/90 text-xs font-mono text-slate-300">
          {loading
            ? 'LOADING BACKEND DATA…'
            : `REQUEST FAILED — ${liveUnavailable}`}
          {!loading && dataSource === 'historical_fastapi' && <button className="ml-2 underline" onClick={() => setAttempt(value => value + 1)}>Retry historical data</button>}
        </div>
      )}

      {/* Floating Tactical Operations Bar (Top Center) */}
      <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 flex items-center gap-1.5 p-1 rounded-xl bg-slate-950/85 border border-slate-800/90 shadow-2xl backdrop-blur-xl text-xs font-mono">
        {/* 2D vs 3D View Switcher */}
        <div className="flex items-center bg-slate-900/80 rounded-lg p-0.5 border border-slate-800/60">
          <button
            onClick={() => setViewMode('2d')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-bold transition-colors ${
              viewMode === '2d'
                ? 'bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/20'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <MapIcon className="w-3.5 h-3.5" />
            <span>2D RADAR</span>
          </button>
          <button
            onClick={() => setViewMode('3d')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-bold transition-colors ${
              viewMode === '3d'
                ? 'bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/20'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Globe className="w-3.5 h-3.5" />
            <span>3D GLOBE</span>
          </button>
        </div>

        <div className="h-4 w-px bg-slate-800 mx-1 hidden sm:block" />

        {/* Simulation Speed Controls */}
        <div className={dataSource === 'demo' ? "hidden sm:flex items-center gap-1" : "hidden"}>
          <button
            onClick={() => handleSpeedChange(simSpeed === 0 ? 1 : 0)}
            title={simSpeed === 0 ? 'Resume Simulation' : 'Pause Simulation'}
            className={`p-1.5 rounded-lg border transition-colors ${
              simSpeed === 0
                ? 'bg-amber-950/70 border-amber-500/50 text-amber-300'
                : 'bg-slate-900/80 border-slate-800 text-slate-300 hover:text-cyan-400'
            }`}
          >
            {simSpeed === 0 ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
          </button>

          {[1, 2, 5].map((spd) => (
            <button
              key={spd}
              onClick={() => handleSpeedChange(spd)}
              className={`px-2 py-1 rounded text-[11px] font-bold border transition-colors ${
                simSpeed === spd
                  ? 'bg-cyan-950/80 border-cyan-500/60 text-cyan-300'
                  : 'bg-slate-900/60 border-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {spd}x
            </button>
          ))}
        </div>

        <div className="h-4 w-px bg-slate-800 mx-1 hidden md:block" />

        {/* Search & Filter Drawer Toggle */}
        <button
          onClick={() => setIsFilterOpen((prev) => !prev)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border transition-colors ${
            isFilterOpen || filters.searchQuery || filters.selectedAirline !== 'all'
              ? 'bg-cyan-950/80 border-cyan-500/60 text-cyan-300'
              : 'bg-slate-900/80 border-slate-800 text-slate-300 hover:text-slate-100'
          }`}
        >
          <Search className="w-3.5 h-3.5" />
          <span>SEARCH &amp; FILTER</span>
        </button>

        {/* Mode Tag (DEMO vs LIVE FASTAPI) */}
        <button
          disabled={loading} onClick={handleToggleBackend}
          title="Toggle between historical replay and live OpenSky"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-900/90 hover:bg-slate-800 border border-slate-800 text-[10px] text-slate-300 transition-colors"
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              dataSource === 'live_fastapi'
                ? 'bg-emerald-400'
                : dataSource === 'live_unavailable'
                ? 'bg-red-400'
                : 'bg-amber-400 animate-pulse'
            }`}
          />
          <span>
            {dataSource === 'live_fastapi'
              ? 'LIVE OPENSKY'
              : dataSource === 'live_unavailable'
              ? 'LIVE UNAVAILABLE'
              : dataSource === 'historical_fastapi'
              ? 'HISTORICAL FASTAPI'
              : 'DEMO SIMULATION'}
          </span>
        </button>
      </div>

      {/* Collapsible Search & Filter Dropdown overlay */}
      {isFilterOpen && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-20 w-[92%] sm:w-[540px]">
          <FlightSearchFilter
            filterState={filters}
            onChangeFilter={handleUpdateFilter}
            totalFlightsCount={flights.length}
            filteredCount={filteredFlights.length}
          />
        </div>
      )}

      {/* Tactical Flight Roster Side Panel (Left) */}
      <FlightRosterPanel
        flights={filteredFlights}
        selectedFlight={selectedFlight}
        onSelectFlight={(flight) => {
          setSelectedFlight(flight);
        }}
        isOpen={isRosterOpen}
        onToggleOpen={() => setIsRosterOpen((prev) => !prev)}
      />

      {/* Selected Flight Intelligence Drawer (Right) */}
      <FlightDetailDrawer
        flight={selectedFlight}
        onClose={() => setSelectedFlight(null)}
      />
    </div>
  );
};
