import { useEffect, useState } from 'react';
import { API_ENDPOINTS, apiFetch } from '../../services/apiConfig';
import type { HistoricalFlightResponse } from '../../services/flightsService';

const fields = [
  ['flight_number','Flight number','text'], ['airline_code','Carrier','text'],
  ['origin','BTS origin','text'], ['destination','BTS destination','text'],
  ['flight_date','Flight date','date'], ['date_from','From','date'], ['date_to','Through','date'],
  ['departure_delay_min','Minimum departure delay','number'], ['departure_delay_max','Maximum departure delay','number'],
  ['arrival_delay_min','Minimum arrival delay','number'], ['arrival_delay_max','Maximum arrival delay','number'],
];
export function HistoricalSearch() {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [attempt, retry] = useState(0);
  const [response, setResponse] = useState<HistoricalFlightResponse | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setError('');
    setResponse(null);
    apiFetch<HistoricalFlightResponse>(API_ENDPOINTS.historicalFlights + '?' + query + '&page=' + page + '&page_size=10')
      .then(r => active && setResponse(r)).catch(e => active && setError(e.message));
    return () => { active = false; };
  }, [page, query, attempt]);
  return <section className="rounded-xl border border-slate-800 p-4 space-y-3"><h2>BTS flight search</h2>
    <form className="flex flex-wrap items-end gap-3 text-xs" onSubmit={e => {
      e.preventDefault();
      const params = new URLSearchParams();
      new FormData(e.currentTarget).forEach((v,k) => { if (String(v).trim()) params.set(k,String(v).trim()); });
      setPage(1); setQuery(params.toString()); retry(n=>n+1);
    }}>
      {fields.map(([key,label,type]) => <label key={key}>{label}<input name={key} type={type} className="block w-32 bg-slate-900 p-1" /></label>)}
      {['delayed','cancelled','diverted'].map(key => <label key={key}>{key}<select className="block bg-slate-900" name={key}><option value="">Any</option><option value="true">Yes</option><option value="false">No</option></select></label>)}
      <label>Sort by<select name="sort_by" className="block bg-slate-900">{['source_row','flight_date','flight_number','departure_delay','arrival_delay'].map(k=><option key={k}>{k}</option>)}</select></label>
      <select aria-label="Sort direction" name="sort_order" className="bg-slate-900"><option>asc</option><option>desc</option></select>
      <button className="rounded bg-cyan-900 px-3 py-1">Search records</button>
    </form>
    {error ? <p role="alert">{error} <button onClick={()=>retry(n=>n+1)}>Retry</button></p> : !response ? <p>Loading records…</p> :
      <><p>{response.pagination.total.toLocaleString()} matching records</p>
      <table className="w-full text-left text-sm"><thead><tr>{['Date','Flight','BTS origin','BTS destination','Arrival delay (min)'].map(k=><th key={k}>{k}</th>)}</tr></thead>
      <tbody>{response.data.map(r=><tr key={r.source_file+r.source_row_number}><td>{r.flight_date}</td><td>{r.reporting_airline}{r.flight_number}</td><td>{r.origin_bts_code}</td><td>{r.destination_bts_code}</td><td>{r.arrival_delay_minutes ?? 'Unavailable'}</td></tr>)}</tbody></table>
      <div className="flex gap-3"><button disabled={!response.pagination.has_previous} onClick={()=>setPage(p=>p-1)}>Previous</button><span>Page {page}</span><button disabled={!response.pagination.has_next} onClick={()=>setPage(p=>p+1)}>Next</button></div></>}
  </section>;
}
