import { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard,
  Radio,
  BrainCircuit,
  ShieldAlert,
  BarChart3,
  Zap,
  MessageSquare,
  Settings,
  Activity,
  UserCircle,
  ChevronLeft,
  ChevronRight,
  X,
} from 'lucide-react';
import { sidebarVariants, sidebarTransition } from '../../animations/variants';

interface NavItemDef {
  id: string;
  label: string;
  path: string;
  Icon: React.ElementType;
}

const NAV_ITEMS: NavItemDef[] = [
  { id: 'overview', label: 'Overview', path: '/', Icon: LayoutDashboard },
  { id: 'live-tracking', label: 'Live Tracking', path: '/live-tracking', Icon: Radio },
  { id: 'delay-prediction', label: 'Delay Prediction', path: '/delay-prediction', Icon: BrainCircuit },
  { id: 'anomaly-detection', label: 'Anomaly Detection', path: '/anomaly-detection', Icon: ShieldAlert },
  { id: 'historical', label: 'Historical Analytics', path: '/historical', Icon: BarChart3 },
  { id: 'disruption', label: 'Disruption Intel', path: '/disruption', Icon: Zap },
  { id: 'assistant', label: 'Aviation Assistant', path: '/assistant', Icon: MessageSquare },
];

const BOTTOM_ITEMS: NavItemDef[] = [
  { id: 'settings', label: 'Settings', path: '/settings', Icon: Settings },
  { id: 'status', label: 'System Status', path: '/system-status', Icon: Activity },
];

interface SidebarProps {
  mobileOpen?: boolean;
  onCloseMobile?: () => void;
}

export function Sidebar({ mobileOpen = false, onCloseMobile }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  // Close mobile drawer on route change
  useEffect(() => {
    onCloseMobile?.();
  }, [location.pathname, onCloseMobile]);

  const navContent = (
    <div className="flex h-full flex-col">
      {/* ── Brand ─────────────────────────── */}
      <div
        className="flex h-[60px] items-center justify-between px-4"
        style={{ borderBottom: '1px solid rgba(241,245,249,0.07)' }}
      >
        <div className="flex items-center gap-3 min-w-0">
          {/* Logo mark */}
          <div
            className="flex-shrink-0 flex h-8 w-8 items-center justify-center rounded-lg"
            style={{
              background: 'linear-gradient(135deg, rgba(37,188,235,0.2), rgba(66,133,244,0.2))',
              border: '1px solid rgba(37,188,235,0.4)',
            }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M2 11 L8 3 L14 11"
                stroke="#25BCEB"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M5 11 L8 7 L11 11"
                stroke="#4285F4"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>

          {(!collapsed || mobileOpen) && (
            <div className="min-w-0 overflow-hidden">
              <div
                className="text-xs font-bold tracking-widest whitespace-nowrap"
                style={{ color: '#F1F5F9', letterSpacing: '0.12em' }}
              >
                FLIGHTPULSE
              </div>
              <div
                className="text-[9px] font-medium tracking-widest whitespace-nowrap"
                style={{ color: '#25BCEB', letterSpacing: '0.18em' }}
              >
                LIVE AVIATION INTELLIGENCE
              </div>
            </div>
          )}
        </div>

        {/* Mobile close button */}
        {mobileOpen && (
          <button
            onClick={onCloseMobile}
            className="md:hidden flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 hover:text-slate-100"
            style={{ background: 'rgba(241,245,249,0.05)' }}
            aria-label="Close menu"
          >
            <X size={15} />
          </button>
        )}
      </div>

      {/* ── Navigation ────────────────────── */}
      <nav className="flex flex-col gap-0.5 px-2 pt-3 flex-1 overflow-y-auto overflow-x-hidden">
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path);

          return (
            <NavLinkItem
              key={item.id}
              item={item}
              isActive={isActive}
              collapsed={mobileOpen ? false : collapsed}
              onClick={onCloseMobile}
            />
          );
        })}
      </nav>

      {/* ── Bottom Section ─────────────────── */}
      <div
        className="flex flex-col gap-0.5 px-2 pb-3"
        style={{ borderTop: '1px solid rgba(241,245,249,0.07)', paddingTop: '12px' }}
      >
        {BOTTOM_ITEMS.map((item) => {
          const isActive = location.pathname.startsWith(item.path);
          return (
            <NavLinkItem
              key={item.id}
              item={item}
              isActive={isActive}
              collapsed={mobileOpen ? false : collapsed}
              onClick={onCloseMobile}
            />
          );
        })}

        {/* User Profile */}
        <button
          className="flex items-center gap-3 rounded-lg px-3 py-2.5 w-full text-left transition-colors mt-1"
          style={{
            color: '#94A3B8',
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = 'rgba(241,245,249,0.05)';
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
          }}
          title={collapsed && !mobileOpen ? 'User Profile' : undefined}
        >
          <UserCircle size={18} className="flex-shrink-0" />
          {(!collapsed || mobileOpen) && (
            <span className="text-[13px] font-medium whitespace-nowrap overflow-hidden">
              User Profile
            </span>
          )}
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* ── Desktop Sidebar ──────────────── */}
      <motion.aside
        variants={sidebarVariants}
        animate={collapsed ? 'collapsed' : 'expanded'}
        transition={sidebarTransition}
        className="relative z-20 hidden md:flex h-screen flex-col overflow-hidden border-r"
        style={{
          backgroundColor: '#0A1020',
          borderColor: 'rgba(241,245,249,0.07)',
          flexShrink: 0,
        }}
      >
        {navContent}

        {/* Collapse Toggle */}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="absolute -right-3 top-[72px] flex h-6 w-6 items-center justify-center rounded-full transition-colors z-30"
          style={{
            background: '#131E2E',
            border: '1px solid rgba(241,245,249,0.12)',
            color: '#94A3B8',
            cursor: 'pointer',
          }}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronLeft size={12} />}
        </button>
      </motion.aside>

      {/* ── Mobile Drawer ────────────────── */}
      <AnimatePresence>
        {mobileOpen && (
          <div className="fixed inset-0 z-50 md:hidden flex">
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={onCloseMobile}
              className="fixed inset-0 bg-black/60 backdrop-blur-sm"
            />

            {/* Slide-out Menu */}
            <motion.aside
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ type: 'spring', stiffness: 350, damping: 30 }}
              className="relative z-10 w-[260px] h-full flex flex-col border-r shadow-2xl"
              style={{
                backgroundColor: '#0A1020',
                borderColor: 'rgba(241,245,249,0.1)',
              }}
            >
              {navContent}
            </motion.aside>
          </div>
        )}
      </AnimatePresence>
    </>
  );
}

