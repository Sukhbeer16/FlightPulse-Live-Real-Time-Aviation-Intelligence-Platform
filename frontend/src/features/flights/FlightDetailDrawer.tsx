// ─────────────────────────────────────────────────────────
// FlightPulse Live — Flight Intelligence Details Drawer
// Sophisticated aviation drawer distinguishing Actuals, Historicals & ML Predictions
// ─────────────────────────────────────────────────────────

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  Plane,
  Navigation,
  Compass,
  Gauge,
  Clock,
  Radio,
  AlertTriangle,
  Cpu,
  History,
  Activity,
  ArrowRight,
  ShieldAlert,
} from 'lucide-react';
import type { FlightTrack } from '../../types';
import { RiskBadge, DelayBadge } from '../../components/AviationBadge';

interface FlightDetailDrawerProps {
  flight: FlightTrack | null;
  onClose: () => void;
}

export const FlightDetailDrawer: React.FC<FlightDetailDrawerProps> = ({ flight, onClose }) => {
  if (!flight) return null;

  const isCritical = flight.intelligence.riskLevel === 'critical';
  const machNumber = flight.telemetry.groundSpeedKts == null ? 'unknown' : (flight.telemetry.groundSpeedKts / 573.8).toFixed(2); // approximate Mach at FL360

  return (
    <AnimatePresence>
      <motion.div
        initial={{ x: 440, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 440, opacity: 0 }}
        transition={{ type: 'spring', damping: 26, stiffness: 220 }}
        className="fixed sm:absolute right-0 top-0 bottom-0 z-30 w-full sm:w-[420px] bg-slate-950/95 border-l border-slate-800/90 shadow-2xl backdrop-blur-2xl flex flex-col overflow-hidden text-slate-100"
      >
        {/* Top Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-800/80 bg-slate-900/60">
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center font-mono font-bold text-sm shadow-md"
              style={{
                backgroundColor: `${flight.airline.color}25`,
                border: `1.5px solid ${flight.airline.color}`,
                color: flight.airline.color,
              }}
            >
              {flight.airline.code}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-mono font-extrabold text-lg tracking-wider text-slate-100">
                  {flight.callsign}
                </h2>
                <span className="text-xs font-mono text-slate-400">
                  ({flight.flightNumber})
                </span>
              </div>
              <p className="text-xs text-slate-400 font-sans">
                {flight.airline.name} • {flight.aircraft.model}
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            title="Close Drawer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {flight.sourceDetails ? <div className="p-4 space-y-2 text-sm">
          <h3>{flight.dataKind === 'historical_bts' ? 'Historical BTS record' : 'Live aircraft observation'}</h3>
          {flight.sourceDetails.map(line => <p key={line}>{line}</p>)}
        </div> : (
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Critical Emergency Banner if applicable */}
          {isCritical && (
            <div className="p-3 rounded-xl bg-red-950/70 border border-red-500/80 shadow-[0_0_20px_rgba(239,68,68,0.25)] flex items-start gap-2.5 animate-pulse">
              <ShieldAlert className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
              <div>
                <h4 className="font-mono font-bold text-xs text-red-300 tracking-wider">
                  HIGH-PRIORITY DEMONSTRATION RISK
                </h4>
                <p className="text-[11px] font-mono text-red-200 mt-0.5">
                  This banner is based on demonstration UI data only; it is not a confirmed emergency.
                </p>
              </div>
            </div>
          )}

          {/* Route & Progress Card */}
          <div className="p-3.5 rounded-xl bg-slate-900/50 border border-slate-800/80 space-y-3">
            <div className="flex items-center justify-between text-xs font-mono">
              {/* Origin */}
              <div>
                <span className="text-2xl font-bold font-mono tracking-tight text-slate-100">
                  {flight.origin.btsCode ?? flight.origin.iata}
                </span>
                <p className="text-[11px] text-slate-400 truncate max-w-[120px]">
                  {flight.origin.name}
                </p>
                <div className="text-[10px] text-slate-400 mt-1">
                  STD: <strong className="text-slate-200">{flight.progress.departureScheduled}</strong>
                </div>
              </div>

              {/* Center Plane Icon */}
              <div className="flex flex-col items-center px-2">
                <Plane
                  className="w-5 h-5 text-cyan-400 transition-transform"
                  style={{ transform: `rotate(${flight.telemetry.headingDeg}deg)` }}
                />
                <span className="text-[10px] font-mono text-slate-500 mt-1">
                  {flight.progress.distanceTotalKm} km
                </span>
              </div>

              {/* Destination */}
              <div className="text-right">
                <span className="text-2xl font-bold font-mono tracking-tight text-slate-100">
                  {flight.destination.btsCode ?? flight.destination.iata}
                </span>
                <p className="text-[11px] text-slate-400 truncate max-w-[120px]">
                  {flight.destination.name}
                </p>
                <div className="text-[10px] text-slate-400 mt-1">
                  ETA: <strong className="text-cyan-400">{flight.progress.arrivalEstimated}</strong>
                </div>
              </div>
            </div>

            {/* Flight Progress Bar */}
            <div className="space-y-1 pt-1">
              <div className="flex items-center justify-between text-[10px] font-mono text-slate-400">
                <span>{flight.progress.distanceElapsedKm} km flown</span>
                <span className="font-bold text-cyan-400">{flight.progress.percentage}%</span>
                <span>{flight.progress.distanceRemainingKm} km remaining</span>
              </div>
              <div className="w-full h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-sky-400 transition-all duration-500"
                  style={{ width: `${flight.progress.percentage}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[9px] font-mono text-slate-500 pt-0.5">
                <span>Elapsed: {flight.progress.elapsedTimeMin}m</span>
                <span>Remaining: {flight.progress.remainingTimeMin}m</span>
              </div>
            </div>
          </div>

          {/* Real-time Telemetry Grid */}
          <div>
            <h3 className="font-mono text-[11px] font-bold text-slate-400 tracking-wider uppercase mb-2 flex items-center gap-1.5">
              <Radio className="w-3.5 h-3.5 text-cyan-400" />
              <span>Real-Time Telemetry (ADS-B)</span>
            </h3>

            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              {/* Altitude */}
              <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800/80">
                <span className="text-[10px] text-slate-500 block uppercase">Baro Altitude</span>
                <div className="flex items-baseline gap-1 mt-0.5">
                  <span className="text-base font-bold text-slate-100">
                    {flight.telemetry.altitudeFt?.toLocaleString() ?? 'Unknown'}
                  </span>
                  <span className="text-[10px] text-slate-400">ft (FL{(flight.telemetry.altitudeFt == null ? 'unknown' : Math.round(flight.telemetry.altitudeFt / 100))})</span>
                </div>
              </div>

              {/* Speed */}
              <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800/80">
                <span className="text-[10px] text-slate-500 block uppercase">Ground Speed</span>
                <div className="flex items-baseline gap-1 mt-0.5">
                  <span className="text-base font-bold text-slate-100">
                    {flight.telemetry.groundSpeedKts}
                  </span>
                  <span className="text-[10px] text-slate-400">kts (M {machNumber})</span>
                </div>
              </div>

              {/* Heading */}
              <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800/80">
                <span className="text-[10px] text-slate-500 block uppercase">True Track</span>
                <div className="flex items-baseline gap-1 mt-0.5">
                  <span className="text-base font-bold text-slate-100">
                    {flight.telemetry.headingDeg}°
                  </span>
                  <span className="text-[10px] text-slate-400">HEADING</span>
                </div>
              </div>

              {/* Squawk */}
              <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800/80">
                <span className="text-[10px] text-slate-500 block uppercase">Transponder</span>
                <div className="flex items-baseline gap-1 mt-0.5">
                  <span className="text-base font-bold font-mono text-slate-100">
                    SQK {flight.telemetry.squawk}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Predictive Delay & Risk Score */}
          <div className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800/90 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 font-mono text-xs font-bold text-slate-300">
                <Cpu className="w-4 h-4 text-cyan-400" />
                <span>Predictive Delay & Risk Model</span>
              </div>
              <RiskBadge level={flight.intelligence.riskLevel} score={flight.intelligence.riskScore} />
            </div>

            <div className="flex items-center gap-4 pt-1">
              {/* Circular Gauge Score */}
              <div className="relative w-16 h-16 shrink-0 flex items-center justify-center">
                <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                  <path
                    className="text-slate-800"
                    strokeWidth="3.5"
                    stroke="currentColor"
                    fill="none"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                  <path
                    className={
                      flight.intelligence.riskScore > 75
                        ? 'text-red-400'
                        : flight.intelligence.riskScore > 40
                        ? 'text-amber-400'
                        : 'text-cyan-400'
                    }
                    strokeDasharray={`${flight.intelligence.riskScore}, 100`}
                    strokeWidth="3.5"
                    strokeLinecap="round"
                    stroke="currentColor"
                    fill="none"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                </svg>
                <div className="absolute flex flex-col items-center">
                  <span className="font-mono font-bold text-sm text-slate-100">
                    {flight.intelligence.riskScore}
                  </span>
                  <span className="text-[8px] font-mono text-slate-500">RISK</span>
                </div>
              </div>

              {/* Model Rationale */}
              <div className="text-xs font-mono space-y-1">
                <div className="text-slate-300">
                  Predicted Category:{' '}
                  <strong className="text-cyan-400 font-bold">
                    {flight.intelligence.predictedDelayCategory}
                  </strong>
                </div>
                <div className="text-[11px] text-slate-400">
                  Confidence: Not provided by backend
                </div>
                <div className="text-[11px] text-slate-400">
                  Predicted Arrival Delta:{' '}
                  <span
                    className={
                      flight.intelligence.predictedArrivalDelayMin > 15
                        ? 'text-amber-400 font-bold'
                        : 'text-emerald-400 font-bold'
                    }
                  >
                    {flight.intelligence.predictedArrivalDelayMin > 0 ? '+' : ''}
                    {flight.intelligence.predictedArrivalDelayMin} min
                  </span>
                </div>
              </div>
            </div>

            {/* Explanation text */}
            <p className="text-[11px] text-slate-300 leading-relaxed font-sans pt-1 border-t border-slate-800/80">
              {flight.intelligence.intelligenceSummary}
            </p>
          </div>

          {/* TRIPLE CLASSIFICATION BREAKDOWN */}
          <div className="space-y-3 pt-2">
            <h4 className="font-mono text-[10px] font-bold text-slate-500 tracking-widest uppercase">
              Operational Intelligence Breakdown
            </h4>

            {/* 1. ACTUAL OBSERVATIONS */}
            <div className="p-3 rounded-lg bg-slate-900/40 border border-slate-800/70 space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-cyan-400">
                <Radio className="w-3.5 h-3.5" />
                <span>1. ACTUAL OBSERVATIONS</span>
              </div>
              <ul className="text-[11px] font-sans text-slate-300 space-y-1 list-disc list-inside">
                {flight.intelligence.actualObservations.map((obs, i) => (
                  <li key={i}>{obs}</li>
                ))}
              </ul>
            </div>

            {/* 2. HISTORICAL FACTS */}
            <div className="p-3 rounded-lg bg-slate-900/40 border border-slate-800/70 space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-amber-400">
                <History className="w-3.5 h-3.5" />
                <span>2. HISTORICAL FACTS</span>
              </div>
              <ul className="text-[11px] font-sans text-slate-300 space-y-1 list-disc list-inside">
                {flight.intelligence.historicalFacts.map((fact, i) => (
                  <li key={i}>{fact}</li>
                ))}
              </ul>
            </div>

            {/* 3. MODEL PREDICTIONS */}
            <div className="p-3 rounded-lg bg-slate-900/40 border border-slate-800/70 space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-purple-400">
                <Cpu className="w-3.5 h-3.5" />
                <span>3. MODEL PREDICTIONS</span>
              </div>
              <ul className="text-[11px] font-sans text-slate-300 space-y-1 list-disc list-inside">
                {flight.intelligence.modelPredictions.map((pred, i) => (
                  <li key={i}>{pred}</li>
                ))}
              </ul>
            </div>
          </div>

          {/* Aircraft Technical Specs */}
          <div className="p-3 rounded-lg bg-slate-900/30 border border-slate-800/60 text-[11px] font-mono text-slate-400 space-y-1">
            <div className="flex justify-between">
              <span>ICAO24 HEX:</span>
              <span className="text-slate-200 uppercase">{flight.aircraft.icao24}</span>
            </div>
            <div className="flex justify-between">
              <span>REGISTRATION:</span>
              <span className="text-slate-200">{flight.aircraft.registration}</span>
            </div>
            <div className="flex justify-between">
              <span>AIRCRAFT TYPE:</span>
              <span className="text-slate-200">{flight.aircraft.typeCode}</span>
            </div>
            <div className="flex justify-between">
              <span>DATA SOURCE:</span>
              <span className="text-cyan-400">{flight.isDemo ? 'SIMULATION / MOCK' : 'FASTAPI BACKEND'}</span>
            </div>
          </div>
        </div>
        )}
      </motion.div>
    </AnimatePresence>
  );
};
