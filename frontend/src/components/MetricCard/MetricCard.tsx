import { motion } from 'framer-motion';
import { TrendingUp, TrendingDown, Minus, FlaskConical } from 'lucide-react';
import { fadeInUp } from '../../animations/variants';
import type { KpiMetric } from '../../types';

interface MetricCardProps {
  metric: KpiMetric;
  index?: number;
}

export function MetricCard({ metric, index = 0 }: MetricCardProps) {
  const TrendIcon =
    metric.trend === 'up' ? TrendingUp :
    metric.trend === 'down' ? TrendingDown : Minus;

  const trendColor =
    metric.id === 'anomalies'
      ? metric.trend === 'up' ? '#EF4444' : '#22C55E'
      : metric.trend === 'up' ? '#22C55E' : metric.trend === 'down' ? '#EF4444' : '#94A3B8';

  return (
    <motion.div
      custom={index}
      variants={fadeInUp}
      initial="hidden"
      animate="visible"
      className="relative overflow-hidden rounded-fp p-5 transition-colors"
      style={{
        background: '#131E2E',
        border: '1px solid rgba(241,245,249,0.07)',
      }}
      whileHover={{
        borderColor: 'rgba(37,188,235,0.2)',
        transition: { duration: 0.2 },
      }}
    >
      {/* Demo badge */}
      {metric.isDemo && (
        <div
          className="absolute top-3 right-3 flex items-center gap-1 rounded px-1.5 py-0.5"
          style={{ background: 'rgba(37,188,235,0.1)', border: '1px solid rgba(37,188,235,0.2)' }}
        >
          <FlaskConical size={8} style={{ color: '#25BCEB' }} />
          <span className="text-[9px] font-semibold tracking-wider" style={{ color: '#25BCEB' }}>
            DEMO
          </span>
        </div>
      )}

      <div className="mb-3">
        <span className="text-[11px] font-medium tracking-wider uppercase" style={{ color: '#475569' }}>
          {metric.label}
        </span>
      </div>

      <div className="flex items-end justify-between gap-2">
        <div>
          <span className="text-[28px] font-semibold leading-none" style={{ color: '#F1F5F9' }}>
            {metric.value}
          </span>
          {metric.unit && (
            <span className="ml-1.5 text-[13px]" style={{ color: '#94A3B8' }}>
              {metric.unit}
            </span>
          )}
        </div>

        {metric.change !== undefined && (
          <div
            className="flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-medium flex-shrink-0"
            style={{ background: `${trendColor}18`, color: trendColor }}
          >
            <TrendIcon size={11} />
            <span>
              {metric.trend !== 'neutral' && (metric.change > 0 ? '+' : '')}
              {metric.change}
              {metric.id === 'delay_rate' || metric.id === 'anomalies' ? '' : '%'}
            </span>
          </div>
        )}
      </div>

      {metric.changeLabel && (
        <div className="mt-2 text-[10px]" style={{ color: '#475569' }}>
          {metric.changeLabel}
        </div>
      )}
    </motion.div>
  );
}

