import { useLocation } from 'react-router-dom';
import { HistoricalAssessment } from '../features/intelligence/HistoricalAssessment';
import { OperationalAlertsCenter } from '../features/alerts/OperationalAlertsCenter';
import '../styles/operations.css';

export function AnomalyDetectionPage() {
  const { pathname } = useLocation();
  return <div className="ops-page"><div className="ops-wrap">
    <header className="ops-heading"><h1>Alert center</h1><p>Review live telemetry flags and saved historical disruptions. Updated every 15 seconds.</p></header>
    <OperationalAlertsCenter/>
    {pathname !== '/alerts' && <HistoricalAssessment onAlertCreated={() => window.dispatchEvent(new Event('flightpulse-alerts-updated'))}/>}
  </div></div>;
}
export default AnomalyDetectionPage;
