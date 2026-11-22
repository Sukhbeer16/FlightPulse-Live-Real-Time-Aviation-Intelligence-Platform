import { useEffect, useState } from 'react';
import { IntelligenceDashboard } from '../features/intelligence/IntelligenceDashboard';
import { FlightDetailDrawer } from '../features/flights/FlightDetailDrawer';
import { fetchHistoricalFlights, fetchAlerts } from '../services/flightsService';
import type { FlightTrack, AviationAlert } from '../types';
import '../styles/analytics.css';

export function OverviewPage() {
  const [flights, setFlights] = useState<FlightTrack[]>([]);
  const [alerts, setAlerts] = useState<AviationAlert[]>([]);
  const [selected, setSelected] = useState<FlightTrack | null>(null);
  const [flightsStatus, setFlightsStatus] = useState('Loading flights…');
  const [alertsStatus, setAlertsStatus] = useState('Loading alerts…');

  useEffect(() => {
    let active = true;
    fetchHistoricalFlights({ page: 1, pageSize: 7, dateFrom: '2024-01-01', dateTo: '2024-01-31' }).then(({ flights }) => {
      if (active) { setFlights(flights); setFlightsStatus('No records in this reporting period.'); }
    }).catch(() => active && setFlightsStatus('The archive is unavailable.'));
    fetchAlerts().then(data => {
      if (active) { setAlerts(data); setAlertsStatus('No demonstration alerts recorded.'); }
    }).catch(() => active && setAlertsStatus('The alert log is unavailable.'));
    return () => { active = false; };
  }, []);

  return <div className="analysis-page">
    <IntelligenceDashboard flights={flights} alerts={alerts} flightsStatus={flightsStatus}
      alertsStatus={alertsStatus} onSelectFlight={setSelected} />
    {selected && <div className="analysis-drawer"><FlightDetailDrawer flight={selected} onClose={() => setSelected(null)} /></div>}
  </div>;
}
export default OverviewPage;
