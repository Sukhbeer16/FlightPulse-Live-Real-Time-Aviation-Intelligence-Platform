import { useState, useRef, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Bell, ChevronDown, Circle, Menu } from 'lucide-react';
import { dropdownVariants } from '../../animations/variants';
import { DEMO_SYSTEM_STATUS } from '../../data/mockData';
import type { ConnectionStatus } from '../../types';

// ── Page title map ────────────────────────────

const PAGE_TITLES: Record<string, { title: string; breadcrumb: string[] }> = {
  '/': { title: 'Overview', breadcrumb: ['FlightPulse', 'Overview'] },
  '/live-tracking': { title: 'Live Flight Tracking', breadcrumb: ['FlightPulse', 'Live Tracking'] },
  '/delay-prediction': { title: 'Delay Prediction', breadcrumb: ['FlightPulse', 'Delay Prediction'] },
  '/anomaly-detection': { title: 'Anomaly Detection', breadcrumb: ['FlightPulse', 'Anomaly Detection'] },
  '/historical': { title: 'Historical Analytics', breadcrumb: ['FlightPulse', 'Historical Analytics'] },
  '/disruption': { title: 'Disruption Intelligence', breadcrumb: ['FlightPulse', 'Disruption Intel'] },
  '/assistant': { title: 'Aviation Assistant', breadcrumb: ['FlightPulse', 'Aviation Assistant'] },
  '/settings': { title: 'Settings', breadcrumb: ['FlightPulse', 'Settings'] },
  '/system-status': { title: 'System Status', breadcrumb: ['FlightPulse', 'System Status'] },
};

// ── Status dot helper ─────────────────────────

const STATUS_COLORS: Record<ConnectionStatus, string> = {
  connected: '#22C55E',
  connecting: '#F59E0B',
  disconnected: '#475569',
  error: '#EF4444',
};

function StatusDot({ status }: { status: ConnectionStatus }) {
  const color = STATUS_COLORS[status];
  return (
    <span
      className="inline-block h-1.5 w-1.5 rounded-full"
      style={{ background: color }}
    />
  );
}

interface TopbarProps {
  onToggleMobile?: () => void;
}

