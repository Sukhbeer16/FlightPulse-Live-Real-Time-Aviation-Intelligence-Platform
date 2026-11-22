import { useEffect, useState } from 'react';
import { Check, RefreshCw, ShieldCheck } from 'lucide-react';
import type { AviationAlert } from '../../types';
import { fetchAlertPage } from '../../services/flightsService';
import { API_ENDPOINTS, apiFetch } from '../../services/apiConfig';

type Counts={by_status:Record<string,number>;open_by_severity:Record<string,number>};
export function OperationalAlertsCenter(){
  const [rows,setRows]=useState<AviationAlert[]>([]);
  const [counts,setCounts]=useState<Counts>();
  const [page,setPage]=useState(1);
  const [totalPages,setTotalPages]=useState(0);
  const [total,setTotal]=useState(0);
  const [status,setStatus]=useState('');
  const [severity,setSeverity]=useState('');
  const [type,setType]=useState('');
  const [search,setSearch]=useState('');
  const [includeDemo,setIncludeDemo]=useState(false);
  const [attempt,refresh]=useState(0);
  const [busy,setBusy]=useState('');
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  useEffect(()=>{
    let active=true;
    const timer=window.setTimeout(()=>{
      setLoading(true);setError('');
      Promise.all([fetchAlertPage({page,status,severity,type,search,includeDemo}),apiFetch<Counts>(API_ENDPOINTS.alerts+'/counts')])
        .then(([result,summary])=>{if(active){setRows(result.data);setTotal(result.total);setTotalPages(result.totalPages);setCounts(summary);}})
        .catch(e=>{if(active)setError(e instanceof Error?e.message:'Alert inbox unavailable.');})
        .finally(()=>{if(active)setLoading(false);});
    },search?250:0);
    return()=>{active=false;clearTimeout(timer);};
  },[page,status,severity,type,search,includeDemo,attempt]);
  useEffect(()=>{
    const poll=window.setInterval(()=>refresh(n=>n+1),15000);
    const event=()=>refresh(n=>n+1);
    window.addEventListener('flightpulse-alerts-updated',event);
    return()=>{clearInterval(poll);window.removeEventListener('flightpulse-alerts-updated',event);};
  },[]);
  async function update(id:string,next:'acknowledged'|'resolved'){
    setBusy(id);setError('');
    try{await apiFetch(API_ENDPOINTS.alerts+'/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify({status:next})});refresh(n=>n+1);}
    catch(e){setError(e instanceof Error?e.message:'Unable to update alert.');}
    finally{setBusy('');}
  }
  return <div className="ops-alert-grid"><section className="ops-alert-summary">
    <div className="ops-ticket-top"><span><ShieldCheck size={19}/> Operations inbox</span></div>
    <strong className="ops-total">{counts?.by_status.open??'—'}</strong><p>Open operational alerts · all records</p>
    <div className="ops-breakdown">{(['high','warning','info'] as const).map(level=><div key={level}><span><i className={'ops-dot '+(level==='warning'?'medium':level==='info'?'low':'high')}/>{level}</span><b>{counts?.open_by_severity[level]??'—'}</b></div>)}</div>
    <p>{counts?.by_status.acknowledged??0} acknowledged · {counts?.by_status.resolved??0} resolved</p>
    <p className="ops-notification-note">Desktop notifications can be enabled from the top bar while this app is open. Email requires server SMTP configuration.</p>
  </section><section className="ops-card ops-inbox"><header className="ops-card-heading"><div><h2>Alert inbox</h2><p>{total} matching persistent records</p></div><button className="ops-quiet ops-refresh" aria-label="Refresh alert inbox" onClick={()=>refresh(n=>n+1)}><RefreshCw size={17}/></button></header>
    <div className="ops-filters"><label className="ops-search"><input aria-label="Search alerts" placeholder="Search flight, airline or alert" value={search} onChange={e=>{setSearch(e.target.value);setPage(1);}}/></label>
      <label className="ops-severity"><select aria-label="Alert status" value={status} onChange={e=>{setStatus(e.target.value);setPage(1);}}><option value="">All statuses</option><option value="open">Open</option><option value="acknowledged">Acknowledged</option><option value="resolved">Resolved</option></select></label>
      <label className="ops-severity"><select aria-label="Severity" value={severity} onChange={e=>{setSeverity(e.target.value);setPage(1);}}><option value="">All severities</option><option value="high">High</option><option value="warning">Warning</option><option value="info">Info</option></select></label>
      <label className="ops-severity"><select aria-label="Alert type" value={type} onChange={e=>{setType(e.target.value);setPage(1);}}><option value="">All types</option><option value="historical_delay">Historical delay</option><option value="telemetry_review">Telemetry review</option><option value="statistical_anomaly">Statistical anomaly</option><option value="risk_assessment">Risk assessment</option></select></label>
      <label><input type="checkbox" checked={includeDemo} onChange={e=>{setIncludeDemo(e.target.checked);setPage(1);}}/> Show demonstrations</label>
    </div>
    {error?<p role="alert" className="ops-error">{error}</p>:loading?<p>Loading alerts…</p>:rows.length?<div className="ops-inbox-list">{rows.map(a=><details key={a.id}><summary><i className={'ops-dot '+a.severity}/><div><strong>{a.title}</strong><small>{a.airline} · {a.origin}–{a.destination} · {new Date(a.detectionTime).toLocaleString()}</small></div><span className="ops-level">{a.status==='ACTIVE'?'Open':a.status==='MONITORING'?'Acknowledged':'Resolved'}</span></summary>
      <div className="ops-alert-detail"><span className="ops-pill">{a.source} · {a.alertType}</span><p>{a.explanation}</p><p>Evidence time: {a.evidenceTime??'Not supplied'} · Last updated: {a.updatedAt?new Date(a.updatedAt).toLocaleString():'Not supplied'}</p><p>{a.acknowledgedAt?'Acknowledged: '+new Date(a.acknowledgedAt).toLocaleString():''}{a.resolvedAt?' · Resolved: '+new Date(a.resolvedAt).toLocaleString():''}</p><p>Delivery: {a.deliveryStatus==='sent'?'Accepted by email server':a.deliveryStatus==='pending'?'Email queued':a.deliveryStatus==='failed'?'Email failed: '+a.deliveryError:'Saved in application'}</p><div className="ops-alert-actions">{a.status==='ACTIVE'&&<button className="ops-secondary" disabled={!!busy} onClick={()=>update(a.id,'acknowledged')}><Check size={16}/>Acknowledge</button>}{a.status!=='RESOLVED'&&<button className="ops-secondary" disabled={!!busy} onClick={()=>update(a.id,'resolved')}><ShieldCheck size={16}/>Resolve</button>}</div></div></details>)}</div>:<div className="ops-empty"><h3>No matching alerts</h3><p>Save a delayed historical record or review fresh Kafka telemetry.</p></div>}
    <footer className="dataset-route-pages"><button disabled={page===1||loading} onClick={()=>setPage(p=>p-1)}>Previous</button><span>Page {page} of {totalPages||1}</span><button disabled={page>=totalPages||loading} onClick={()=>setPage(p=>p+1)}>Next</button></footer>
  </section></div>;
}
