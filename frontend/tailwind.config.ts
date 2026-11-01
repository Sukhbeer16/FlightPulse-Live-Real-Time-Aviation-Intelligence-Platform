import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        fp: {
          'bg-primary': '#080D18',
          'bg-secondary': '#101827',
          'bg-card': '#131E2E',
          'bg-elevated': '#1A2640',
          'accent': '#25BCEB',
          'accent-2': '#4285F4',
          'accent-dim': 'rgba(37,188,235,0.15)',
          'text': '#F1F5F9',
          'text-2': '#94A3B8',
          'text-muted': '#475569',
          'border': 'rgba(241,245,249,0.10)',
          'border-subtle': 'rgba(241,245,249,0.06)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      borderRadius: {
        'fp': '12px',
        'fp-sm': '8px',
      },
      animation: {
        'pulse-dot': 'pulse-dot 2s ease-in-out infinite',
        'radar': 'radar-sweep 3s linear infinite',
      },
      keyframes: {
        'pulse-dot': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
        'radar-sweep': {
          from: { transform: 'rotate(0deg)' },
          to: { transform: 'rotate(360deg)' },
        },
      },
    },
  },
  plugins: [],
};

export default config;

