import { motion } from 'framer-motion';
import { pageTransition } from '../animations/variants';
import { Activity, Radio, Database, BrainCircuit, Clock } from 'lucide-react';
import type { ConnectionStatus } from '../types';
import { DEMO_SYSTEM_STATUS } from '../data/mockData';

const STATUS_COLORS: Record<ConnectionStatus, string> = {
  connected: '#22C55E',
  connecting: '#F59E0B',
  disconnected: '#475569',
  error: '#EF4444',
};

const STATUS_LABELS: Record<ConnectionStatus, string> = {
  connected: 'Connected',
  connecting: 'Connecting',
  disconnected: 'Offline',
  error: 'Error',
};

interface StatusCardProps {
  Icon: React.ElementType;
  name: string;
  status: ConnectionStatus;
  detail: string;
}

function StatusCard({ Icon, name, status, detail }: StatusCardProps) {
  const color = STATUS_COLORS[status];
  return (
    <div
      className="rounded-fp p-5"
      style={{ background: '#131E2E', border: `1px solid ${color}25` }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon size={16} style={{ color }} />
          <span className="text-[13px] font-semibold" style={{ color: '#F1F5F9' }}>{name}</span>
        </div>
        <span
          className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold"
          style={{ background: `${color}15`, color }}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
          {STATUS_LABELS[status]}
        </span>
      </div>
      <p className="text-[11px]" style={{ color: '#475569' }}>{detail}</p>
    </div>
  );
}

export function SystemStatusPage() {
  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="p-6 space-y-8 max-w-3xl"
    >
      <div>
        <h2 className="text-[22px] font-semibold mb-1" style={{ color: '#F1F5F9' }}>System Status</h2>
        <div className="flex items-center gap-2">
          <Clock size={12} style={{ color: '#475569' }} />
          <span className="text-[11px]" style={{ color: '#475569' }}>
            Last checked: {new Date(DEMO_SYSTEM_STATUS.lastUpdated).toLocaleTimeString()}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <StatusCard
          Icon={Radio}
          name="OpenSky Network"
          status={DEMO_SYSTEM_STATUS.opensky}
          detail="Real-time aircraft tracking API. Will be connected when OpenSky integration is implemented."
        />
        <StatusCard
          Icon={Database}
          name="BTS Analytics"
          status={DEMO_SYSTEM_STATUS.btsApi}
          detail="Bureau of Transportation Statistics historical data. Jan–Feb 2024 data ingested via PySpark pipelines."
        />
        <StatusCard
          Icon={BrainCircuit}
          name="ML Service"
          status={DEMO_SYSTEM_STATUS.mlService}
          detail="FastAPI prediction endpoint for delay models (LR, DT, RF, XGBoost). Pending backend deployment."
        />
        <StatusCard
          Icon={Activity}
          name="Anomaly Engine"
          status="disconnected"
          detail="Isolation Forest anomaly detection service. Integration planned after OpenSky connection is live."
        />
      </div>
    </motion.div>
  );
}

