// ─────────────────────────────────────────────
// FlightPulse Live — Design Tokens
// ─────────────────────────────────────────────

export const colors = {
  bg: {
    primary: '#080D18',
    secondary: '#101827',
    card: '#131E2E',
    elevated: '#1A2640',
    overlay: 'rgba(8,13,24,0.85)',
  },
  accent: {
    primary: '#25BCEB',
    secondary: '#4285F4',
    primaryDim: 'rgba(37,188,235,0.15)',
    secondaryDim: 'rgba(66,133,244,0.15)',
  },
  text: {
    primary: '#F1F5F9',
    secondary: '#94A3B8',
    muted: '#475569',
    inverse: '#080D18',
  },
  border: {
    subtle: 'rgba(241,245,249,0.06)',
    default: 'rgba(241,245,249,0.1)',
    accent: 'rgba(37,188,235,0.25)',
  },
  status: {
    online: '#22C55E',
    warning: '#F59E0B',
    error: '#EF4444',
    info: '#25BCEB',
  },
  severity: {
    low: '#22C55E',
    medium: '#F59E0B',
    high: '#EF4444',
    critical: '#DC2626',
  },
} as const;

