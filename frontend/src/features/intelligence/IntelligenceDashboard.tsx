import { AirlinePerformanceChart } from '../../components/Charts/Charts';
import { API_ENDPOINTS, apiFetch } from '../../services/apiConfig';
// ─────────────────────────────────────────────────────────
// FlightPulse Live — Aviation Intelligence Dashboard
// Global operational analytics, punctuality metrics & delay trends
// ─────────────────────────────────────────────────────────

import React, { useEffect, useRef } from 'react';
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
} from 'recharts';
import {
  Activity,
  AlertTriangle,
  Clock,
  Plane,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  Cpu,
  Radio,
  FileText,
} from 'lucide-react';
import type { FlightTrack, AviationAlert } from '../../types';
import {
  DEMO_DELAY_TREND,
  DEMO_AIRLINE_PERFORMANCE,
  DEMO_FLIGHT_ACTIVITY,
} from '../../data/mockData';
import { playBootSequence } from '../../animations/gsapAnimations';
import { SeverityBadge } from '../../components/AviationBadge';

interface IntelligenceDashboardProps {
  flights: FlightTrack[];
  alerts: AviationAlert[];
  onSelectFlight: (flight: FlightTrack) => void;
}

export const IntelligenceDashboard: React.FC<IntelligenceDashboardProps> = ({
  flights,
  alerts,
  onSelectFlight,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);

  // Trigger GSAP Boot animation on mount
  useEffect(() => {
    if (containerRef.current) {
      playBootSequence('.intelligence-dashboard-root');
    }
  }, []);

  // Compute live KPIs
  const [aggregate, setAggregate] = React.useState<{total_flights:number; delayed_flights:number; delay_rate:number|null} | null>(null);
  useEffect(() => {
    apiFetch<{statistics:NonNullable<typeof aggregate>}>(API_ENDPOINTS.analyticsOverview)
      .then(r=>setAggregate(r.statistics)).catch(()=>setAggregate(null));
  }, []);
  return (
    <div
      ref={containerRef}
      className="intelligence-dashboard-root flex-1 p-4 md:p-6 space-y-6 max-w-7xl mx-auto overflow-y-auto text-slate-100"
    >
      {/* Header Banner */}
      <div data-gsap="tactical-header" className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-mono text-2xl font-black tracking-wider text-slate-100">
              AVIATION INTELLIGENCE OPERATIONS
            </h1>
            <span className="px-2 py-0.5 rounded bg-cyan-950/60 border border-cyan-500/40 text-cyan-400 font-mono text-xs font-bold">
              SYSTEM LEVEL
            </span>
          </div>
          <p className="text-xs text-slate-400 font-sans mt-1">
            Historical operating metrics and flight assessments
          </p>
        </div>

        <div className="flex items-center gap-2 font-mono text-xs text-slate-400">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>HISTORICAL &amp; MODEL SERVICES</span>
        </div>
      </div>

      {/* Top 5 Primary KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3.5">
        {/* Monitored Flights */}
        <div data-gsap="hud-panel" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800/80 backdrop-blur-md shadow-lg">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>HISTORICAL FLIGHTS</span>
            <Plane className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-2xl font-mono font-extrabold text-slate-100">
            {aggregate?.total_flights.toLocaleString() ?? 'Unavailable'}
          </div>
          <div className="flex items-center gap-1 text-[11px] font-mono text-emerald-400 mt-1">
            <TrendingUp className="w-3.5 h-3.5" />
            <span>January 2024 BTS</span>
          </div>
        </div>

        {/* Delayed Flights */}
        <div data-gsap="hud-panel" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800/80 backdrop-blur-md shadow-lg">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>DELAYED (&gt;15M)</span>
            <Clock className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-mono font-extrabold text-amber-400">
            {aggregate?.delayed_flights.toLocaleString() ?? 'Unavailable'}
          </div>
          <div className="text-[11px] font-mono text-slate-400 mt-1">
            January 2024 BTS
          </div>
        </div>

        {/* High Risk Flights */}
        <div data-gsap="hud-panel" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800/80 backdrop-blur-md shadow-lg">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>HIGH-RISK TIER</span>
            <AlertTriangle className="w-4 h-4 text-orange-400" />
          </div>
          <div className="text-2xl font-mono font-extrabold text-orange-400">
            Unevaluated
          </div>
          <div className="text-[11px] font-mono text-slate-400 mt-1">
            Predictive model score &gt; 70
          </div>
        </div>

        {/* Active Anomalies */}
        <div data-gsap="hud-panel" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800/80 backdrop-blur-md shadow-lg">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>ACTIVE ANOMALIES</span>
            <ShieldAlert className="w-4 h-4 text-red-400" />
          </div>
          <div className="text-2xl font-mono font-extrabold text-red-400">
            Unevaluated
          </div>
          <div className="text-[11px] font-mono text-red-400 mt-1">
            Statistical records only
          </div>
        </div>

        {/* Punctuality Index */}
        <div data-gsap="hud-panel" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800/80 backdrop-blur-md shadow-lg col-span-2 lg:col-span-1">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>ON-TIME RATE</span>
            <Activity className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-mono font-extrabold text-emerald-400">
            {aggregate?.delay_rate == null ? "Unavailable" : ((1-aggregate.delay_rate)*100).toFixed(1)+"%"}
          </div>
          <div className="text-[11px] font-mono text-slate-400 mt-1">
            Eligible BTS arrivals
          </div>
        </div>
      </div>

      {/* Analytics Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Chart 1: Airspace Flight Activity (Departures vs Arrivals) */}
        <div data-gsap="hud-panel" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800/80 backdrop-blur-md shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-mono text-xs font-bold text-slate-200 tracking-wider flex items-center gap-2">
              <Plane className="w-4 h-4 text-cyan-400" />
              <span>HOURLY AIRSPACE OPERATIONS (DEPARTURES VS ARRIVALS)</span>
            </h3>
            <span className="text-[10px] font-mono text-slate-500">SAMPLE DATA</span>
          </div>

          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={DEMO_FLIGHT_ACTIVITY} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="depGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00E5FF" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#00E5FF" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="arrGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#38BDF8" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#38BDF8" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" />
                <XAxis dataKey="date" stroke="#64748B" fontSize={10} fontStyle="mono" />
                <YAxis stroke="#64748B" fontSize={10} fontStyle="mono" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0A1120',
                    border: '1px solid #1E293B',
                    borderRadius: '8px',
                    fontFamily: 'monospace',
                    fontSize: '11px',
                  }}
                />
                <Area type="monotone" dataKey="departures" stroke="#00E5FF" strokeWidth={2} fillOpacity={1} fill="url(#depGradient)" name="Departures" />
                <Area type="monotone" dataKey="arrivals" stroke="#38BDF8" strokeWidth={2} fillOpacity={1} fill="url(#arrGradient)" name="Arrivals" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <AirlinePerformanceChart />
      </div>

      {/* Bottom Section: Recent Aviation Events & Active High-Risk Flights */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Aviation Events Feed */}
        <div data-gsap="hud-panel" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800/80 backdrop-blur-md shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-mono text-xs font-bold text-slate-200 tracking-wider flex items-center gap-2">
              <Radio className="w-4 h-4 text-cyan-400" />
              <span>ACTIVE INTELLIGENCE ALERTS &amp; EVENTS</span>
            </h3>
            <span className="text-[10px] font-mono text-cyan-400">● DEMONSTRATION ALERT LOG</span>
          </div>

          <div className="space-y-2.5 max-h-80 overflow-y-auto pr-1">
            {alerts.map((alert) => (
              <div
                key={alert.id}
                className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/70 hover:border-slate-700 transition-all flex flex-col gap-1.5"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={alert.severity} />
                    <span className="font-mono font-bold text-xs text-slate-200">
                      {alert.callsign}
                    </span>
                    <span className="text-[11px] font-mono text-slate-400">
                      ({alert.airline})
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-500">
                    {alert.detectionTime}
                  </span>
                </div>

                <h4 className="font-mono text-xs font-semibold text-slate-200">
                  {alert.title}
                </h4>
                <p className="text-[11px] font-sans text-slate-400 leading-relaxed">
                  {alert.explanation}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* Monitored Flight Roster Quick List */}
        <div data-gsap="hud-panel" className="p-4 rounded-xl bg-slate-900/70 border border-slate-800/80 backdrop-blur-md shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-mono text-xs font-bold text-slate-200 tracking-wider flex items-center gap-2">
              <Cpu className="w-4 h-4 text-purple-400" />
              <span>HISTORICAL FLIGHT RECORDS</span>
            </h3>
            <span className="text-[10px] font-mono text-slate-500">CLICK TO INSPECT</span>
          </div>

          <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
            {flights.slice(0, 7).map((flight) => (
              <div
                key={flight.id}
                onClick={() => onSelectFlight(flight)}
                className="p-2.5 rounded-lg bg-slate-950/60 hover:bg-slate-900/80 border border-slate-800/70 cursor-pointer transition-all flex items-center justify-between"
              >
                <div className="flex items-center gap-3">
                  <div
                    className="w-1.5 h-8 rounded-full"
                    style={{ backgroundColor: flight.airline.color }}
                  />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-xs text-slate-100">
                        {flight.callsign}
                      </span>
                      <span className="text-[10px] font-mono text-slate-400">
                        {flight.origin.btsCode ?? flight.origin.iata} ➔ {flight.destination.btsCode ?? flight.destination.iata}
                      </span>
                    </div>
                    <div className="text-[10px] font-mono text-slate-500">
                      Historical • {flight.telemetry.groundSpeedKts} kts • {flight.aircraft.model}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span
                    className={`font-mono text-xs font-bold px-2 py-0.5 rounded border ${
                      flight.intelligence.riskScore > 70
                        ? 'bg-red-950/50 border-red-500/40 text-red-400'
                        : flight.intelligence.riskScore > 30
                        ? 'bg-amber-950/40 border-amber-500/40 text-amber-300'
                        : 'bg-emerald-950/40 border-emerald-500/40 text-emerald-400'
                    }`}
                  >
                    BTS
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
