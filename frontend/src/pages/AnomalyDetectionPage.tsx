import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { HistoricalAssessment } from '../features/intelligence/HistoricalAssessment';
import { AlertsCenter } from '../features/alerts/AlertsCenter';
import { fetchAlerts } from '../services/flightsService';
import type { AviationAlert } from '../types';
import '../styles/operations.css';

export function AnomalyDetectionPage() {
  const [alerts, setAlerts] = useState<AviationAlert[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, refresh] = useState(0);
  const { pathname } = useLocation();
  useEffect(()=>{
    const update=()=>refresh(n=>n+1);
    window.addEventListener('flightpulse-alerts-updated',update);
    return ()=>window.removeEventListener('flightpulse-alerts-updated',update);
  },[]);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    fetchAlerts().then(data => { if (active) setAlerts(data); })
      .catch(e => { if (active) setError(e.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [attempt]);
  return <div className="ops-page"><div className="ops-wrap">
    <header className="ops-heading"><h1>Alert center</h1><p>Review live telemetry flags and saved historical disruptions. Updated every 15 seconds.</p></header>
    <AlertsCenter alerts={alerts} error={error} loading={loading} onRefresh={() => refresh(n => n+1)}/>
    {pathname !== '/alerts' && <HistoricalAssessment onAlertCreated={() => refresh(n => n+1)}/>}
  </div></div>;
}
export default AnomalyDetectionPage;
