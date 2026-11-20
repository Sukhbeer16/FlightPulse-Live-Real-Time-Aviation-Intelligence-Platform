// ─────────────────────────────────────────────────────────
// FlightPulse Live — Tactical Anomaly Detection & Alerts Center Page
// ─────────────────────────────────────────────────────────

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertsCenter } from '../features/alerts/AlertsCenter';
import { fetchFlights, fetchAlerts } from '../services/flightsService';
import type { FlightTrack, AviationAlert } from '../types';
import { API_ENDPOINTS, apiFetch } from '../services/apiConfig';

export const AnomalyDetectionPage: React.FC = () => {
  const [flights, setFlights] = useState<FlightTrack[]>([]);
  const [alerts, setAlerts] = useState<AviationAlert[]>([]);
  const [anomalyStatus, setAnomalyStatus] = useState<
    'loading' | 'available' | 'unavailable'
  >('loading');
  const [anomalyMessage, setAnomalyMessage] = useState('Checking Isolation Forest…');
  const [riskMessage, setRiskMessage] = useState('Checking demonstration risk…');
  const navigate = useNavigate();

  useEffect(() => {
    fetchFlights().then(({ flights: data }) => setFlights(data));
    fetchAlerts().then((data) => setAlerts(data));
    apiFetch<{
      status: 'available' | 'unavailable';
      model_id?: string;
      anomaly_score?: number;
      is_statistical_outlier?: boolean;
      reason?: string;
    }>(API_ENDPOINTS.anomaly, {
      method: 'POST',
      body: JSON.stringify({
        reporting_airline: 'AA',
        origin: 'JFK',
        destination: 'LAX',
        flight_date: '2024-02-01',
        scheduled_departure_hhmm: 930,
        scheduled_arrival_hhmm: 1300,
        scheduled_elapsed_time_minutes: 330,
        distance_miles: 2475,
      }),
    }).then((result) => {
      if (result.status === 'available') {
        setAnomalyStatus('available');
        setAnomalyMessage(
          `${result.model_id}: score ${result.anomaly_score?.toFixed(2)} — ${
            result.is_statistical_outlier ? 'statistical outlier' : 'within fitted nominal region'
          }`
        );
      } else {
        setAnomalyStatus('unavailable');
        setAnomalyMessage(result.reason ?? 'Anomaly model unavailable.');
      }
    }).catch((error) => {
      setAnomalyStatus('unavailable');
      setAnomalyMessage(error instanceof Error ? error.message : 'Anomaly service unavailable.');
    });
    apiFetch<{
      status: 'available' | 'unavailable';
      risk_score?: number;
      risk_category?: string;
      predicted_delay_status?: string | null;
      observed_arrival_delay_minutes?: number | null;
      anomaly_score?: number | null;
      explanation?: string;
      reason?: string;
    }>(API_ENDPOINTS.risk, {
      method: 'POST',
      body: JSON.stringify({
        reporting_airline: 'AA',
        origin: 'JFK',
        destination: 'LAX',
        flight_date: '2024-02-01',
        scheduled_departure_hhmm: 930,
        scheduled_arrival_hhmm: 1300,
        scheduled_elapsed_time_minutes: 330,
        distance_miles: 2475,
        flight_reference: 'DEMO-AA123',
        observed_arrival_delay_minutes: null,
        include_anomaly: true,
      }),
    }).then((result) => {
      if (result.status === 'available') {
        setRiskMessage(
          `Demonstration risk ${result.risk_category ?? 'unknown'} (${result.risk_score ?? 0}/100); ` +
          `predicted delay: ${result.predicted_delay_status ?? 'unknown'}`
        );
      } else {
        setRiskMessage(result.reason ?? 'Risk assessment unavailable.');
      }
    }).catch((error) => {
      setRiskMessage(error instanceof Error ? error.message : 'Risk service unavailable.');
    });
  }, []);

  const handleLocateOnMap = (flightId: string) => {
    // Navigate to live tracking
    navigate('/live-tracking');
  };

  return (
    <div className="relative w-full h-[calc(100vh-64px)] overflow-hidden flex flex-col bg-[#070A12]">
      <div className="mx-4 mt-3 rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-xs font-mono text-slate-300">
        <span
          className={`mr-2 inline-block h-2 w-2 rounded-full ${
            anomalyStatus === 'available'
              ? 'bg-cyan-400'
              : anomalyStatus === 'loading'
              ? 'bg-amber-400'
              : 'bg-red-400'
          }`}
        />
        Isolation Forest: {anomalyMessage}. This is a statistical result, not a confirmed emergency.
      </div>
      <div className="mx-4 mt-2 rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-xs font-mono text-slate-300">
        <span className="mr-2 inline-block h-2 w-2 rounded-full bg-amber-400" />
        Operational risk: {riskMessage}. Demonstration context only.
      </div>
      <AlertsCenter
        alerts={alerts}
        flights={flights}
        onLocateOnMap={handleLocateOnMap}
      />
    </div>
  );
};
export default AnomalyDetectionPage;