// ── Individual Nav Link ───────────────────────

interface NavLinkItemProps {
  item: NavItemDef;
  isActive: boolean;
  collapsed: boolean;
  onClick?: () => void;
}

function NavLinkItem({ item, isActive, collapsed, onClick }: NavLinkItemProps) {
  const { Icon, label, path } = item;

  return (
    <NavLink
      to={path}
      onClick={onClick}
      title={collapsed ? label : undefined}
      className="flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors relative group"
      style={{
        background: isActive ? 'rgba(37,188,235,0.1)' : 'transparent',
        color: isActive ? '#25BCEB' : '#94A3B8',
        textDecoration: 'none',
        border: isActive ? '1px solid rgba(37,188,235,0.18)' : '1px solid transparent',
      }}
      onMouseEnter={(e) => {
        if (!isActive) {
          (e.currentTarget as HTMLAnchorElement).style.background = 'rgba(241,245,249,0.05)';
          (e.currentTarget as HTMLAnchorElement).style.color = '#F1F5F9';
        }
      }}
      onMouseLeave={(e) => {
        if (!isActive) {
          (e.currentTarget as HTMLAnchorElement).style.background = 'transparent';
          (e.currentTarget as HTMLAnchorElement).style.color = '#94A3B8';
        }
      }}
    >
      {/* Active indicator bar */}
      {isActive && (
        <motion.div
          layoutId="sidebar-active-bar"
          className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-r"
          style={{ background: '#25BCEB' }}
          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        />
      )}

      <Icon size={17} className="flex-shrink-0" />

      {!collapsed && (
        <span className="text-[13px] font-medium whitespace-nowrap overflow-hidden">
          {label}
        </span>
      )}

      {/* Collapsed tooltip */}
      {collapsed && (
        <div
          className="absolute left-full ml-2 px-2 py-1 rounded text-[11px] font-medium whitespace-nowrap pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity z-50"
          style={{
            background: '#1A2640',
            border: '1px solid rgba(241,245,249,0.12)',
            color: '#F1F5F9',
          }}
        >
          {label}
        </div>
      )}
    </NavLink>
  );
}
