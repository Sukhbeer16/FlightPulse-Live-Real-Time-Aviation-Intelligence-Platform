// ─────────────────────────────────────────────────────────
// FlightPulse Live — Tactical Flight Roster Side Panel
// High-density flight list with quick telemetry & risk badges
// ─────────────────────────────────────────────────────────

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronLeft, ChevronRight, Plane, ArrowRight, AlertTriangle, ShieldCheck } from 'lucide-react';
import type { FlightTrack } from '../../types';
import { RiskBadge, DelayBadge } from '../../components/AviationBadge';

interface FlightRosterPanelProps {
  flights: FlightTrack[];
  selectedFlight: FlightTrack | null;
  onSelectFlight: (flight: FlightTrack) => void;
  isOpen: boolean;
  onToggleOpen: () => void;
}

export const FlightRosterPanel: React.FC<FlightRosterPanelProps> = ({
  flights,
  selectedFlight,
  onSelectFlight,
  isOpen,
  onToggleOpen,
}) => {
  return (
    <>
      {/* Floating Toggle Pill when closed */}
      {!isOpen && (
        <button
          onClick={onToggleOpen}
          className="absolute left-3 top-20 z-20 flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-900/90 hover:bg-slate-800 border border-slate-800/90 text-slate-200 text-xs font-mono shadow-xl backdrop-blur-md transition-all group"
          title="Open Flight Roster"
        >
          <Plane className="w-4 h-4 text-cyan-400 group-hover:rotate-45 transition-transform" />
          <span>ROSTER ({flights.length})</span>
          <ChevronRight className="w-4 h-4 text-slate-400" />
        </button>
      )}

      {/* Expanded Roster Drawer */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ x: -380, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: -380, opacity: 0 }}
            transition={{ type: 'spring', damping: 25, stiffness: 220 }}
            className="absolute left-3 top-20 bottom-12 z-20 w-[340px] sm:w-[380px] flex flex-col rounded-2xl bg-slate-950/92 border border-slate-800/90 shadow-2xl backdrop-blur-xl overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/80 bg-slate-900/60">
              <div className="flex items-center gap-2">
                <Plane className="w-4 h-4 text-cyan-400" />
                <span className="font-mono font-bold text-sm tracking-wide text-slate-100">
                  TRACKED AIRSPACE
                </span>
                <span className="px-2 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 text-cyan-400 font-mono text-[11px] font-semibold">
                  {flights.length}
                </span>
              </div>
              <button
                onClick={onToggleOpen}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800/80 transition-colors"
                title="Collapse Panel"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
            </div>

            {/* Flight Items Scroll Area */}
            <div className="flex-1 overflow-y-auto p-2 space-y-2 divide-y divide-slate-800/40">
              {flights.length === 0 ? (
                <div className="p-8 text-center text-slate-500 font-mono text-xs">
                  No aircraft match current filter criteria.
                </div>
              ) : (
                flights.map((flight) => {
                  const isSelected = selectedFlight?.id === flight.id;
                  const isCritical = flight.intelligence.riskLevel === 'critical';

                  return (
                    <motion.div
                      key={flight.id}
                      whileHover={{ scale: 1.01 }}
                      onClick={() => onSelectFlight(flight)}
                      className={`cursor-pointer rounded-xl p-3 transition-all relative overflow-hidden ${
                        isSelected
                          ? 'bg-slate-900/90 border border-cyan-500/60 shadow-[0_0_15px_rgba(0,229,255,0.15)]'
                          : isCritical
                          ? 'bg-red-950/20 border border-red-500/40 hover:bg-red-950/30'
                          : 'bg-slate-900/40 hover:bg-slate-900/70 border border-slate-800/60'
                      }`}
                    >
                      {/* Left colored airline stripe */}
                      <div
                        className="absolute left-0 top-0 bottom-0 w-1 rounded-l"
                        style={{ backgroundColor: flight.airline.color || '#38BDF8' }}
                      />

                      {/* Top Row: Callsign, Flight Number & Badges */}
                      <div className="flex items-start justify-between gap-2 pl-1.5 mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-bold text-sm text-slate-100 tracking-wider">
                            {flight.callsign}
                          </span>
                          <span className="text-xs text-slate-400 font-mono">
                            ({flight.flightNumber})
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <RiskBadge level={flight.intelligence.riskLevel} showScore={false} />
                        </div>
                      </div>

                      {/* Middle Row: Route (Origin -> Destination) */}
                      <div className="flex items-center justify-between text-xs font-mono text-slate-300 pl-1.5 mb-2">
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-slate-100">{flight.origin.iata}</span>
                          <span className="text-slate-500 text-[10px]">{flight.origin.city}</span>
                        </div>
                        <ArrowRight className="w-3.5 h-3.5 text-cyan-400/80" />
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-slate-100">
                            {flight.destination.iata}
                          </span>
                          <span className="text-slate-500 text-[10px]">
                            {flight.destination.city}
                          </span>
                        </div>
                      </div>

                      {/* Bottom Telemetry Bar: Altitude, Speed, Progress */}
                      <div className="flex items-center justify-between pl-1.5 pt-1.5 border-t border-slate-800/60 text-[11px] font-mono text-slate-400">
                        <div className="flex items-center gap-3">
                          <span>
                            ALT:{' '}
                            <strong className="text-slate-200">
                              FL{Math.round(flight.telemetry.altitudeFt / 100)}
                            </strong>
                          </span>
                          <span>
                            SPD:{' '}
                            <strong className="text-slate-200">
                              {flight.telemetry.groundSpeedKts} kt
                            </strong>
                          </span>
                        </div>
                        <div>
                          <DelayBadge
                            category={flight.delayCategory}
                            minutes={flight.delayMinutes}
                          />
                        </div>
                      </div>

                      {/* Critical Anomaly Highlight banner */}
                      {isCritical && flight.intelligence.anomalies.length > 0 && (
                        <div className="mt-2 pl-1.5 py-1 px-2 rounded bg-red-950/60 border border-red-500/40 text-[10px] font-mono text-red-300 flex items-center gap-1.5">
                          <AlertTriangle className="w-3 h-3 text-red-400 shrink-0 animate-pulse" />
                          <span className="truncate">
                            {flight.intelligence.anomalies[0].title}
                          </span>
                        </div>
                      )}
                    </motion.div>
                  );
                })
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};
