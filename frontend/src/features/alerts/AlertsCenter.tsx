// ─────────────────────────────────────────────────────────
// FlightPulse Live — Aviation Alerts & Incident Center
// Prioritized operational alerts, anomaly telemetry & rapid map triage
// ─────────────────────────────────────────────────────────

import React, { useState } from 'react';
import {
  ShieldAlert,
  AlertTriangle,
  Radio,
  Search,
  ExternalLink,
  MapPin,
  Clock,
  Filter,
  CheckCircle2,
  XCircle,
} from 'lucide-react';
import type { AviationAlert, FlightTrack } from '../../types';
import { SeverityBadge } from '../../components/AviationBadge';

interface AlertsCenterProps {
  alerts: AviationAlert[];
  flights: FlightTrack[];
  onLocateOnMap: (flightId: string) => void;
}

export const AlertsCenter: React.FC<AlertsCenterProps> = ({
  alerts,
  flights,
  onLocateOnMap,
}) => {
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Filter alerts
  const filteredAlerts = alerts.filter((alert) => {
    if (severityFilter !== 'all' && alert.severity !== severityFilter) {
      return false;
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const match =
        alert.flightNumber.toLowerCase().includes(q) ||
        alert.callsign.toLowerCase().includes(q) ||
        alert.airline.toLowerCase().includes(q) ||
        alert.title.toLowerCase().includes(q) ||
        alert.origin.toLowerCase().includes(q) ||
        alert.destination.toLowerCase().includes(q);
      if (!match) return false;
    }
    return true;
  });

  const criticalCount = alerts.filter((a) => a.severity === 'critical').length;
  const highCount = alerts.filter((a) => a.severity === 'high').length;
  const mediumCount = alerts.filter((a) => a.severity === 'medium').length;

  return (
    <div className="flex-1 p-4 md:p-6 space-y-6 max-w-7xl mx-auto overflow-y-auto text-slate-100">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-6 h-6 text-red-400" />
            <h1 className="font-mono text-2xl font-black tracking-wider text-slate-100">
              TACTICAL ALERTS &amp; ANOMALIES CENTER
            </h1>
          </div>
          <p className="text-xs text-slate-400 font-sans mt-1">
            Real-time automated incident detection, transponder alerts &amp; route anomalies
          </p>
        </div>

        {/* Severity Count Summary */}
        <div className="flex items-center gap-2 font-mono text-xs">
          <span className="px-2.5 py-1 rounded-md bg-red-950/60 border border-red-500/40 text-red-400 font-bold">
            {criticalCount} CRITICAL
          </span>
          <span className="px-2.5 py-1 rounded-md bg-orange-950/60 border border-orange-500/40 text-orange-400 font-bold">
            {highCount} HIGH
          </span>
          <span className="px-2.5 py-1 rounded-md bg-amber-950/60 border border-amber-500/40 text-amber-300 font-bold">
            {mediumCount} MEDIUM
          </span>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 p-3 rounded-xl bg-slate-900/80 border border-slate-800/80 backdrop-blur-md">
        {/* Search Input */}
        <div className="relative w-full sm:w-80">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search alerts by flight, airline, title..."
            className="w-full pl-9 pr-3 py-1.5 rounded-lg bg-slate-950/80 border border-slate-800 text-xs font-mono text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
          />
        </div>

        {/* Severity Filter Buttons */}
        <div className="flex items-center gap-1.5 w-full sm:w-auto overflow-x-auto pb-1 sm:pb-0">
          {['all', 'critical', 'high', 'medium', 'low'].map((sev) => (
            <button
              key={sev}
              onClick={() => setSeverityFilter(sev)}
              className={`px-3 py-1 rounded-lg text-xs font-mono uppercase tracking-wider transition-colors ${
                severityFilter === sev
                  ? 'bg-cyan-500/20 border border-cyan-500/60 text-cyan-300 font-bold'
                  : 'bg-slate-950/60 border border-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {sev}
            </button>
          ))}
        </div>
      </div>

      {/* Alerts List */}
      <div className="space-y-3.5">
        {filteredAlerts.length === 0 ? (
          <div className="p-12 text-center text-slate-500 font-mono text-xs rounded-xl border border-slate-800 bg-slate-900/30">
            No active alerts matching your filter criteria.
          </div>
        ) : (
          filteredAlerts.map((alert) => {
            const associatedFlight = flights.find((f) => f.id === alert.flightId);
            const isCrit = alert.severity === 'critical';

            return (
              <div
                key={alert.id}
                className={`p-4 sm:p-5 rounded-xl border transition-all backdrop-blur-md relative overflow-hidden ${
                  isCrit
                    ? 'bg-red-950/20 border-red-500/50 hover:bg-red-950/30 shadow-[0_0_20px_rgba(239,68,68,0.12)]'
                    : 'bg-slate-900/60 border-slate-800/80 hover:bg-slate-900/90'
                }`}
              >
                {/* Left accent color indicator */}
                <div
                  className={`absolute left-0 top-0 bottom-0 w-1.5 ${
                    isCrit
                      ? 'bg-red-500 animate-pulse'
                      : alert.severity === 'high'
                      ? 'bg-orange-500'
                      : 'bg-amber-500'
                  }`}
                />

                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <SeverityBadge severity={alert.severity} />
                    <span className="font-mono font-bold text-sm text-slate-100 tracking-wider">
                      {alert.callsign}
                    </span>
                    <span className="text-xs font-mono text-slate-400">
                      ({alert.airline} • {alert.flightNumber})
                    </span>
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-800/60 text-slate-300">
                      {alert.origin} ➔ {alert.destination}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 font-mono text-xs text-slate-400">
                    <Clock className="w-3.5 h-3.5 text-slate-500" />
                    <span>{alert.detectionTime}</span>
                  </div>
                </div>

                {/* Alert Title */}
                <h3 className="font-mono text-sm font-bold text-slate-100 mb-1.5">
                  {alert.title}
                </h3>

                {/* Explanation */}
                <p className="text-xs font-sans text-slate-300 leading-relaxed max-w-4xl mb-3">
                  {alert.explanation}
                </p>

                {/* Telemetry and Action Row */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-2.5 border-t border-slate-800/60 text-xs font-mono">
                  {/* Telemetry Snapshot */}
                  <div className="flex items-center gap-4 text-slate-400">
                    {associatedFlight && (
                      <>
                        <span>
                          ALT:{' '}
                          <strong className="text-slate-200">
                            FL{Math.round(associatedFlight.telemetry.altitudeFt / 100)}
                          </strong>
                        </span>
                        <span>
                          SPD:{' '}
                          <strong className="text-slate-200">
                            {associatedFlight.telemetry.groundSpeedKts} kt
                          </strong>
                        </span>
                        <span>
                          SQK:{' '}
                          <strong className="text-slate-200">
                            {associatedFlight.telemetry.squawk}
                          </strong>
                        </span>
                      </>
                    )}
                    <span>
                      RISK SCORE:{' '}
                      <strong className="text-red-400">{alert.riskScore}/100</strong>
                    </span>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => onLocateOnMap(alert.flightId)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-950/70 hover:bg-cyan-900 border border-cyan-500/50 text-cyan-300 hover:text-cyan-200 font-mono text-xs transition-colors shadow-sm"
                    >
                      <MapPin className="w-3.5 h-3.5 text-cyan-400" />
                      <span>LOCATE ON MAP</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
