import { motion } from 'framer-motion';
import { pageTransition } from '../animations/variants';
import { Settings, Database, Radio, BrainCircuit } from 'lucide-react';
import type { ConnectionStatus } from '../types';
import { DEMO_SYSTEM_STATUS } from '../data/mockData';

const STATUS_LABELS: Record<ConnectionStatus, string> = {
  connected: 'Connected',
  connecting: 'Connecting…',
  disconnected: 'Disconnected',
  error: 'Error',
};

const STATUS_COLORS: Record<ConnectionStatus, string> = {
  connected: '#22C55E',
  connecting: '#F59E0B',
  disconnected: '#475569',
  error: '#EF4444',
};

interface ServiceRowProps {
  Icon: React.ElementType;
  name: string;
  description: string;
  status: ConnectionStatus;
}

function ServiceRow({ Icon, name, description, status }: ServiceRowProps) {
  const color = STATUS_COLORS[status];
  return (
    <div
      className="flex items-center gap-4 rounded-fp-sm p-4"
      style={{ background: 'rgba(8,13,24,0.4)', border: '1px solid rgba(241,245,249,0.06)' }}
    >
      <div
        className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg"
        style={{ background: `${color}18`, border: `1px solid ${color}30` }}
      >
        <Icon size={18} style={{ color }} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-semibold mb-0.5" style={{ color: '#F1F5F9' }}>{name}</div>
        <div className="text-[11px]" style={{ color: '#475569' }}>{description}</div>
      </div>
      <div className="flex items-center gap-2">
        <span
          className="h-2 w-2 rounded-full"
          style={{ background: color }}
        />
        <span className="text-[11px] font-medium" style={{ color }}>
          {STATUS_LABELS[status]}
        </span>
      </div>
    </div>
  );
}

export function SettingsPage() {
  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="p-6 space-y-8 max-w-3xl"
    >
      <div>
        <h2 className="text-[22px] font-semibold mb-1" style={{ color: '#F1F5F9' }}>Settings</h2>
        <p className="text-[13px]" style={{ color: '#94A3B8' }}>
          Platform configuration, API connectivity and system preferences.
        </p>
      </div>

      {/* System Services */}
      <div
        className="rounded-fp p-5"
        style={{ background: '#131E2E', border: '1px solid rgba(241,245,249,0.07)' }}
      >
        <div className="flex items-center gap-2 mb-4">
          <Settings size={16} style={{ color: '#25BCEB' }} />
          <h3 className="text-[14px] font-semibold" style={{ color: '#F1F5F9' }}>System Services</h3>
        </div>
        <div className="space-y-3">
          <ServiceRow
            Icon={Radio}
            name="OpenSky Network"
            description="Real-time aircraft position data via OpenSky REST API"
            status={DEMO_SYSTEM_STATUS.opensky}
          />
          <ServiceRow
            Icon={Database}
            name="BTS Analytics API"
            description="Historical flight data from Bureau of Transportation Statistics"
            status={DEMO_SYSTEM_STATUS.btsApi}
          />
          <ServiceRow
            Icon={BrainCircuit}
            name="ML Prediction Service"
            description="Delay prediction via FastAPI ML inference endpoint"
            status={DEMO_SYSTEM_STATUS.mlService}
          />
        </div>
      </div>

      {/* API Config */}
      <div
        className="rounded-fp p-5"
        style={{ background: '#131E2E', border: '1px solid rgba(241,245,249,0.07)' }}
      >
        <h3 className="text-[14px] font-semibold mb-4" style={{ color: '#F1F5F9' }}>API Configuration</h3>
        <div className="space-y-3">
          {[
            { label: 'API Base URL', placeholder: 'http://127.0.0.1:8000', env: 'VITE_API_BASE_URL' },
          ].map(({ label, placeholder, env }) => (
            <div key={label}>
              <label className="block text-[11px] font-medium mb-1.5" style={{ color: '#94A3B8' }}>
                {label}
                <span className="ml-2 font-mono text-[10px]" style={{ color: '#475569' }}>
                  ({env})
                </span>
              </label>
              <input
                disabled
                defaultValue={placeholder}
                className="w-full rounded-fp-sm px-3 py-2 text-[12px] font-mono"
                style={{
                  background: 'rgba(8,13,24,0.6)',
                  border: '1px solid rgba(241,245,249,0.08)',
                  color: '#94A3B8',
                  cursor: 'not-allowed',
                }}
              />
              <p className="mt-1 text-[10px]" style={{ color: '#475569' }}>
                Set via .env file — do not commit API keys to source control.
              </p>
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}

