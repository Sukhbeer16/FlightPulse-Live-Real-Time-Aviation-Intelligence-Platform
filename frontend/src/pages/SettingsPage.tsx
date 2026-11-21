import { Link } from 'react-router-dom';
import { API_BASE_URL } from '../services/apiConfig';
import { motion } from 'framer-motion';
import { pageTransition } from '../animations/variants';
import { Settings } from 'lucide-react';

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
        <Link className="text-cyan-400" to="/system-status">View current service status</Link>
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
                value={API_BASE_URL}
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