export function Topbar({ onToggleMobile }: TopbarProps) {
  const location = useLocation();
  const pageInfo = PAGE_TITLES[location.pathname] ?? PAGE_TITLES['/'];
  const [searchFocused, setSearchFocused] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const notifRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setProfileOpen(false);
      }
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setNotifOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const overallStatus: ConnectionStatus =
    DEMO_SYSTEM_STATUS.opensky === 'connected' || DEMO_SYSTEM_STATUS.btsApi === 'connected'
      ? 'connected'
      : 'disconnected';

  return (
    <header
      className="flex h-[60px] flex-shrink-0 items-center gap-3 px-4 md:px-6"
      style={{
        background: 'rgba(10,16,32,0.95)',
        borderBottom: '1px solid rgba(241,245,249,0.07)',
        backdropFilter: 'blur(12px)',
        position: 'sticky',
        top: 0,
        zIndex: 10,
      }}
    >
      {/* ── Mobile Menu Button ─────────────── */}
      <button
        onClick={onToggleMobile}
        className="md:hidden flex h-8 w-8 items-center justify-center rounded-lg text-slate-300 hover:text-white transition-colors"
        style={{
          background: 'rgba(241,245,249,0.04)',
          border: '1px solid rgba(241,245,249,0.08)',
        }}
        aria-label="Open menu"
      >
        <Menu size={16} />
      </button>

      {/* ── Title + Breadcrumb ─────────────── */}
      <div className="flex-1 min-w-0">
        <div
          className="flex items-center gap-1.5 text-[10px] font-medium tracking-wider mb-0.5"
          style={{ color: '#475569' }}
        >
          {pageInfo.breadcrumb.map((crumb, i) => (
            <span key={crumb} className="flex items-center gap-1.5">
              {i > 0 && <span style={{ color: '#2A3A50' }}>/</span>}
              <span style={{ color: i === pageInfo.breadcrumb.length - 1 ? '#25BCEB' : '#475569' }}>
                {crumb}
              </span>
            </span>
          ))}
        </div>
        <h1
          className="text-[14px] md:text-[15px] font-semibold leading-none truncate"
          style={{ color: '#F1F5F9' }}
        >
          {pageInfo.title}
        </h1>
      </div>

      {/* ── Search ─────────────────────────── */}
      <div
        className="relative hidden sm:flex items-center"
        style={{
          width: searchFocused ? 260 : 200,
          transition: 'width 0.25s ease',
        }}
      >
        <Search
          size={13}
          className="absolute left-3 pointer-events-none"
          style={{ color: '#475569' }}
        />
        <input
          type="text"
          placeholder="Search aircraft, routes…"
          onFocus={() => setSearchFocused(true)}
          onBlur={() => setSearchFocused(false)}
          className="w-full rounded-lg py-2 pl-8 pr-3 text-[12px] outline-none transition-colors"
          style={{
            background: 'rgba(241,245,249,0.05)',
            border: `1px solid ${searchFocused ? 'rgba(37,188,235,0.35)' : 'rgba(241,245,249,0.08)'}`,
            color: '#F1F5F9',
          }}
        />
      </div>

      {/* ── System Connectivity ────────────── */}
      <button
        className="hidden lg:flex items-center gap-2 rounded-lg px-3 py-1.5 text-[11px] font-medium transition-colors"
        style={{
          background: 'rgba(241,245,249,0.04)',
          border: '1px solid rgba(241,245,249,0.08)',
          color: '#94A3B8',
          cursor: 'pointer',
        }}
        title="System connectivity status"
      >
        <StatusDot status={overallStatus} />
        <span>
          {overallStatus === 'connected' ? 'Systems Online' : 'Limited Connectivity'}
        </span>
      </button>

      {/* ── Notification Bell ──────────────── */}
      <div className="relative" ref={notifRef}>
        <button
          onClick={() => {
            setNotifOpen((n) => !n);
            setProfileOpen(false);
          }}
          className="relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors"
          style={{
            background: notifOpen ? 'rgba(37,188,235,0.1)' : 'rgba(241,245,249,0.04)',
            border: `1px solid ${notifOpen ? 'rgba(37,188,235,0.2)' : 'rgba(241,245,249,0.08)'}`,
            color: notifOpen ? '#25BCEB' : '#94A3B8',
            cursor: 'pointer',
          }}
          aria-label="Notifications"
        >
          <Bell size={14} />
          <span
            className="absolute -top-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full text-[8px] font-bold"
            style={{ background: '#EF4444', color: '#fff' }}
          >
            3
          </span>
        </button>

        <AnimatePresence>
          {notifOpen && (
            <motion.div
              key="notif-dropdown"
              variants={dropdownVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="absolute right-0 top-10 w-72 rounded-fp overflow-hidden"
              style={{
                background: '#131E2E',
                border: '1px solid rgba(241,245,249,0.1)',
                boxShadow: '0 16px 48px rgba(0,0,0,0.5)',
                zIndex: 50,
              }}
            >
              <div
                className="px-4 py-3"
                style={{ borderBottom: '1px solid rgba(241,245,249,0.07)' }}
              >
                <span className="text-[11px] font-semibold tracking-wider" style={{ color: '#94A3B8' }}>
                  NOTIFICATIONS
                </span>
              </div>
              {[
                { title: 'Anomaly Detected', desc: 'UAL328 — altitude irregularity', time: '5 min ago', dot: '#EF4444' },
                { title: 'Prediction Complete', desc: 'ORD→LAX delay model ran', time: '12 min ago', dot: '#F59E0B' },
                { title: 'BTS Data Updated', desc: 'Feb 2024 analytics refreshed', time: '1 hr ago', dot: '#22C55E' },
              ].map((n, i) => (
                <div
                  key={i}
                  className="flex gap-3 px-4 py-3 transition-colors"
                  style={{ borderBottom: '1px solid rgba(241,245,249,0.04)', cursor: 'pointer' }}
                  onMouseEnter={(e) =>
                    ((e.currentTarget as HTMLDivElement).style.background = 'rgba(241,245,249,0.03)')
                  }
                  onMouseLeave={(e) =>
                    ((e.currentTarget as HTMLDivElement).style.background = 'transparent')
                  }
                >
                  <Circle size={7} className="mt-1.5 flex-shrink-0" fill={n.dot} stroke="none" />
                  <div>
                    <div className="text-[12px] font-medium" style={{ color: '#F1F5F9' }}>
                      {n.title}
                    </div>
                    <div className="text-[11px]" style={{ color: '#94A3B8' }}>
                      {n.desc}
                    </div>
                    <div className="text-[10px] mt-0.5" style={{ color: '#475569' }}>
                      {n.time}
                    </div>
                  </div>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Profile ─────────────────────────── */}
      <div className="relative" ref={profileRef}>
        <button
          onClick={() => {
            setProfileOpen((p) => !p);
            setNotifOpen(false);
          }}
          className="flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors"
          style={{
            background: profileOpen ? 'rgba(37,188,235,0.08)' : 'rgba(241,245,249,0.04)',
            border: `1px solid ${profileOpen ? 'rgba(37,188,235,0.18)' : 'rgba(241,245,249,0.08)'}`,
            cursor: 'pointer',
          }}
        >
          <div
            className="flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold"
            style={{ background: 'linear-gradient(135deg, #25BCEB, #4285F4)', color: '#fff' }}
          >
            FP
          </div>
          <ChevronDown size={11} style={{ color: '#94A3B8' }} />
        </button>

        <AnimatePresence>
          {profileOpen && (
            <motion.div
              key="profile-dropdown"
              variants={dropdownVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="absolute right-0 top-10 w-48 rounded-fp overflow-hidden"
              style={{
                background: '#131E2E',
                border: '1px solid rgba(241,245,249,0.1)',
                boxShadow: '0 16px 48px rgba(0,0,0,0.5)',
                zIndex: 50,
              }}
            >
              {['Profile', 'Settings', 'Sign Out'].map((item, i) => (
                <button
                  key={item}
                  className="flex w-full px-4 py-2.5 text-[12px] text-left transition-colors"
                  style={{
                    color: i === 2 ? '#EF4444' : '#F1F5F9',
                    background: 'transparent',
                    border: 'none',
                    borderTop: i > 0 ? '1px solid rgba(241,245,249,0.05)' : undefined,
                    cursor: 'pointer',
                  }}
                  onMouseEnter={(e) =>
                    ((e.currentTarget as HTMLButtonElement).style.background = 'rgba(241,245,249,0.05)')
                  }
                  onMouseLeave={(e) =>
                    ((e.currentTarget as HTMLButtonElement).style.background = 'transparent')
                  }
                >
                  {item}
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </header>
  );
}
