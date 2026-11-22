import { useEffect, useRef, useState } from 'react';
import { BellPlus, Fingerprint, Plane } from 'lucide-react';
import { API_ENDPOINTS, apiFetch } from '../../services/apiConfig';
import { fetchHistoricalFlights, type HistoricalFlightItem } from '../../services/flightsService';
import { DelayReasons } from './DelayReasons';

interface Assessment {
  status: string; risk_score: number | null; risk_category: string | null;
  predicted_delay_score: number | null; anomaly_score: number | null; explanation: string;
  factors: { factor: string; evidence_status: string; contribution: number }[];
}

function riskInput(row: HistoricalFlightItem) {
  return {
    reporting_airline: row.reporting_airline, origin: row.origin_bts_code, destination: row.destination_bts_code,
    flight_date: row.flight_date, scheduled_departure_hhmm: row.scheduled_departure_local_hhmm,
    scheduled_arrival_hhmm: row.scheduled_arrival_local_hhmm, distance_miles: row.distance_miles,
    scheduled_elapsed_time_minutes: row.scheduled_elapsed_time_minutes, observed_arrival_delay_minutes: row.arrival_delay_minutes,
    flight_reference: row.source_file + '#' + row.source_row_number,
  };
}

export function HistoricalAssessment({onAlertCreated}: {onAlertCreated?: () => void}) {
  const [rows, setRows] = useState<HistoricalFlightItem[]>([]);
  const [index, select] = useState(0);
  const [attempt, retry] = useState(0);
  const [result, setResult] = useState<Assessment | null>(null);
  const [error, setError] = useState('');
  const [alertMessage, setAlertMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const row = rows[index];
  const selectedRow = useRef(row);
  selectedRow.current = row;

  async function createAlert() {
    if (!row || saving || saved) return;
    setSaving(true); setAlertMessage('');
    try {
      const alert = await apiFetch<{flight_reference:string}>(API_ENDPOINTS.historicalAlert, {
        method:'POST', body:JSON.stringify({source_file:row.source_file, source_row_number:row.source_row_number}),
      });
      if (selectedRow.current === row) {
        setSaved(true);
        setAlertMessage('Historical alert saved to the inbox for ' + alert.flight_reference);
      }
      onAlertCreated?.();
    } catch (e) {
      if (selectedRow.current === row) setAlertMessage(e instanceof Error ? e.message : 'Alert unavailable.');
    } finally { if (selectedRow.current === row) setSaving(false); }
  }
  useEffect(() => {
    let active = true;
    setError(''); setResult(null); setRows([]);
    fetchHistoricalFlights({delayed:true}).then(({ response }) => {
      if (!active) return;
      const eligible = response.data.filter(item => item.reporting_airline && item.origin_bts_code && item.destination_bts_code && !item.cancelled && !item.diverted);
      setRows(eligible); select(0);
      if (!eligible.length) setError('No eligible flights were found on this historical page.');
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [attempt]);
  useEffect(() => {
    if (!row) return;
    const controller = new AbortController();
    setAlertMessage(''); setSaved(false); setSaving(false); setResult(null); setError('');
    apiFetch<Assessment>(API_ENDPOINTS.risk, { method:'POST', signal:controller.signal, body:JSON.stringify(riskInput(row)) })
      .then(value => { if (!controller.signal.aborted) setResult(value); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [row]);

  return <section className="ops-card ops-assessment">
    <header className="ops-card-heading"><span className="ops-icon"><Fingerprint size={21}/></span><div><h2>Historical flight assessment</h2><p>Observed arrival performance and model evidence</p></div></header>
    {rows.length > 0 && <label className="ops-record-picker"><span><Plane size={15}/> Historical flight</span><select aria-label="Historical flight" value={index} onChange={e => select(Number(e.target.value))}>
      {rows.map((r,i) => <option key={r.source_file+r.source_row_number} value={i}>{r.reporting_airline}{r.flight_number} · {r.origin_bts_code} to {r.destination_bts_code} · {r.flight_date}</option>)}
    </select></label>}
    {error ? <p role="alert" className="ops-error">{error} <button className="ops-text-action" onClick={() => retry(n => n+1)}>Retry</button></p> :
      !row || !result ? <p className="ops-notice" role="status">Loading assessment…</p> : <>
        <dl className="ops-metrics">{[
          ['Operational risk', result.risk_score?.toFixed(1) ?? '—', result.risk_category || 'Unavailable'],
          ['Observed arrival delay', row.arrival_delay_minutes ?? '—', 'minutes'],
          ['Selected model delay score', result.predicted_delay_score?.toFixed(3) ?? '—', 'relative score'],
          ['Isolation Forest anomaly score', result.anomaly_score?.toFixed(3) ?? '—', 'model score'],
        ].map(([label,value,unit]) => <div key={label}><dt>{label}</dt><dd>{value}</dd><small>{unit}</small></div>)}</dl>
        <div className="ops-assess-footer"><div><details className="ops-disclosure"><summary>Assessment evidence</summary><p>{result.explanation}</p>{result.factors.map(f=><div key={f.factor}><span>{f.factor} · {f.evidence_status}</span><b>{f.contribution} pts</b></div>)}<p>BTS source · {row.source_file}, row {row.source_row_number}</p></details></div>
        <button className="ops-secondary" disabled={saving || saved} onClick={createAlert}><BellPlus size={16}/>{saving ? 'Recording…' : saved ? 'Alert recorded' : 'Save historical alert'}</button></div>
        <DelayReasons row={row}/>
        {alertMessage && <p className="ops-note" role="status">{alertMessage}</p>}
      </>}
  </section>;
}
