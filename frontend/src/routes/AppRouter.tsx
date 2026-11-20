import { Routes, Route } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';
import { AppLayout } from '../layouts/AppLayout';
import { OverviewPage } from '../pages/OverviewPage';
import { LiveTrackingPage } from '../pages/LiveTrackingPage';
import { DelayPredictionPage } from '../pages/DelayPredictionPage';
import { AnomalyDetectionPage } from '../pages/AnomalyDetectionPage';
import { HistoricalAnalyticsPage } from '../pages/HistoricalAnalyticsPage';
import { DisruptionPage } from '../pages/DisruptionPage';
import { AssistantPage } from '../pages/AssistantPage';
import { SettingsPage } from '../pages/SettingsPage';
import { SystemStatusPage } from '../pages/SystemStatusPage';

export function AppRouter() {
  return (
    <AnimatePresence mode="wait">
      <Routes>
        <Route element={<AppLayout />}>
          {/* Primary screen is Live Flight Tracker */}
          <Route index element={<LiveTrackingPage />} />
          <Route path="live-tracking" element={<LiveTrackingPage />} />
          <Route path="overview" element={<OverviewPage />} />
          <Route path="intelligence" element={<OverviewPage />} />
          <Route path="delay-prediction" element={<DelayPredictionPage />} />
          <Route path="anomaly-detection" element={<AnomalyDetectionPage />} />
          <Route path="alerts" element={<AnomalyDetectionPage />} />
          <Route path="historical" element={<HistoricalAnalyticsPage />} />
          <Route path="disruption" element={<DisruptionPage />} />
          <Route path="assistant" element={<AssistantPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="system-status" element={<SystemStatusPage />} />
        </Route>
      </Routes>
    </AnimatePresence>
  );
}
