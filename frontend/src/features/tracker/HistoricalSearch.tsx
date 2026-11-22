import { useEffect, useState } from 'react';
import { Search, SlidersHorizontal } from 'lucide-react';
import { API_ENDPOINTS, apiFetch } from '../../services/apiConfig';
import type { HistoricalFlightResponse, HistoricalFlightItem } from '../../services/flightsService';
import { reportingMonth } from '../intelligence/historicalReports';

const fields = [
  ['flight_number','Flight number','text','e.g. 120'], ['airline_code','Carrier','text','e.g. UA'],
  ['origin','BTS origin','text','e.g. JFK'], ['destination','BTS destination','text','e.g. SFO'],
  ['flight_date','Flight date','date',''],
];
const advanced = [
  ['date_from','From date','date'], ['date_to','Through date','date'],
  ['departure_delay_min','Minimum departure delay','number'], ['departure_delay_max','Maximum departure delay','number'],
  ['arrival_delay_min','Minimum arrival delay','number'], ['arrival_delay_max','Maximum arrival delay','number'],
];
function status(r: HistoricalFlightItem) {
  if (r.cancelled === 1) return 'Cancelled';
  if (r.diverted === 1) return 'Diverted';
  if (r.arrival_delay_minutes == null) return 'Unavailable';
  if (r.arrival_delay_minutes > 15) return 'Delayed';
  return 'On time';
}
export function HistoricalSearch() {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [attempt,retry] = useState(0);
  const [response, setResponse] = useState<HistoricalFlightResponse | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    setResponse(null);
    const params = new URLSearchParams(query);
    params.set('page', String(page)); params.set('page_size','10');
    apiFetch<HistoricalFlightResponse>(API_ENDPOINTS.historicalFlights + '?' + params, {signal:controller.signal})
      .then(r => { if (!controller.signal.aborted) setResponse(r); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [page, query, attempt]);
  return <section className="analysis-card archive-search">
    <div className="analysis-card-head"><div><h2>Search records</h2><p>Airport and carrier codes follow the BTS reporting standard.</p></div><Search size={22} /></div>
    <form onReset={() => { setQuery(''); setPage(1); }} onSubmit={e => {
      e.preventDefault();
      const params = new URLSearchParams();
      new FormData(e.currentTarget).forEach((v,k) => { if (String(v).trim()) params.set(k,String(v).trim()); });
      setPage(1); setQuery(params.toString()); retry(n=>n+1);
    }}>
      <div className="archive-fields">{fields.map(([key,label,type,hint]) => <label key={key}>{label}<input name={key} type={type} placeholder={hint}/></label>)}</div>
      <details><summary><SlidersHorizontal size={16}/> Advanced filters</summary>
        <div className="archive-fields advanced-fields">
          {advanced.map(([key,label,type]) => <label key={key}>{label}<input name={key} type={type}/></label>)}
          {['delayed','cancelled','diverted'].map(key => <label key={key}>{key.charAt(0).toUpperCase()+key.slice(1)}<select name={key}><option value="">Any</option><option value="true">Yes</option><option value="false">No</option></select></label>)}
          <label>Sort by<select name="sort_by">{['source_row','flight_date','flight_number','departure_delay','arrival_delay'].map(k=><option value={k} key={k}>{k.replace('_',' ')}</option>)}</select></label>
          <label>Direction<select name="sort_order"><option value="asc">Ascending</option><option value="desc">Descending</option></select></label>
        </div></details>
      <div className="archive-actions"><button type="reset">Reset</button><button className="archive-submit"><Search size={15}/> Search records</button></div>
    </form>
    {error ? <p className="analysis-message" role="alert">{error} <button onClick={()=>retry(n=>n+1)}>Retry</button></p> : !response ? <p className="analysis-message" role="status">Loading flight records…</p> :
      <><div className="archive-count"><div><h3>Results</h3><small>{response.source_period.split(' to ').map(reportingMonth).join(' – ')}</small></div><span>{response.pagination.total.toLocaleString()} matching records</span></div>
      {!response.data.length ? <p className="analysis-message">No flights match these filters.</p> :
        <div className="archive-table-wrap" role="region" aria-label="Flight results" tabIndex={0}><table><thead><tr>{['Flight','Date','Origin','Destination','Arrival delay','Status'].map(k=><th key={k}>{k}</th>)}</tr></thead>
        <tbody>{response.data.map(r=>{
          const label=status(r);
          const delay=r.arrival_delay_minutes;
          return <tr key={r.source_file+r.source_row_number}><td><strong>{r.reporting_airline}{r.flight_number}</strong></td><td>{r.flight_date}</td><td>{r.origin_bts_code}</td><td>{r.destination_bts_code}</td><td>{delay==null?'—':(delay>0?'+':'')+delay+' min'}</td><td><span className={'archive-status '+label.toLowerCase().replace(' ','-')}>{label}</span></td></tr>;
        })}</tbody></table></div>}
      <div className="archive-pagination"><span>Page {page}</span><button disabled={!response.pagination.has_previous} onClick={()=>setPage(p=>p-1)}>Previous</button><button disabled={!response.pagination.has_next} onClick={()=>setPage(p=>p+1)}>Next</button></div></>}
  </section>;
}
