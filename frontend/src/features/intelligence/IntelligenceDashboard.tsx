import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, CalendarDays, Clock3, PlaneLanding, PlaneTakeoff, Radio, Timer, Bell } from 'lucide-react';
import { AreaChart, Area, CartesianGrid, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import { API_ENDPOINTS } from '../../services/apiConfig';
import { AIRLINES } from '../../data/aviationData';
import type { FlightTrack, AviationAlert } from '../../types';
import { reportingMonth, useReport, type OverviewReport, type Report } from './historicalReports';

interface Hour { time_basis: string; hour: number; flights_in_hour: number; delay_rate: number | null }
interface Carrier { Reporting_Airline: string; total_flights: number; delay_rate: number | null }
const carrierNames: Record<string,string> = {
  ...Object.fromEntries(Object.values(AIRLINES).map(a => [a.code, a.name])),
  WN: 'Southwest Airlines', OO: 'SkyWest Airlines',
};
interface Props {
  flights: FlightTrack[]; alerts: AviationAlert[]; flightsStatus: string; alertsStatus: string;
  onSelectFlight: (flight: FlightTrack) => void;
}

export function IntelligenceDashboard({ flights, alerts, flightsStatus, alertsStatus, onSelectFlight }: Props) {
  const summary = useReport<OverviewReport>(API_ENDPOINTS.analyticsOverview);
  const hourly = useReport<Report<Hour>>(API_ENDPOINTS.analyticsReport('hourly'));
  const carriers = useReport<Report<Carrier>>(API_ENDPOINTS.analyticsReport('airlines'));
  const [metric, setMetric] = useState<'volume' | 'delay'>('volume');
  const s = summary.data?.statistics;
  const hours = (hourly.data?.data ?? []).filter(r => r.time_basis === 'scheduled_arrival')
    .sort((a,b) => a.hour-b.hour).map(r => ({
      hour: String(r.hour).padStart(2, '0') + ':00',
      value: metric === 'volume' ? r.flights_in_hour : r.delay_rate == null ? null : +(r.delay_rate*100).toFixed(1),
    }));
  const airlines = [...(carriers.data?.data ?? [])].sort((a,b) => b.total_flights-a.total_flights).slice(0,5);
  const punctuality = s?.delay_rate == null ? null : 100*(1-s.delay_rate);
  return <div className="analysis-content">
    <header className="analysis-mast"><div><p className="analysis-overline"><Activity size={15}/> Network analytics</p><h1>Operations overview</h1><p>US carrier performance and arrival patterns across the domestic network.</p></div>
      <span className="analysis-period"><CalendarDays size={16}/>{reportingMonth(summary.data?.source_period)}</span>
    </header>
    <section className="analysis-kpis" aria-label="Monthly flight performance">
      {[
        {title:'Flights recorded',value:s?.total_flights.toLocaleString(),note:'Scheduled flights',icon:PlaneTakeoff},
        {title:'On-time arrivals',value:punctuality == null ? null : punctuality.toFixed(1)+'%',note:'Within 15 minutes',icon:PlaneLanding},
        {title:'Delayed arrivals',value:s?.delayed_flights.toLocaleString(),note:'Over 15 minutes late',icon:Clock3},
        {title:'Mean arrival delay',value:s?.average_arrival_delay_minutes == null ? null : s.average_arrival_delay_minutes.toFixed(1)+' min',note:'Eligible arrivals',icon:Timer},
      ].map(({title,value,note,icon:Icon}) => <article key={title}><div><span>{title}</span><Icon size={18}/></div><strong>{value ?? '—'}</strong><small>{note}</small></article>)}
    </section>
    {summary.error && <p className="analysis-error" role="alert">Monthly statistics are unavailable. <button onClick={summary.retry}>Retry</button></p>}
    <div className="analysis-split">
      <section className="analysis-card"><div className="analysis-card-head"><div><h2>Arrival profile</h2><p>By scheduled arrival hour, airport local time</p></div>
        <div className="analysis-segments">{(['volume','delay'] as const).map(m => <button key={m} aria-pressed={metric===m} onClick={() => setMetric(m)}>{m==='volume'?'Flights':'Delay rate'}</button>)}</div></div>
        {hours.length ? <div className="analysis-chart" role="img" aria-label={metric==='volume'?'Scheduled flight volume by hour':'Arrival delay rate by hour'}>
          <ResponsiveContainer width="100%" height="100%"><AreaChart data={hours} margin={{left:-10,right:18,top:12,bottom:3}}>
            <defs><linearGradient id="arrival-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#16a799" stopOpacity={.34}/><stop offset="100%" stopColor="#16a799" stopOpacity={.03}/></linearGradient></defs>
            <CartesianGrid vertical={false} stroke="#dce5e9" strokeDasharray="3 4"/>
            <XAxis dataKey="hour" interval={3} axisLine={false} tickLine={false} tick={{fontSize:12,fill:'#526775'}}/>
            <YAxis axisLine={false} tickLine={false} tick={{fontSize:12,fill:'#526775'}} tickFormatter={v => metric==='delay'?v+'%':Intl.NumberFormat('en',{notation:'compact'}).format(v)}/>
            <Tooltip formatter={v => [metric==='volume'?Number(v).toLocaleString():v+'%',metric==='volume'?'Flights':'Delayed arrivals']} />
            <Area dataKey="value" type="monotone" stroke="#007c74" strokeWidth={3} fill="url(#arrival-fill)" isAnimationActive={false}/>
          </AreaChart></ResponsiveContainer>
        </div> : <p className="analysis-message">{hourly.error?'Hourly report unavailable.':hourly.data?'No hourly observations.':'Loading hourly report…'} {hourly.error && <button onClick={hourly.retry}>Retry</button>}</p>}
      </section>
      <section className="analysis-card"><div className="analysis-card-head"><div><h2>Carrier punctuality</h2><p>On-time arrivals at the five busiest carriers</p></div></div>
        <div className="analysis-carriers">{airlines.map(r => {
          const rate = r.delay_rate == null ? null : 100*(1-r.delay_rate);
          return <div key={r.Reporting_Airline}><span className="carrier-code">{r.Reporting_Airline}</span><div><b>{carrierNames[r.Reporting_Airline] ?? 'Carrier '+r.Reporting_Airline}</b><div className="carrier-track"><i style={{width:(rate ?? 0)+'%'}}/></div></div><strong>{rate == null?'—':rate.toFixed(1)+'%'}</strong></div>;
        })}</div>
        {!airlines.length && <p className="analysis-message">{carriers.error?'Carrier report unavailable.':carriers.data?'No carrier records.':'Loading carrier report…'} {carriers.error && <button onClick={carriers.retry}>Retry</button>}</p>}
      </section>
    </div>
    <div className="analysis-split">
      <section className="analysis-card"><div className="analysis-card-head"><div><h2>Flight records</h2><p>Select a flight to inspect its source record.</p></div><Link to="/historical">Browse archive</Link></div>
        <div className="analysis-records">{flights.map(f=><button key={f.id} onClick={()=>onSelectFlight(f)}><b>{f.callsign}</b><span>{f.origin.btsCode ?? f.origin.iata} <i>→</i> {f.destination.btsCode ?? f.destination.iata}</span><time>{f.sourceDetails?.[0]}</time></button>)}</div>
        {!flights.length && <p className="analysis-message">{flightsStatus}</p>}
      </section>
      <section className="analysis-card"><div className="analysis-card-head"><div><h2>Assessment alerts</h2><p>Historical assessment demonstration log</p></div><Link to="/alerts">View log</Link></div>
        {!alerts.length ? <div className="analysis-empty"><Bell size={28}/><p>{alertsStatus}</p></div> :
          <ul className="analysis-alerts">{alerts.slice(0,5).map(a=><li key={a.id}><Radio size={16}/><div><b>{a.title}</b><p>{a.callsign} · {a.severity}</p></div></li>)}</ul>}
      </section>
    </div>
    <p className="analysis-source">Source · US Bureau of Transportation Statistics</p>
  </div>;
}
