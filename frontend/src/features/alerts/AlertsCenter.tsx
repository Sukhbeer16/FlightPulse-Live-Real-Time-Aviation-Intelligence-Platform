import { useState } from 'react';
import { BellRing, Check, Inbox, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import type { AviationAlert } from '../../types';
import { API_ENDPOINTS, apiFetch } from '../../services/apiConfig';

interface Props { alerts: AviationAlert[]; error: string; loading: boolean; onRefresh: () => void }
const levels = ['critical','high','medium','low'] as const;
export function AlertsCenter({alerts, error, loading, onRefresh}: Props) {
  const [severity, setSeverity] = useState('all');
  const [status, setStatus] = useState('all');
  const [query, setQuery] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState('');
  const [notification, setNotification] = useState('');
  const [notificationsOn, setNotificationsOn] = useState(()=>{try{return localStorage.getItem('flightpulse.notifications')==='on'&&'Notification' in window&&Notification.permission==='granted';}catch{return false;}});
  const filtered = alerts.filter(a => (severity === 'all' || a.severity === severity) &&
    (status==='all' || a.status===status) &&
    [a.flightNumber,a.callsign,a.title,a.airline,a.origin,a.destination].some(v => v.toLowerCase().includes(query.trim().toLowerCase())));
  async function update(id:string, next:'acknowledged'|'resolved') {
    setBusy(id);setActionError('');
    try {await apiFetch(API_ENDPOINTS.alerts+'/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify({status:next})});onRefresh();}
    catch(e){setActionError(e instanceof Error?e.message:'Update failed.');}
    finally {setBusy('');}
  }
  async function enable() {
    if(notificationsOn){try{localStorage.setItem('flightpulse.notifications','off');setNotificationsOn(false);setNotification('Desktop alerts paused. Your inbox continues to update.');}catch{setNotification('Browser preferences could not be saved.');}return;}
    if (!('Notification' in window)) {setNotification('Desktop notifications are unavailable in this browser.');return;}
    try {
      const permission=await Notification.requestPermission();
      if(permission==='granted'){localStorage.setItem('flightpulse.notifications','on');setNotificationsOn(true);setNotification('Desktop notifications enabled while FlightPulse is open.');}
      else setNotification('Notifications were not enabled. You can allow them in browser site settings.');
    } catch {setNotification('Notifications could not be enabled in this browser.');}
  }
  return <div className="ops-alert-grid">
    <section className="ops-alert-summary">
      <div className="ops-ticket-top"><span><ShieldCheck size={19}/> Operations inbox</span></div>
      <strong className="ops-total">{error || loading ? '—' : alerts.filter(a=>a.status==='ACTIVE').length}</strong>
      <p>Open alerts · latest 100 records</p>
      <div className="ops-breakdown">{levels.map(level => <div key={level}><span><i className={'ops-dot '+level}/>{level}</span><b>{loading || error ? '—' : alerts.filter(a=>a.severity===level&&a.status==='ACTIVE').length}</b></div>)}</div>
      <button className="ops-secondary" onClick={enable}><BellRing size={17}/>{notificationsOn?'Pause desktop alerts':'Enable desktop alerts'}</button>
      <p className="ops-notification-note" role="status">{notification || 'Get a desktop notification for new alerts while the application is open. Email delivery requires server SMTP configuration.'}</p>
    </section>
    <section className="ops-card ops-inbox"><header className="ops-card-heading"><span className="ops-icon"><Inbox size={21}/></span><div><h2>Alert inbox</h2><p>Persistent records with source evidence</p></div><button className="ops-quiet ops-refresh" aria-label="Refresh alert inbox" onClick={onRefresh} disabled={loading}><RefreshCw size={17}/></button></header>
      <div className="ops-filters"><label className="ops-search"><Search size={17}/><input aria-label="Search alerts" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search flight, airline or alert"/></label>
        <label className="ops-severity"><select aria-label="Severity" value={severity} onChange={e=>setSeverity(e.target.value)}><option value="all">All severities</option>{levels.map(level=><option key={level} value={level}>{level}</option>)}</select></label>
        <label className="ops-severity"><select aria-label="Alert status" value={status} onChange={e=>setStatus(e.target.value)}><option value="all">All statuses</option><option value="ACTIVE">Open</option><option value="MONITORING">Acknowledged</option><option value="RESOLVED">Resolved</option></select></label></div>
      {actionError&&<p role="alert" className="ops-error">{actionError}</p>}
      {error ? <p className="ops-error" role="alert">{error}</p> : loading && !alerts.length ? <p className="ops-notice" role="status">Loading alert inbox…</p> :
        !filtered.length ? <div className="ops-empty"><span><ShieldCheck size={29}/></span><h3>{alerts.length ? 'No matching alerts' : 'No alerts recorded'}</h3><p>{alerts.length ? 'Try another filter.' : 'Save a disruption from the dataset map or run the Kafka consumer to receive live telemetry review flags.'}</p></div> :
        <div className="ops-inbox-list">{filtered.map(a=><details key={a.id}><summary><i className={'ops-dot '+a.severity}/><div><strong>{a.title}</strong><small>{a.airline} · {a.origin}–{a.destination} · {new Date(a.detectionTime).toLocaleString()}</small></div><span className="ops-level">{a.status==='ACTIVE'?'Open':a.status==='MONITORING'?'Acknowledged':'Resolved'}</span></summary>
          <div className="ops-alert-detail"><span className="ops-pill">{a.source==='historical_bts'?'Historical BTS':a.source==='opensky'?'Live OpenSky':a.source==='adsb_lol'?'Live adsb.lol':'Demonstration'}</span><p>{a.explanation}</p>
            <p>Delivery: {a.deliveryStatus==='sent'?'Accepted by email server':a.deliveryStatus==='pending'?'Email queued':a.deliveryStatus==='failed'?'Email failed · '+a.deliveryError:'Saved in application'}</p>
            <div className="ops-alert-actions">{a.status==='ACTIVE'&&<button className="ops-secondary" disabled={!!busy} onClick={()=>update(a.id,'acknowledged')}><Check size={16}/>Acknowledge</button>}
              {a.status!=='RESOLVED'&&<button className="ops-secondary" disabled={!!busy} onClick={()=>update(a.id,'resolved')}><ShieldCheck size={16}/>Resolve</button>}</div>
          </div></details>)}</div>}
    </section>
  </div>;
}
