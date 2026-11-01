import { motion } from 'framer-motion';
import { pageTransition } from '../animations/variants';
import { MetricCard } from '../components/MetricCard/MetricCard';
import { LiveMap } from '../components/LiveMap/LiveMap';
import { DelayTrendChart, AirlinePerformanceChart, FlightActivityChart } from '../components/Charts/Charts';
import { ActivityFeed } from '../components/ActivityFeed/ActivityFeed';
import { DEMO_KPI_METRICS, DEMO_AIRCRAFT } from '../data/mockData';

export function OverviewPage() {
  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="p-6 space-y-8"
    >
      {/* ── Welcome ─────────────────────────── */}
      <div>
        <h2 className="text-[22px] font-semibold mb-1" style={{ color: '#F1F5F9' }}>
          Aviation Intelligence Overview
        </h2>
        <p className="text-[13px]" style={{ color: '#94A3B8' }}>
          Monitor aircraft activity, analyse flight performance and explore predictive insights.
        </p>
      </div>

      {/* ── KPI Metrics ─────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {DEMO_KPI_METRICS.map((metric, i) => (
          <MetricCard key={metric.id} metric={metric} index={i} />
        ))}
      </div>

      {/* ── Live Map ────────────────────────── */}
      <section>
        <div className="flex items-center gap-3 mb-4">
          <h3 className="text-[15px] font-semibold" style={{ color: '#F1F5F9' }}>
            Live Aircraft Activity
          </h3>
          <div
            className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-medium"
            style={{ background: 'rgba(37,188,235,0.1)', color: '#25BCEB', border: '1px solid rgba(37,188,235,0.2)' }}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse-dot" />
            DEMO MODE — OpenSky integration pending
          </div>
        </div>
        <div style={{ height: 460 }}>
          <LiveMap aircraft={DEMO_AIRCRAFT} />
        </div>
      </section>

      {/* ── Historical Analytics ─────────────── */}
      <section>
        <div className="flex items-center gap-3 mb-4">
          <h3 className="text-[15px] font-semibold" style={{ color: '#F1F5F9' }}>
            Historical Analytics
          </h3>
          <span className="text-[11px]" style={{ color: '#475569' }}>
            BTS data — Jan & Feb 2024 ingested
          </span>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <DelayTrendChart />
          <AirlinePerformanceChart />
        </div>
        <div className="mt-4">
          <FlightActivityChart />
        </div>
      </section>

      {/* ── Activity Feed ──────────────────── */}
      <section>
        <ActivityFeed />
      </section>
    </motion.div>
  );
}

