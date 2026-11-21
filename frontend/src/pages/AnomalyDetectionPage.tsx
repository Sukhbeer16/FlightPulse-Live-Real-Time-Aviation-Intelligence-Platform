import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { HistoricalAssessment } from '../features/intelligence/HistoricalAssessment';
import { AlertsCenter } from '../features/alerts/AlertsCenter';
import { fetchAlerts } from '../services/flightsService';
import type { AviationAlert } from '../types';

export function AnomalyDetectionPage() {
  const [alerts, setAlerts] = useState<AviationAlert[]>([]);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const { pathname } = useLocation();
  useEffect(() => {
    fetchAlerts().then(setAlerts).catch(e => setError(e.message));
  }, []);
  return <main>
    {pathname !== '/alerts' && <HistoricalAssessment />}
    {error && <p role="alert">{error}</p>}
    <AlertsCenter alerts={alerts} flights={[]} onLocateOnMap={() => navigate('/live-tracking')} />
  </main>;
}
export default AnomalyDetectionPage;
