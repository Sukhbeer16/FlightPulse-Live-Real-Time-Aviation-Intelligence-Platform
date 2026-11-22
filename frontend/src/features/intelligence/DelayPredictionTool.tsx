import { useEffect, useState } from 'react';
import { Activity, ChartNoAxesColumnIncreasing, Plane, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { API_ENDPOINTS, apiFetch } from '../../services/apiConfig';
import { fetchHistoricalFlights, type HistoricalFlightItem } from '../../services/flightsService';
import { DelayReasons } from './DelayReasons';

const initial = {origin:'ORD', destination:'JFK', carrier:'UA', time:'14:30', arrival:'17:30', date:'2024-02-01', duration:'120', distance:'740'};
interface Prediction {
  status: string; reason?: string; model_id: string; model_score: number | null;
  threshold: number; predicted_class: string; limitations: string[];
  input_gaps?: string[];
  evaluation_metrics?: {precision?: number; recall?: number; pr_auc?: number};
  selection?: { algorithm:string; compared_models:number; metric:string; metric_value:number; reason:string; unavailable_models:string[] };
  risk_factors?: {label:string; score_change:number; description:string}[];
}
const hhmm = (value: number | null) => value == null ? '' : String(value === 2400 ? 0 : value).padStart(4,'0').replace(/(\d{2})(\d{2})/,'$1:$2');

export function DelayPredictionTool() {
  const [draft, setDraft] = useState(initial);
  const [submitted, setSubmitted] = useState<typeof initial>();
  const [mode, setMode] = useState<'dataset'|'custom'>('dataset');
  const [rows, setRows] = useState<HistoricalFlightItem[]>([]);
  const [record, setRecord] = useState<HistoricalFlightItem>();
  const [scoredRecord, setScoredRecord] = useState<HistoricalFlightItem>();
  const [result, setResult] = useState<Prediction>();
  const [error, setError] = useState('');
  const [dataError, setDataError] = useState('');
  const [loading, setLoading] = useState(false);
  const [attempt, retry] = useState(0);
  const [airportSearch, setAirportSearch] = useState('ORD');
  const [sourceOrigin, setSourceOrigin] = useState('ORD');
  const [onlyDelayed, setOnlyDelayed] = useState(false);
  const update = (name: keyof typeof initial, value: string) => setDraft(s => ({...s, [name]:value}));
  function choose(row: HistoricalFlightItem) {
    setRecord(row); setDraft({origin:row.origin_bts_code ?? '', destination:row.destination_bts_code ?? '',
      carrier:row.reporting_airline ?? '', date:row.flight_date, time:hhmm(row.scheduled_departure_local_hhmm),
      arrival:hhmm(row.scheduled_arrival_local_hhmm), duration:String(row.scheduled_elapsed_time_minutes ?? ''), distance:String(row.distance_miles ?? '')});
  }
  useEffect(() => {
    let active = true;
    setDataError('');
    setRows([]);setRecord(undefined);
    fetchHistoricalFlights({pageSize:100, origin:sourceOrigin||undefined, delayed:onlyDelayed?true:undefined}).then(({response}) => {
      if (!active) return;
      const eligible = response.data.filter(r=>!r.cancelled&&!r.diverted);
      setRows(eligible);
      if (eligible[0]) choose(eligible[0]);
      else setDataError('No eligible records found. Use a custom schedule.');
    }).catch(e=>{if(active)setDataError(e.message);});
    return ()=>{active=false;};
  },[attempt,sourceOrigin,onlyDelayed]);
  useEffect(() => {
    if (!submitted) return;
    const controller = new AbortController();
    setError(''); setResult(undefined); setLoading(true);
    apiFetch<Prediction>(API_ENDPOINTS.delayPrediction(), {
      method:'POST', signal:controller.signal,
      body:JSON.stringify({reporting_airline:submitted.carrier, origin:submitted.origin, destination:submitted.destination,
        flight_date:submitted.date, scheduled_departure_hhmm:submitted.time ? Number(submitted.time.replace(':','')) : null,
        scheduled_arrival_hhmm:submitted.arrival ? Number(submitted.arrival.replace(':','')) : null,
        scheduled_elapsed_time_minutes:submitted.duration ? Number(submitted.duration) : null,
        distance_miles:submitted.distance ? Number(submitted.distance) : null}),
    }).then(data=>{if(!controller.signal.aborted){if(data.status==='available')setResult(data);else setError(data.reason || 'Prediction unavailable.');}})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[submitted]);
  const shown = submitted ?? draft;
  return <div className="ops-delay-grid">
    <section className="ops-card">
      <header className="ops-card-heading"><span className="ops-icon"><SlidersHorizontal size={21}/></span><div><h2>Choose a flight</h2><p>One forecast, selected from four models</p></div></header>
      <div className="ops-tabs">{(['dataset','custom'] as const).map(m=><button key={m} aria-pressed={mode===m} onClick={()=>{setMode(m);if(m==='dataset'&&record)choose(record);}}>{m==='dataset'?'Dataset flight':'Custom schedule'}</button>)}</div>
      {mode==='dataset' && <><form className="ops-source-search" onSubmit={e=>{e.preventDefault();setSourceOrigin(airportSearch);}}><label>Departure airport<input aria-label="Forecast dataset airport" maxLength={3} pattern="[A-Z0-9]{3}" value={airportSearch} onChange={e=>setAirportSearch(e.target.value.toUpperCase())} placeholder="Any airport"/></label><button className="ops-secondary">Find flights</button></form><label className="ops-checkbox"><input type="checkbox" checked={onlyDelayed} onChange={e=>setOnlyDelayed(e.target.checked)}/>Only recorded delays over 15 minutes</label>
        {dataError ? <p className="ops-error">{dataError} <button onClick={()=>retry(n=>n+1)}>Retry</button></p> : <label className="ops-record-picker">First 100 matching BTS records<select aria-label="Dataset flight" value={record?.source_file+'#'+record?.source_row_number} onChange={e=>{const r=rows.find(r=>r.source_file+'#'+r.source_row_number===e.target.value);if(r)choose(r);}}>
        {!rows.length&&<option>Loading dataset flights…</option>}{rows.map(r=><option key={r.source_file+r.source_row_number} value={r.source_file+'#'+r.source_row_number}>{r.airline_name ?? r.reporting_airline} · {r.reporting_airline}{r.flight_number} · {r.origin_bts_code}–{r.destination_bts_code} · {r.flight_date}</option>)}</select></label>}</>}
      <form className="ops-form" onSubmit={e=>{e.preventDefault();setSubmitted({...draft});setScoredRecord(mode==='dataset'?record:undefined);}}>
        {mode==='custom' && <p className="ops-note">This research model supports January–February 2024 dates and carriers and airports seen in its training data.</p>}
        <fieldset disabled={mode==='dataset'} className="ops-fields">
          {(['origin','destination','carrier'] as const).map(key=><label key={key}>{key==='carrier'?'Reporting airline code':key==='origin'?'Departure airport':'Arrival airport'}<input required pattern={key==='carrier'?'[A-Z0-9]{1,8}':'[A-Z0-9]{3}'} maxLength={key==='carrier'?8:3} value={draft[key]} onChange={e=>update(key,e.target.value.toUpperCase())}/></label>)}
          <label>Flight date<input required type="date" value={draft.date} onChange={e=>update('date',e.target.value)}/></label>
          <label>Departure · local<input type="time" value={draft.time} onChange={e=>update('time',e.target.value)}/></label>
          <label>Arrival · local<input type="time" value={draft.arrival} onChange={e=>update('arrival',e.target.value)}/></label>
          <label>Duration · minutes<input type="number" min="0" max="2000" value={draft.duration} onChange={e=>update('duration',e.target.value)}/></label>
          <label>Distance · miles<input type="number" min="0" max="20000" value={draft.distance} onChange={e=>update('distance',e.target.value)}/></label>
        </fieldset>
        <div className="ops-selection-note"><ShieldCheck size={19}/><span>Automatic model selection<br/><small>Ranked by held-out validation F2, never by the highest flight score.</small></span></div>
        <button className="ops-primary" disabled={loading || draft.origin===draft.destination || (mode==='dataset'&&!record)}><Activity size={17}/>{loading?'Calculating forecast…':'Get best-model forecast'}</button>
      </form>
    </section>
    <div className="ops-output">
      <section className="ops-ticket"><div className="ops-ticket-top"><span><Plane size={18}/>{scoredRecord && submitted ? scoredRecord.reporting_airline+String(scoredRecord.flight_number) : 'Flight forecast'}</span><b>{shown.carrier}</b></div>
        <div className="ops-route"><div><small>FROM</small><strong>{shown.origin}</strong></div><div className="ops-route-line"><Plane size={22}/></div><div><small>TO</small><strong>{shown.destination}</strong></div></div>
        <div className="ops-ticket-foot"><span>{shown.date}</span><span>{shown.time || 'Unknown'} local departure</span></div></section>
      <section className="ops-card ops-result" aria-live="polite"><header className="ops-card-heading"><span className="ops-icon"><ChartNoAxesColumnIncreasing size={21}/></span><div><h2>Arrival outlook</h2><p>Arrival delay over 15 minutes</p></div></header>
        {loading ? <p className="ops-notice">Scoring the flight with the validation winner…</p> : error ? <p role="alert" className="ops-error">{error}</p> : result && result.model_score != null ? <>
          <span className={'ops-pill '+(result.predicted_class==='delayed'?'amber':'')}>{result.predicted_class==='delayed'?'Elevated delay risk':'Lower delay risk'}</span>
          <div className="ops-score-head"><strong>{result.model_score.toFixed(3)}<small> / 1.000</small></strong></div>
          <div className="ops-meter"><span style={{width:100*result.model_score+'%'}}/><i style={{left:100*result.threshold+'%'}}/></div>
          <p className="ops-note">Relative model score · threshold {result.threshold.toFixed(2)}. This is not a calibrated probability or an estimated number of delay minutes.</p>
          {result.input_gaps?.length ? <p className="ops-error">Estimated from training medians: {result.input_gaps.join(', ')}.</p> : null}
          {result.selection && <div className="ops-selection-note"><ShieldCheck size={20}/><span>{result.selection.algorithm} selected from {result.selection.compared_models} models<small>{result.selection.metric}: {result.selection.metric_value.toFixed(3)}.{result.selection.unavailable_models.length>0?' Some higher-ranked artifacts are unavailable.':''}</small></span></div>}
          <h3>What influenced the forecast?</h3>
          {result.risk_factors?.length ? result.risk_factors.slice(0,4).map(f=><div className="ops-cause" key={f.label}><span>{f.label}</span><b>{f.score_change>=0?'+':''}{f.score_change.toFixed(3)}</b></div>) : <p className="ops-note">Feature-level explanation unavailable for this artifact.</p>}
          <p className="ops-note">Score changes compare each input with an unknown category or training median. They are model sensitivities, not confirmed delay causes.</p>
          <details className="ops-disclosure"><summary>Model quality and limitations</summary>
            {result.evaluation_metrics?.precision != null && result.evaluation_metrics.recall != null && <p>Held-out February 2024 test: precision {(100 * result.evaluation_metrics.precision).toFixed(1)}%, recall {(100 * result.evaluation_metrics.recall).toFixed(1)}%{result.evaluation_metrics.pr_auc != null ? `, PR-AUC ${result.evaluation_metrics.pr_auc.toFixed(3)}` : ''}. This model cannot predict every delay.</p>}
            <p>{result.selection?.reason}</p>{result.limitations.map(l=><p key={l}>{l}</p>)}<small>{result.model_id}</small></details>
        </> : <p className="ops-notice">Select a dataset flight or enter a schedule, then run your forecast.</p>}
      </section>
      {scoredRecord && <section className="ops-card"><DelayReasons row={scoredRecord}/></section>}
    </div>
  </div>;
}
