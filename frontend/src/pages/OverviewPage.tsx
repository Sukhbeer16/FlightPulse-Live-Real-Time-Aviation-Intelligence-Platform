// ─────────────────────────────────────────────────────────
// FlightPulse Live — Overview Page (Aviation Intelligence Dashboard)
// ─────────────────────────────────────────────────────────

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { IntelligenceDashboard } from '../features/intelligence/IntelligenceDashboard';
import { FlightDetailDrawer } from '../features/flights/FlightDetailDrawer';
import { fetchHistoricalFlights, fetchAlerts } from '../services/flightsService';
import type { FlightTrack, AviationAlert } from '../types';

export const OverviewPage: React.FC = () => {
  const [flights, setFlights] = useState<FlightTrack[]>([]);
  const [alerts, setAlerts] = useState<AviationAlert[]>([]);
  const [selectedFlight, setSelectedFlight] = useState<FlightTrack | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchHistoricalFlights({ page: 1, pageSize: 50 }).then(({ flights: data }) => setFlights(data));
    fetchAlerts().then((data) => setAlerts(data));
  }, []);

  return (
    <div className="relative w-full h-[calc(100vh-64px)] overflow-hidden flex flex-col bg-[#070A12]">
      <IntelligenceDashboard
        flights={flights}
        alerts={alerts}
        onSelectFlight={(flight) => setSelectedFlight(flight)}
      />

      <FlightDetailDrawer
        flight={selectedFlight}
        onClose={() => setSelectedFlight(null)}
      />
    </div>
  );
};
export default OverviewPage;
