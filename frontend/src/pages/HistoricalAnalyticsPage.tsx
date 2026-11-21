import { HistoricalSearch } from '../features/tracker/HistoricalSearch';
// ─────────────────────────────────────────────────────────
// FlightPulse Live — Historical Aviation Analytics
// BTS historical flight delay patterns, carrier comparisons & trends
// ─────────────────────────────────────────────────────────

import React, { useEffect, useState } from 'react';
import { BarChart3, Database, FileSpreadsheet, TrendingUp } from 'lucide-react';
import {
  DelayTrendChart,
  AirlinePerformanceChart,
  FlightActivityChart,
} from '../components/Charts/Charts';
import { API_ENDPOINTS, apiFetch } from '../services/apiConfig';

export const HistoricalAnalyticsPage: React.FC = () => {
  const [overview, setOverview] = useState<{
    total_flights: number;
    eligible_arrival_records: number;
    delayed_flights: number;
    cancelled_flights: number;
    diverted_flights: number;
    delay_rate: number | null;
  } | null>(null);
  const [status, setStatus] = useState<'loading' | 'available' | 'unavailable'>('loading');
  useEffect(() => {
    apiFetch<{
      data_kind: 'historical_aggregate';
      source_period: string;
      statistics: typeof overview;
    }>(API_ENDPOINTS.analyticsOverview)
      .then((response) => {
        setOverview(response.statistics);
        setStatus('available');
      })
      .catch(() => setStatus('unavailable'));
  }, []);
  return (
    <div className="relative w-full h-[calc(100vh-64px)] overflow-y-auto p-4 md:p-6 bg-[#070A12] max-w-7xl mx-auto space-y-6 text-slate-100">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-cyan-400" />
            <h1 className="font-mono text-2xl font-black tracking-wider text-slate-100">
              HISTORICAL BTS AVIATION ANALYTICS
            </h1>
          </div>
          <p className="text-xs text-slate-400 font-sans mt-1">
            Bureau of Transportation Statistics (BTS) baseline records, PySpark pipeline telemetry &amp; carrier rankings
          </p>
        </div>

        <div className="flex items-center gap-2 font-mono text-xs">
          <span className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-slate-300">
            BTS HISTORICAL API:{' '}
            <strong className={status === 'available' ? 'text-cyan-400' : 'text-amber-400'}>
              {status === 'available' ? 'CONNECTED' : status === 'loading' ? 'CHECKING' : 'UNAVAILABLE'}
            </strong>
          </span>
        </div>
      </div>

      {overview && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {[
            ['JAN 2024 BTS RECORDS', overview.total_flights],
            ['ELIGIBLE ARRIVAL', overview.eligible_arrival_records],
            ['DELAYED >15M', overview.delayed_flights],
            ['CANCELLED', overview.cancelled_flights],
            ['DIVERTED', overview.diverted_flights],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
              <div className="text-[10px] font-mono text-slate-500">{label}</div>
              <div className="mt-1 text-xl font-mono font-bold text-cyan-400">
                {Number(value).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      )}

      <HistoricalSearch />
      {/* Analytics Charts Grid */}
      <div className="space-y-6">
        <DelayTrendChart />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <AirlinePerformanceChart />
          <FlightActivityChart />
        </div>
      </div>
    </div>
  );
};
export default HistoricalAnalyticsPage;
