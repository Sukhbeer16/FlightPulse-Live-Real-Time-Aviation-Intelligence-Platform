// ─────────────────────────────────────────────────────────
// FlightPulse Live — Flight Search & Aviation Filter Controls
// ─────────────────────────────────────────────────────────

import React from 'react';
import { Search, X, Filter, AlertTriangle, Clock } from 'lucide-react';
import type { TrackerFilterState, DelayCategory, RiskLevel } from '../../types';
import { AIRLINES } from '../../data/aviationData';

interface FlightSearchFilterProps {
  filterState: TrackerFilterState;
  onChangeFilter: (updates: Partial<TrackerFilterState>) => void;
  totalFlightsCount: number;
  filteredCount: number;
}

export const FlightSearchFilter: React.FC<FlightSearchFilterProps> = ({
  filterState,
  onChangeFilter,
  totalFlightsCount,
  filteredCount,
}) => {
  return (
    <div className="flex flex-col gap-2.5 p-3 rounded-xl bg-slate-900/90 border border-slate-800/90 backdrop-blur-md shadow-xl text-slate-200">
      {/* Search Input Bar */}
      <div className="relative flex items-center">
        <Search className="absolute left-3 w-4 h-4 text-slate-400" />
        <input
          type="text"
          value={filterState.searchQuery}
          onChange={(e) => onChangeFilter({ searchQuery: e.target.value })}
          placeholder="Search flight, callsign, airline, origin, destination..."
          className="w-full pl-9 pr-8 py-2 rounded-lg bg-slate-950/80 border border-slate-800 text-xs font-mono text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500/60 focus:ring-1 focus:ring-cyan-500/30 transition-all"
        />
        {filterState.searchQuery && (
          <button
            onClick={() => onChangeFilter({ searchQuery: '' })}
            className="absolute right-2.5 p-0.5 rounded text-slate-400 hover:text-slate-200"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Filter Row */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {/* Airline Selector */}
        <div className="flex-1 min-w-[130px]">
          <select
            value={filterState.selectedAirline}
            onChange={(e) => onChangeFilter({ selectedAirline: e.target.value })}
            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950/80 border border-slate-800 text-xs font-mono text-slate-300 focus:outline-none focus:border-cyan-500/50"
          >
            <option value="all">All Airlines</option>
            {Object.entries(AIRLINES).map(([code, airline]) => (
              <option key={code} value={airline.code}>
                {airline.name} ({airline.code})
              </option>
            ))}
          </select>
        </div>

        {/* Delay Category Selector */}
        <div className="flex-1 min-w-[120px]">
          <select
            value={filterState.delayFilter}
            onChange={(e) =>
              onChangeFilter({ delayFilter: e.target.value as DelayCategory | 'all' })
            }
            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950/80 border border-slate-800 text-xs font-mono text-slate-300 focus:outline-none focus:border-cyan-500/50"
          >
            <option value="all">All Punctuality</option>
            <option value="on_time">On Time (&lt;15m)</option>
            <option value="minor">Minor Delay (15-30m)</option>
            <option value="moderate">Moderate Delay (30-60m)</option>
            <option value="severe">Severe Delay (&gt;60m)</option>
          </select>
        </div>

        {/* Risk Level Selector */}
        <div className="flex-1 min-w-[120px]">
          <select
            value={filterState.riskFilter}
            onChange={(e) =>
              onChangeFilter({ riskFilter: e.target.value as RiskLevel | 'all' })
            }
            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950/80 border border-slate-800 text-xs font-mono text-slate-300 focus:outline-none focus:border-cyan-500/50"
          >
            <option value="all">All Risk Tiers</option>
            <option value="minimal">Minimal Risk</option>
            <option value="elevated">Elevated Risk</option>
            <option value="high">High Risk</option>
            <option value="critical">Critical Anomaly</option>
          </select>
        </div>
      </div>

      {/* Filter Status Badge Count */}
      <div className="flex items-center justify-between pt-1 border-t border-slate-800/80 text-[11px] font-mono text-slate-400">
        <div className="flex items-center gap-2">
          <span>
            SHOWING <strong className="text-cyan-400 font-semibold">{filteredCount}</strong> OF{' '}
            <strong className="text-slate-200">{totalFlightsCount}</strong> FLIGHTS
          </span>
        </div>

        {(filterState.searchQuery ||
          filterState.selectedAirline !== 'all' ||
          filterState.delayFilter !== 'all' ||
          filterState.riskFilter !== 'all') && (
          <button
            onClick={() =>
              onChangeFilter({
                searchQuery: '',
                selectedAirline: 'all',
                selectedAirport: 'all',
                delayFilter: 'all',
                riskFilter: 'all',
              })
            }
            className="text-cyan-400 hover:text-cyan-300 hover:underline flex items-center gap-1"
          >
            <X className="w-3 h-3" />
            <span>Reset Filters</span>
          </button>
        )}
      </div>
    </div>
  );
};
