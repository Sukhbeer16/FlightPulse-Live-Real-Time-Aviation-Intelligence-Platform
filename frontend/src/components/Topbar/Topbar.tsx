// ─────────────────────────────────────────────────────────
// FlightPulse Live — Tactical Aviation Operations Topbar
// Real-time Zulu UTC clock, connection telemetry & quick view navigation
// ─────────────────────────────────────────────────────────

import React, { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  Plane,
  Radio,
  Activity,
  ShieldAlert,
  Cpu,
  Clock,
  Menu,
  Bell,
  Sparkles,
  Wifi,
} from 'lucide-react';

interface TopbarProps {
  onToggleMobile?: () => void;
}

export const Topbar: React.FC<TopbarProps> = ({ onToggleMobile }) => {
  const [utcTime, setUtcTime] = useState<string>('');
  const location = useLocation();

  // 1-second Zulu UTC Clock
  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      const hours = String(now.getUTCHours()).padStart(2, '0');
      const minutes = String(now.getUTCMinutes()).padStart(2, '0');
      const seconds = String(now.getUTCSeconds()).padStart(2, '0');
      setUtcTime(`${hours}:${minutes}:${seconds} UTC`);
    };

    updateClock();
    const timer = setInterval(updateClock, 1000);
    return () => clearInterval(timer);
  }, []);

  const navLinks = [
    { label: 'LIVE TRACKER', path: '/live-tracking', icon: Radio },
    { label: 'INTELLIGENCE', path: '/', icon: Activity },
    { label: 'ALERTS & ANOMALIES', path: '/anomaly-detection', icon: ShieldAlert },
    { label: 'DELAY ML', path: '/delay-prediction', icon: Cpu },
  ];

  return (
    <header className="h-16 w-full px-4 flex items-center justify-between border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-xl z-20 select-none">
      {/* Left: Brand & Mobile Toggle */}
      <div className="flex items-center gap-3">
        {onToggleMobile && (
          <button
            onClick={onToggleMobile}
            className="md:hidden p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800"
          >
            <Menu className="w-5 h-5" />
          </button>
        )}

        <NavLink to="/live-tracking" className="flex items-center gap-2.5 group">
          <div className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-cyan-950/70 border border-cyan-500/50 group-hover:border-cyan-400 transition-colors shadow-md shadow-cyan-500/10">
            <Plane className="w-4 h-4 text-cyan-400 group-hover:scale-110 transition-transform -rotate-45" />
            <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-mono font-extrabold text-sm tracking-widest text-slate-100">
                FLIGHTPULSE
              </span>
              <span className="text-[10px] font-mono font-black text-cyan-400 bg-cyan-950/80 px-1 rounded border border-cyan-500/40">
                LIVE
              </span>
            </div>
            <span className="text-[9px] font-mono text-slate-500 tracking-wider block">
              PREMIUM AVIATION INTELLIGENCE
            </span>
          </div>
        </NavLink>
      </div>

      {/* Center: Tactical Screen Navigation Tabs */}
      <nav className="hidden md:flex items-center gap-1 bg-slate-900/60 p-1 rounded-xl border border-slate-800/80">
        {navLinks.map(({ label, path, icon: Icon }) => {
          const isActive = location.pathname === path;
          return (
            <NavLink
              key={path}
              to={path}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold tracking-wider transition-all ${
                isActive
                  ? 'bg-cyan-500/15 border border-cyan-500/40 text-cyan-300 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
              }`}
            >
              <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-cyan-400' : 'text-slate-400'}`} />
              <span>{label}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* Right: Zulu Clock & Telemetry Status */}
      <div className="flex items-center gap-3 font-mono text-xs">
        {/* Zulu UTC Clock */}
        <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-900/80 border border-slate-800 text-slate-300 shadow-inner">
          <Clock className="w-3.5 h-3.5 text-cyan-400" />
          <span className="font-bold text-slate-100">{utcTime || '12:00:00 UTC'}</span>
        </div>

        {/* Live / Demo Mode Badge */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-900/80 border border-slate-800 text-slate-300">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
          <span className="text-[11px] text-slate-300">
            {'HISTORICAL / LOCAL'}
          </span>
        </div>
      </div>
    </header>
  );
};
export default Topbar;
