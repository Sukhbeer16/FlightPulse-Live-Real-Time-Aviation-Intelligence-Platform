import { useEffect, useState } from 'react';
import { Activity, Database, Radio, RefreshCw, Server, Waypoints } from 'lucide-react';
import { API_BASE_URL, API_ENDPOINTS, apiFetch } from '../services/apiConfig';
import type { Snapshot } from '../features/tracker/airspace';
import '../styles/services.css';

type Report = { available: boolean; detail: string };
const checks = [
  { title:'FlightPulse API', icon:Server, run:async (signal: AbortSignal): Promise<Report> => {
    const r = await apiFetch<{version:string}>(API_ENDPOINTS.health,{signal});
    return {available:true, detail:'FastAPI version ' + r.version};
  }},
  { title:'Radar feed', icon:Radio, run:async (signal: AbortSignal): Promise<Report> => {
    const r = await apiFetch<Snapshot>(API_BASE_URL + '/api/v1/live/airspace/new-york',{signal});
    return {available:Date.now()-r.time < 120000, detail:r.aircraft.length + ' aircraft in the New York area · ' + new Date(r.time).toUTCString()};
  }},
  { title:'Historical database', icon:Database, run:async (signal: AbortSignal): Promise<Report> => {
    const r = await apiFetch<{status:string}>(API_ENDPOINTS.databaseHealth,{signal});
    return {available:r.status==='ok', detail:'PostgreSQL connection verified'};
  }},
  { title:'Model catalog', icon:Activity, run:async (signal: AbortSignal): Promise<Report> => {
    const r = await apiFetch<{models:{status:string;algorithm:string}[]}>(API_ENDPOINTS.models,{signal});
    const models = r.models.filter(m=>m.status==='available');
    return {available:models.length>0, detail:models.length+' of '+r.models.length+' models available · '+models.map(m=>m.algorithm).join(', ')};
  }},
  { title:'OpenSky integration', icon:Waypoints, run:async (signal: AbortSignal): Promise<Report> => {
    const r = await apiFetch<{state:string;oauth_configured:boolean}>(API_ENDPOINTS.providerStatus,{signal});
    return {available:r.state==='connected', detail:'Optional stream · '+(r.oauth_configured ? r.state.replace(/_/g,' ') : 'OAuth credentials unconfigured')};
  }},
  { title:'Kafka live positions', icon:Activity, run:async (signal: AbortSignal): Promise<Report> => {
    const r = await apiFetch<{status:string;time:number|null;aircraft:unknown[]}>(API_ENDPOINTS.streamStates,{signal});
    return {available:r.status==='available', detail:r.status==='available'?r.aircraft.length+' fresh aircraft from Kafka':r.status==='stale'?'Stored observations are stale; check producer and consumer.':'Awaiting Kafka observations; start broker, producer and consumer.'};
  }},
];

export function SystemStatusPage() {
  const [attempt, setAttempt] = useState(0);
  const [reports,setReports] = useState<Record<string,Report>>({});
  const [checked,setChecked] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setReports({}); setChecked(new Date().toUTCString());
    for (const check of checks) {
      check.run(controller.signal).catch((error: Error) => ({available:false,detail:error.message}))
        .then(report=>{if(!controller.signal.aborted)setReports(prev=>({...prev,[check.title]:report}));});
    }
    return ()=>controller.abort();
  },[attempt]);
  return <div className="service-page"><div className="service-wrap"><header><div><h1>System status</h1><p>Last checked {checked}</p></div>
    <button onClick={()=>setAttempt(n=>n+1)}><RefreshCw size={16}/> Recheck</button></header>
    <section className="service-surface"><h2>Service connections</h2><div className="service-rows">
      {checks.map(({title,icon:Icon}) => {const r=reports[title];return <article key={title}><span className="service-icon"><Icon size={21}/></span>
        <div><h3>{title}</h3><p>{r?.detail ?? 'Requesting service status…'}</p></div><span className={'service-state '+(r?.available?'online':'')}>{r ? r.available ? 'Available' : 'Unavailable' : 'Checking'}</span></article>;})}
    </div></section></div></div>;
}
export default SystemStatusPage;
