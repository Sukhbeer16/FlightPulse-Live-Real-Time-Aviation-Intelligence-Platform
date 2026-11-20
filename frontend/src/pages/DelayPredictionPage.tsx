// ─────────────────────────────────────────────────────────
// FlightPulse Live — Delay Prediction ML Sandbox Page
// ─────────────────────────────────────────────────────────

import React from 'react';
import { DelayPredictionTool } from '../features/intelligence/DelayPredictionTool';

export const DelayPredictionPage: React.FC = () => {
  return (
    <div className="relative w-full h-[calc(100vh-64px)] overflow-y-auto p-4 md:p-6 bg-[#070A12] max-w-6xl mx-auto">
      <DelayPredictionTool />
    </div>
  );
};
export default DelayPredictionPage;
