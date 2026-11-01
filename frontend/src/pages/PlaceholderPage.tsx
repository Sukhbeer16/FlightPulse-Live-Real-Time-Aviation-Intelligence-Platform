import { motion } from 'framer-motion';
import { pageTransition } from '../animations/variants';
import type { LucideIcon } from 'lucide-react';

interface PlaceholderPageProps {
  title: string;
  description: string;
  Icon: LucideIcon;
  status?: string;
  features?: string[];
}

export function PlaceholderPage({
  title,
  description,
  Icon,
  status = 'In Development',
  features = [],
}: PlaceholderPageProps) {
  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="flex flex-col items-center justify-center min-h-[calc(100vh-60px)] p-6"
    >
      <div
        className="w-full max-w-lg rounded-fp p-10 text-center"
        style={{
          background: '#131E2E',
          border: '1px solid rgba(241,245,249,0.08)',
        }}
      >
        {/* Icon */}
        <div
          className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl"
          style={{
            background: 'linear-gradient(135deg, rgba(37,188,235,0.15), rgba(66,133,244,0.15))',
            border: '1px solid rgba(37,188,235,0.25)',
          }}
        >
          <Icon size={28} style={{ color: '#25BCEB' }} />
        </div>

        {/* Status badge */}
        <div
          className="mx-auto mb-4 inline-flex items-center gap-2 rounded-full px-3 py-1"
          style={{
            background: 'rgba(245,158,11,0.12)',
            border: '1px solid rgba(245,158,11,0.25)',
          }}
        >
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: '#F59E0B' }}
          />
          <span className="text-[10px] font-semibold tracking-wider uppercase" style={{ color: '#F59E0B' }}>
            {status}
          </span>
        </div>

        <h2 className="text-[20px] font-semibold mb-3" style={{ color: '#F1F5F9' }}>
          {title}
        </h2>
        <p className="text-[13px] leading-relaxed mb-6" style={{ color: '#94A3B8' }}>
          {description}
        </p>

        {/* Feature list */}
        {features.length > 0 && (
          <div
            className="text-left rounded-fp-sm p-4 space-y-2"
            style={{ background: 'rgba(8,13,24,0.4)', border: '1px solid rgba(241,245,249,0.06)' }}
          >
            <div className="text-[10px] font-semibold tracking-wider uppercase mb-3" style={{ color: '#475569' }}>
              Planned Features
            </div>
            {features.map((f) => (
              <div key={f} className="flex items-center gap-2">
                <span
                  className="h-1 w-1 rounded-full flex-shrink-0"
                  style={{ background: '#25BCEB' }}
                />
                <span className="text-[12px]" style={{ color: '#94A3B8' }}>{f}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}

