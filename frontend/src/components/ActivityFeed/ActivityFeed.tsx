import { motion } from 'framer-motion';
import { Plane, BrainCircuit, ShieldAlert, RefreshCw, FlaskConical } from 'lucide-react';
import { listContainer, fadeInUp } from '../../animations/variants';
import { DEMO_ACTIVITY_EVENTS } from '../../data/mockData';
import type { ActivityEvent, ActivityType } from '../../types';

// ── Icon map ──────────────────────────────────

const TYPE_ICONS: Record<ActivityType, React.ElementType> = {
  aircraft_tracked: Plane,
  prediction_made: BrainCircuit,
  anomaly_detected: ShieldAlert,
  data_updated: RefreshCw,
  system_event: RefreshCw,
};

const SEVERITY_COLORS = {
  info: '#25BCEB',
  warning: '#F59E0B',
  critical: '#EF4444',
};

// ── Time formatter ────────────────────────────

function timeAgo(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Single activity item ──────────────────────

function ActivityItem({ event }: { event: ActivityEvent }) {
  const Icon = TYPE_ICONS[event.type] ?? RefreshCw;
  const color = event.severity ? SEVERITY_COLORS[event.severity] : '#25BCEB';

  return (
    <motion.div
      variants={fadeInUp}
      className="flex gap-3 py-3"
      style={{ borderBottom: '1px solid rgba(241,245,249,0.05)' }}
    >
      <div
        className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg"
        style={{ background: `${color}18`, border: `1px solid ${color}30` }}
      >
        <Icon size={13} style={{ color }} />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2 mb-0.5">
          <span className="text-[12px] font-semibold truncate" style={{ color: '#F1F5F9' }}>
            {event.title}
          </span>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {event.isDemo && (
              <span
                className="rounded px-1 py-0.5 text-[8px] font-bold tracking-wider"
                style={{ background: 'rgba(37,188,235,0.1)', color: '#25BCEB' }}
              >
                DEMO
              </span>
            )}
            <span className="text-[10px] whitespace-nowrap" style={{ color: '#475569' }}>
              {timeAgo(event.timestamp)}
            </span>
          </div>
        </div>
        <p className="text-[11px] leading-relaxed" style={{ color: '#94A3B8' }}>
          {event.description}
        </p>
      </div>
    </motion.div>
  );
}

// ── Activity Feed ─────────────────────────────

export function ActivityFeed() {
  return (
    <div
      className="rounded-fp p-5"
      style={{ background: '#131E2E', border: '1px solid rgba(241,245,249,0.07)' }}
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[14px] font-semibold" style={{ color: '#F1F5F9' }}>
          Recent Activity
        </h3>
        <div
          className="flex items-center gap-1 rounded px-1.5 py-0.5"
          style={{ background: 'rgba(37,188,235,0.1)', border: '1px solid rgba(37,188,235,0.2)' }}
        >
          <FlaskConical size={9} style={{ color: '#25BCEB' }} />
          <span className="text-[9px] font-semibold tracking-wider" style={{ color: '#25BCEB' }}>
            DEMO EVENTS
          </span>
        </div>
      </div>

      <motion.div
        variants={listContainer}
        initial="hidden"
        animate="visible"
      >
        {DEMO_ACTIVITY_EVENTS.map((event) => (
          <ActivityItem key={event.id} event={event} />
        ))}
      </motion.div>
    </div>
  );
}

