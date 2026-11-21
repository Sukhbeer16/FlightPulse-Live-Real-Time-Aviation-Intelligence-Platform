// ─────────────────────────────────────────────────────────
// FlightPulse Live — Aviation Badge & Status Indicators
// ─────────────────────────────────────────────────────────

import React from 'react';
import type { RiskLevel, DelayCategory } from '../types';

interface RiskBadgeProps {
  level: RiskLevel;
  score?: number;
  showScore?: boolean;
}

export const RiskBadge: React.FC<RiskBadgeProps> = ({ level, score, showScore = true }) => {
  const config = {
    minimal: {
      bg: 'bg-emerald-950/40 border-emerald-500/30 text-emerald-400',
      dot: 'bg-emerald-400',
      label: 'MINIMAL RISK',
    },
    elevated: {
      bg: 'bg-amber-950/40 border-amber-500/30 text-amber-400',
      dot: 'bg-amber-400',
      label: 'ELEVATED RISK',
    },
    high: {
      bg: 'bg-orange-950/40 border-orange-500/40 text-orange-400',
      dot: 'bg-orange-400 animate-pulse',
      label: 'HIGH RISK',
    },
    critical: {
      bg: 'bg-red-950/50 border-red-500/50 text-red-400 shadow-[0_0_12px_rgba(239,68,68,0.25)]',
      dot: 'bg-red-400 animate-ping',
      label: 'CRITICAL ANOMALY',
    },
  }[level] || {
    bg: 'bg-slate-900 border-slate-700 text-slate-400',
    dot: 'bg-slate-400',
    label: 'UNKNOWN',
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono tracking-wider font-semibold border ${config.bg}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
      <span>{config.label}</span>
      {showScore && score !== undefined && (
        <span className="opacity-80 font-normal">[{score}]</span>
      )}
    </span>
  );
};

interface DelayBadgeProps {
  category: DelayCategory;
  minutes?: number;
}

export const DelayBadge: React.FC<DelayBadgeProps> = ({ category, minutes }) => {
  const config = {
    on_time: {
      bg: 'bg-cyan-950/40 border-cyan-500/30 text-cyan-400',
      label: 'ON TIME',
    },
    minor: {
      bg: 'bg-amber-950/30 border-amber-500/30 text-amber-300',
      label: minutes ? `+${minutes}m DELAY` : 'MINOR DELAY',
    },
    moderate: {
      bg: 'bg-orange-950/40 border-orange-500/40 text-orange-400',
      label: minutes ? `+${minutes}m DELAY` : 'MODERATE DELAY',
    },
    severe: {
      bg: 'bg-red-950/50 border-red-500/40 text-red-400',
      label: minutes ? `+${minutes}m DELAY` : 'SEVERE DELAY',
    },
  }[category];

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-medium tracking-wider border ${config.bg}`}
    >
      {config.label}
    </span>
  );
};

interface SeverityBadgeProps {
  severity: 'critical' | 'high' | 'medium' | 'low';
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({ severity }) => {
  const config = {
    critical: 'bg-red-950/60 border-red-500 text-red-400 animate-pulse',
    high: 'bg-orange-950/50 border-orange-500 text-orange-400',
    medium: 'bg-amber-950/40 border-amber-500/60 text-amber-300',
    low: 'bg-blue-950/40 border-blue-500/40 text-blue-300',
  }[severity];

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-bold tracking-widest uppercase border ${config}`}
    >
      {severity}
    </span>
  );
};
