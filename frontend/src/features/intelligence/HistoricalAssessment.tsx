import { useEffect, useState } from 'react';
import { API_ENDPOINTS, apiFetch } from '../../services/apiConfig';
import { fetchHistoricalFlights, type HistoricalFlightItem } from '../../services/flightsService';

interface Assessment {
  status: string;
  risk_score: number | null;
  risk_category: string | null;
  predicted_delay_score: number | null;
  anomaly_score: number | null;
  explanation: string;
  factors: { factor: string; evidence_status: string; contribution: number }[];
}

function riskInput(row: HistoricalFlightItem) {
  return {
      reporting_airline: row.reporting_airline, origin: row.origin_bts_code, destination: row.destination_bts_code,
      flight_date: row.flight_date, scheduled_departure_hhmm: row.scheduled_departure_local_hhmm,
      scheduled_arrival_hhmm: row.scheduled_arrival_local_hhmm, distance_miles: row.distance_miles,
      scheduled_elapsed_time_minutes: row.scheduled_elapsed_time_minutes,
      observed_arrival_delay_minutes: row.arrival_delay_minutes,
      flight_reference: row.source_file + '#' + row.source_row_number,
    };
}

export function HistoricalAssessment() {
  const [rows, setRows] = useState<HistoricalFlightItem[]>([]);
  const [index, select] = useState(0);
  const [attempt, retry] = useState(0);
  const [result, setResult] = useState<Assessment | null>(null);
  const [error, setError] = useState('');
  const [alertMessage, setAlertMessage] = useState('');
  const row = rows[index];
  async function createAlert() {
    setAlertMessage('Creating demonstration alert?');
    try {
      const alert = await apiFetch<{flight_reference:string}>(API_ENDPOINTS.evaluateAlert, {
        method:'POST', body:JSON.stringify({risk:riskInput(row), source:'demonstration'}),
      });
      setAlertMessage('Demonstration alert recorded for ' + alert.flight_reference);
    } catch (e) { setAlertMessage(e instanceof Error ? e.message : 'Alert unavailable'); }
  }
  useEffect(() => {
    let active = true;
    setError('');
    fetchHistoricalFlights().then(({ response }) => {
      if (!active) return;
      const eligible = response.data.filter(item => item.reporting_airline && item.origin_bts_code && item.destination_bts_code && !item.cancelled && !item.diverted);
      setRows(eligible);
      if (!eligible.length) setError('No eligible flights on this historical page.');
    }).catch(e => active && setError(e.message));
    return () => { active = false; };
  }, [attempt]);
  useEffect(() => {
    if (!row) return;
    let active = true;
    setAlertMessage('');
    setResult(null);
    setError('');
    apiFetch<Assessment>(API_ENDPOINTS.risk, { method: 'POST', body: JSON.stringify(riskInput(row)) }).then(value => active && setResult(value)).catch(e => active && setError(e.message));
    return () => { active = false; };
  }, [row]);
  return <section className="m-4 rounded-lg border border-slate-800 bg-slate-950 p-4 text-sm text-slate-200">
    <h2 className="mb-3 font-semibold">Historical flight assessment</h2>
    {rows.length > 0 && <select aria-label="Historical flight" className="bg-slate-900 p-2" value={index} onChange={e => select(Number(e.target.value))}>
      {rows.map((r,i) => <option key={r.source_row_number} value={i}>{r.flight_date} · {r.reporting_airline}{r.flight_number} · {r.origin_bts_code} to {r.destination_bts_code}</option>)}
    </select>}
    {error ? <p role="alert">{error} <button onClick={() => retry(n => n+1)}>Retry</button></p> :
      !result ? <p role="status">Loading assessment…</p> : <div className="mt-3 space-y-1">
      <p>BTS record {row.source_file} · row {row.source_row_number}</p>
      <p>Observed arrival delay {row.arrival_delay_minutes ?? 'unavailable'} min</p>
      <p>Logistic regression delay score {result.predicted_delay_score?.toFixed(3) ?? 'unavailable'}</p>
      <p>Isolation Forest anomaly score {result.anomaly_score ?? 'unavailable'}</p>
      <p>Operational risk {result.risk_score ?? 'unavailable'} / 100 · {result.risk_category}</p>
      <p>{result.explanation}</p>
      <button className="rounded bg-slate-800 p-2" disabled={alertMessage.startsWith('Creating') || alertMessage.startsWith('Demonstration alert recorded')} onClick={createAlert}>Create demonstration alert</button>
      <p role="status">{alertMessage}</p>
      <ul>{result.factors.map(f => <li key={f.factor}>{f.factor} · {f.evidence_status} · {f.contribution} points</li>)}</ul>
    </div>}
  </section>;
}
