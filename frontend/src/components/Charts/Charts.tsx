import { motion } from 'framer-motion';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
} from 'recharts';
import { FlaskConical } from 'lucide-react';
import { fadeInUp } from '../../animations/variants';
import { DEMO_DELAY_TREND, DEMO_AIRLINE_PERFORMANCE, DEMO_FLIGHT_ACTIVITY } from '../../data/mockData';

// ── Recharts shared styles ────────────────────

const axisStyle = { fill: '#475569', fontSize: 10, fontFamily: 'Inter' };
const gridStyle = { stroke: 'rgba(241,245,249,0.05)' };

// ── Shared section header ─────────────────────

function SectionHeader({
  title,
  subtitle,
  isDemo,
}: {
  title: string;
  subtitle?: string;
  isDemo?: boolean;
}) {
  return (
    <div className="flex items-start justify-between mb-5">
      <div>
        <h3 className="text-[14px] font-semibold mb-0.5" style={{ color: '#F1F5F9' }}>
          {title}
        </h3>
        {subtitle && (
          <p className="text-[11px]" style={{ color: '#475569' }}>
            {subtitle}
          </p>
        )}
      </div>
      {isDemo && (
        <div
          className="flex items-center gap-1 rounded px-1.5 py-0.5"
          style={{ background: 'rgba(37,188,235,0.1)', border: '1px solid rgba(37,188,235,0.2)' }}
        >
          <FlaskConical size={9} style={{ color: '#25BCEB' }} />
          <span className="text-[9px] font-semibold tracking-wider" style={{ color: '#25BCEB' }}>
            SAMPLE DATA
          </span>
        </div>
      )}
    </div>
  );
}

// ── Custom Tooltip ────────────────────────────

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}

function ChartTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div
      className="rounded-fp-sm px-3 py-2 text-[11px]"
      style={{
        background: '#1A2640',
        border: '1px solid rgba(241,245,249,0.12)',
        boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
      }}
    >
      <div className="font-semibold mb-1.5" style={{ color: '#F1F5F9' }}>{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full flex-shrink-0" style={{ background: p.color }} />
          <span style={{ color: '#94A3B8' }}>{p.name}:</span>
          <span style={{ color: '#F1F5F9' }}>{p.value}</span>
        </div>
      ))}
    </div>
  );
}

// ── Delay Trend Chart ─────────────────────────

export function DelayTrendChart() {
  return (
    <motion.div
      custom={0}
      variants={fadeInUp}
      initial="hidden"
      animate="visible"
      className="rounded-fp p-5"
      style={{ background: '#131E2E', border: '1px solid rgba(241,245,249,0.07)' }}
    >
      <SectionHeader
        title="Flight Delay Trend"
        subtitle="Average delay and delay rate — Jan 2023 to Feb 2024"
        isDemo={true}
      />
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={DEMO_DELAY_TREND} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
          <defs>
            <linearGradient id="delayGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#25BCEB" stopOpacity={0.18} />
              <stop offset="95%" stopColor="#25BCEB" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="rateGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#4285F4" stopOpacity={0.18} />
              <stop offset="95%" stopColor="#4285F4" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid {...gridStyle} />
          <XAxis
            dataKey="month"
            tick={axisStyle}
            tickLine={false}
            axisLine={false}
            interval={2}
          />
          <YAxis tick={axisStyle} tickLine={false} axisLine={false} />
          <Tooltip content={<ChartTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: 10, color: '#94A3B8', paddingTop: 12 }}
          />
          <Area
            type="monotone"
            dataKey="avgDelayMin"
            name="Avg Delay (min)"
            stroke="#25BCEB"
            strokeWidth={1.5}
            fill="url(#delayGrad)"
            dot={false}
          />
          <Area
            type="monotone"
            dataKey="delayRate"
            name="Delay Rate (%)"
            stroke="#4285F4"
            strokeWidth={1.5}
            fill="url(#rateGrad)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </motion.div>
  );
}

// ── Airline Performance Chart ─────────────────

export function AirlinePerformanceChart() {
  const data = DEMO_AIRLINE_PERFORMANCE.map((a) => ({
    name: a.code,
    'On-Time %': a.onTimeRate,
    'Avg Delay': a.avgDelay,
  }));

  return (
    <motion.div
      custom={1}
      variants={fadeInUp}
      initial="hidden"
      animate="visible"
      className="rounded-fp p-5"
      style={{ background: '#131E2E', border: '1px solid rgba(241,245,249,0.07)' }}
    >
      <SectionHeader
        title="Airline Performance"
        subtitle="On-time rate and average delay by carrier"
        isDemo={true}
      />
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }} barGap={4}>
          <CartesianGrid {...gridStyle} vertical={false} />
          <XAxis dataKey="name" tick={axisStyle} tickLine={false} axisLine={false} />
          <YAxis tick={axisStyle} tickLine={false} axisLine={false} />
          <Tooltip content={<ChartTooltip />} />
          <Legend wrapperStyle={{ fontSize: 10, color: '#94A3B8', paddingTop: 12 }} />
          <Bar dataKey="On-Time %" fill="#25BCEB" opacity={0.8} radius={[3, 3, 0, 0]} maxBarSize={24} />
          <Bar dataKey="Avg Delay" fill="#4285F4" opacity={0.8} radius={[3, 3, 0, 0]} maxBarSize={24} />
        </BarChart>
      </ResponsiveContainer>
    </motion.div>
  );
}

// ── Flight Activity Summary ────────────────────

export function FlightActivityChart() {
  const data = DEMO_FLIGHT_ACTIVITY.map((d) => ({
    date: d.date,
    Departures: d.departures,
    Arrivals: d.arrivals,
    Cancelled: d.cancelled,
  }));

  return (
    <motion.div
      custom={2}
      variants={fadeInUp}
      initial="hidden"
      animate="visible"
      className="rounded-fp p-5"
      style={{ background: '#131E2E', border: '1px solid rgba(241,245,249,0.07)' }}
    >
      <SectionHeader
        title="Flight Activity Summary"
        subtitle="Weekly departures, arrivals and cancellations — Jan–Feb 2024"
        isDemo={true}
      />
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -16, bottom: 0 }} barGap={4}>
          <CartesianGrid {...gridStyle} vertical={false} />
          <XAxis dataKey="date" tick={axisStyle} tickLine={false} axisLine={false} />
          <YAxis tick={axisStyle} tickLine={false} axisLine={false} />
          <Tooltip content={<ChartTooltip />} />
          <Legend wrapperStyle={{ fontSize: 10, color: '#94A3B8', paddingTop: 12 }} />
          <Bar dataKey="Departures" fill="#25BCEB" opacity={0.75} radius={[2, 2, 0, 0]} maxBarSize={20} />
          <Bar dataKey="Arrivals" fill="#4285F4" opacity={0.75} radius={[2, 2, 0, 0]} maxBarSize={20} />
          <Bar dataKey="Cancelled" fill="#EF4444" opacity={0.75} radius={[2, 2, 0, 0]} maxBarSize={20} />
        </BarChart>
      </ResponsiveContainer>
    </motion.div>
  );
}

