// ─────────────────────────────────────────────────────────
// FlightPulse Live — System Status & Telemetry Diagnostics
// ─────────────────────────────────────────────────────────

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { pageTransition } from '../animations/variants';
import { Activity, Radio, Database, BrainCircuit, Clock, RefreshCw, Server } from 'lucide-react';
import type { ConnectionStatus } from '../types';
import { checkBackendHealth } from '../services/flightsService';
import { API_ENDPOINTS, apiFetch } from '../services/apiConfig';

const STATUS_COLORS: Record<ConnectionStatus, string> = {
  connected: '#22C55E',
  connecting: '#F59E0B',
  disconnected: '#64748B',
  error: '#EF4444',
};

const STATUS_LABELS: Record<ConnectionStatus, string> = {
  connected: 'Connected',
  connecting: 'Checking',
  disconnected: 'Offline',
  error: 'Service Error',
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
      className="rounded-xl p-5 border backdrop-blur-md"
      style={{ background: '#0F172A', borderColor: `${color}30` }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon size={18} style={{ color }} />
          <span className="text-sm font-mono font-bold text-slate-100">{name}</span>
        </div>
        <span
          className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-mono font-semibold"
          style={{ background: `${color}15`, color }}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
          {STATUS_LABELS[status]}
        </span>
      </div>
      <p className="text-xs font-sans text-slate-400 leading-relaxed">{detail}</p>
    </div>
  );
}

export const SystemStatusPage: React.FC = () => {
  const [fastApiStatus, setFastApiStatus] = useState<ConnectionStatus>('connecting');
  const [backendVersion, setBackendVersion] = useState<string>('0.1.0');
  const [lastChecked, setLastChecked] = useState<string>(new Date().toLocaleTimeString());
  const [databaseStatus, setDatabaseStatus] = useState<ConnectionStatus>('connecting');
  const [modelStatus, setModelStatus] = useState<ConnectionStatus>('connecting');
  const [modelDetail, setModelDetail] = useState('Checking saved model artifacts…');

  const [provider, setProvider] = useState({state: 'checking', oauth_configured: false, last_success: null as number | null});
  const [stream, setStream] = useState('Checking processed observations');
  const checkStatus = () => {
    apiFetch<typeof provider>(API_ENDPOINTS.providerStatus).then(setProvider)
      .catch(() => setProvider({state:'unavailable',oauth_configured:false,last_success:null}));
    apiFetch<{windows: {aircraft:string; observations:number; window_start:number}[]}>(API_ENDPOINTS.streamSummary)
      .then(r => setStream(r.windows.length ? r.windows.slice(0,5).map(w =>
        w.aircraft + ' ? ' + w.observations + ' observations ? ' + new Date(w.window_start*1000).toISOString()).join(' / ') : 'Awaiting processed OpenSky observations'))
      .catch(() => setStream('Streaming summary unavailable'));
    setFastApiStatus('connecting');
    setDatabaseStatus('connecting');
    setModelStatus('connecting');
    checkBackendHealth().then((health) => {
      setFastApiStatus(health.connected ? 'connected' : 'disconnected');
      if (health.version) setBackendVersion(health.version);
      setLastChecked(new Date().toLocaleTimeString());
    });
    apiFetch<{ status: string }>(API_ENDPOINTS.databaseHealth)
      .then(() => setDatabaseStatus('connected'))
      .catch(() => setDatabaseStatus('error'));
    apiFetch<{
      models: Array<{
        model_id: string;
        status: 'available' | 'unavailable';
        algorithm: string;
      }>;
    }>(API_ENDPOINTS.models)
      .then((catalog) => {
        const available = catalog.models.filter((model) => model.status === 'available');
        setModelStatus(available.length ? 'connected' : 'disconnected');
        setModelDetail(
          `${available.length} of ${catalog.models.length} saved artifacts available: ${available
            .map((model) => model.algorithm)
            .join(', ')}`
        );
      })
      .catch(() => {
        setModelStatus('error');
        setModelDetail('Model catalog unavailable.');
      });
  };

  useEffect(() => {
    checkStatus();
  }, []);

  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="p-6 space-y-6 max-w-4xl mx-auto text-slate-100"
    >
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div>
          <h2 className="text-2xl font-mono font-bold text-slate-100">TELEMETRY &amp; SYSTEM STATUS</h2>
          <div className="flex items-center gap-2 mt-1">
            <Clock size={12} className="text-slate-500" />
            <span className="text-xs font-mono text-slate-400">Last verified: {lastChecked}</span>
          </div>
        </div>

        <button
          onClick={checkStatus}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs font-mono text-cyan-400 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>RECHECK</span>
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <StatusCard
          Icon={Server}
          name="FastAPI Backend Engine"
          status={fastApiStatus}
          detail={
            fastApiStatus === 'connected'
              ? `Connected to local FastAPI service v${backendVersion} on port 8000. `
              : 'FastAPI backend process is offline. '
          }
        />
        <StatusCard
          Icon={Radio}
          name="OpenSky Live Stream"
          status={provider.state === 'connected' ? 'connected' : 'disconnected'}
          detail={provider.state + ' ? OAuth ' + (provider.oauth_configured ? 'configured' : 'unconfigured') +
            (provider.last_success ? ' ? Last provider update ' + new Date(provider.last_success*1000).toISOString() : '')}
        />
        <StatusCard
          Icon={Database}
          name="PostgreSQL / PostGIS"
          status={databaseStatus}
          detail={
            databaseStatus === 'connected'
              ? 'Database health endpoint reports connected; SQL connectivity verified.'
              : 'Database health endpoint unavailable or returning an error.'
          }
        />
        <StatusCard
          Icon={BrainCircuit}
          name="ML Model Catalog"
          status={modelStatus}
          detail={modelDetail}
        />
      </div>
      <p>Streaming windows ? {stream}</p>
    </motion.div>
  );
};
export default SystemStatusPage;
