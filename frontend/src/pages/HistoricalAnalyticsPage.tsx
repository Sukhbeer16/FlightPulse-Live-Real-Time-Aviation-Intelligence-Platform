import { useState } from 'react';
import { Archive, CalendarDays, ChartColumn, ListFilter } from 'lucide-react';
import { HistoricalSearch } from '../features/tracker/HistoricalSearch';
import { API_ENDPOINTS } from '../services/apiConfig';
import { reportingMonth, useReport, type OverviewReport, type Report } from '../features/intelligence/historicalReports';
import '../styles/analytics.css';

interface Distribution {
  delay_type: string; statistic: string; category: string; proportion: number; flight_count: number;
}
const buckets = [['early','Early'],['on_time','0–15 min late'],['delayed','16–60 min late'],['severe','61–180 min late'],['extreme','Over 180 min late']];

function DelayDistribution() {
  const [event,setEvent] = useState<'arrival'|'departure'>('arrival');
  const report = useReport<Report<Distribution>>(API_ENDPOINTS.analyticsReport('delay-distribution'));
  const rows = (report.data?.data ?? []).filter(r=>r.delay_type===event && r.statistic==='category');
  return <section className="analysis-card"><div className="analysis-card-head"><div><h2>Delay distribution</h2><p>Share of eligible records in each delay interval</p></div><div className="analysis-segments">
    {(['arrival','departure'] as const).map(m=><button key={m} aria-pressed={m===event} onClick={()=>setEvent(m)}>{m==='arrival'?'Arrivals':'Departures'}</button>)}</div></div>
    {!rows.length ? <p className="analysis-message">{report.error?'The delay distribution is unavailable.':report.data?'No eligible records.':'Loading report…'} {report.error && <button onClick={report.retry}>Retry</button>}</p> :
      <div className="analysis-distribution">{buckets.map(([key,label])=>{
        const row=rows.find(r=>r.category===key);
        if (!row) return null;
        return <div key={key}><strong>{label}</strong><div className="carrier-track"><i style={{width:row.proportion*100+'%'}}/></div><b>{(row.proportion*100).toFixed(1)}%</b><small>{row.flight_count.toLocaleString()} flights</small></div>;
      })}</div>}
  </section>;
}
export function HistoricalAnalyticsPage() {
  const summary=useReport<OverviewReport>(API_ENDPOINTS.analyticsOverview);
  const s=summary.data?.statistics;
  const [tab,setTab]=useState<'records'|'performance'>('records');
  return <div className="analysis-page"><div className="analysis-content">
    <header className="analysis-mast"><div><p className="analysis-overline"><Archive size={15}/> Historical data</p><h1>Flight archive</h1><p>Search reported US flights by carrier, route and operating date.</p></div><span className="analysis-period"><CalendarDays size={16}/>Summary · {reportingMonth(summary.data?.source_period)}</span></header>
    <div className="archive-strip">{[['Records',s?.total_flights],['Eligible arrivals',s?.eligible_arrival_records],['Delayed',s?.delayed_flights],['Cancelled',s?.cancelled_flights],['Diverted',s?.diverted_flights]].map(([label,value])=><div key={label}><small>{label}</small><strong>{typeof value==='number'?value.toLocaleString():'—'}</strong></div>)}</div>
    {summary.error && <p className="analysis-error" role="alert">Archive totals are unavailable. <button onClick={summary.retry}>Retry</button></p>}
    <div className="archive-tabs"><button aria-pressed={tab==='records'} onClick={()=>setTab('records')}><ListFilter size={17}/> Flight records</button><button aria-pressed={tab==='performance'} onClick={()=>setTab('performance')}><ChartColumn size={17}/> Delay analysis</button></div>
    <div hidden={tab!=='records'}><HistoricalSearch /></div>
    {tab==='performance' && <DelayDistribution />}
    <p className="analysis-source">Source · US Bureau of Transportation Statistics</p>
  </div></div>;
}
export default HistoricalAnalyticsPage;
