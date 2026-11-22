import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ChevronDown, ChevronRight, Crosshair, Globe, Layers, MapPin, Plane, Radar, Search, Signal, X } from 'lucide-react';
import { fetchAirspace, savedAirspace } from '../services/airspaceFeed';
import { MapLibreTracker } from '../features/tracker/MapLibreTracker';
import { aircraftPath, coordinate, type Position } from '../features/tracker/aircraftDrawing';
import { measure, regions, utc, type Aircraft, type Region, type Snapshot } from '../features/tracker/airspace';
import '../styles/flightRadar.css';
import { DatasetMap } from '../features/tracker/DatasetMap';
import { API_ENDPOINTS, apiFetch } from '../services/apiConfig';

type TrafficFilter = 'All' | 'Airborne' | 'Ground';
const empty: Aircraft[] = [];
const fullTime = (time: number) => new Date(time).toISOString().slice(0,10) + ' · ' + utc(time);

function AircraftDetails({ aircraft: a, back }: { aircraft: Aircraft; back: () => void }) {
  const direction = a.heading == null ? '—' : ['N','NE','E','SE','S','SW','W','NW'][Math.round(a.heading/45)%8];
  return <div className="detail-body scope-detail">
    <button className="scope-back" onClick={back}><ArrowLeft size={16}/> Aircraft list</button>
    <div className="scope-id-card">
      <div><p className="scope-label">Selected aircraft</p><h2 className="aircraft-title">{a.callsign}</h2>
        <p>{[a.type,a.registration].filter(Boolean).join(' · ') || a.id.toUpperCase()}</p></div>
      <div className="scope-bearing" aria-label={'Aircraft track '+measure(a.heading,'°')}>
        <span>N</span><svg viewBox="0 0 24 24" style={{transform:'rotate('+(a.heading??0)+'deg)'}}><path d={aircraftPath}/></svg>
      </div>
    </div>
    <div className="scope-metrics">{[
      ['Barometric altitude',measure(a.altitude,'ft')],['Ground speed',measure(a.speed,'kt')],
      ['Track',a.heading==null?'—':Math.round(a.heading)+'° '+direction],['Vertical rate',measure(a.verticalRate,'ft/min')],
    ].map(([name,v])=><div key={name}><small>{name}</small><strong>{v}</strong></div>)}</div>
    <h3 className="scope-detail-heading">Transponder report</h3>
    <dl>{[['ICAO address',a.id.toUpperCase()],['Squawk',a.squawk||'—'],['Latitude',coordinate(a.lat,true)],['Longitude',coordinate(a.lon,false)],['Position time',fullTime(a.observed)]].map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
  </div>;
}

export function LiveTrackingPage() {
  const [mode,setMode]=useState<'live'|'dataset'|'kafka'>('live');
  return <div className="tracking-shell"><nav className="tracking-sources" aria-label="Flight data source">
    <span>Flight explorer</span>{(['live','dataset','kafka'] as const).map(m=><button key={m} aria-pressed={mode===m} onClick={()=>setMode(m)}>{m==='live'?'Live radar':m==='dataset'?'Dataset flights':'Kafka stream'}</button>)}
  </nav>{mode==='dataset'?<DatasetMap/>:<LiveRadar key={mode} kafka={mode==='kafka'}/>}</div>;
}

function LiveRadar({kafka=false}:{kafka?:boolean}) {
  const [region,setRegion]=useState<Region>('new-york');
  const [custom,setCustom]=useState<Position>();
  const center=custom??regions[region].center;
  const [mapCenter,setMapCenter]=useState(center);
  const moved=Math.abs(mapCenter[0]-center[0])+Math.abs(mapCenter[1]-center[1])>.3;
  const endpoint=custom ? '/airspace?lat='+custom[1].toFixed(2)+'&lon='+custom[0].toFixed(2) : '/airspace/'+region;
  const [globe,setGlobe]=useState(false);
  const [basic,setBasic]=useState(false);
  const [result,setResult]=useState<Snapshot>();
  const [error,setError]=useState(false);
  const [attempt,setAttempt]=useState(0);
  const [selectedId,select]=useState('');
  const [query,setQuery]=useState('');
  const [filter,setFilter]=useState<TrafficFilter>('All');
  const [now,setNow]=useState(Date.now());
  useEffect(()=>{
    const controller=new AbortController();
    let timer:number;
    let busy=false;
    const saved=kafka?undefined:savedAirspace(endpoint);
    if(saved) setResult(saved);
    async function refresh() {
      clearTimeout(timer);
      if(busy || document.hidden) return;
      busy=true;
      try {
        const snapshot=kafka?await apiFetch<Snapshot & {status:string}>(API_ENDPOINTS.streamStates,{signal:controller.signal}):await fetchAirspace(endpoint,center,controller.signal);
        if(controller.signal.aborted) return;
        setResult(snapshot);setError(false);setNow(Date.now());
      } catch {
        if(!controller.signal.aborted) setError(true);
      } finally {
        busy=false;
        if(!controller.signal.aborted && !document.hidden) timer=window.setTimeout(refresh,30000);
      }
    }
    const visibility=()=>{if(document.hidden) clearTimeout(timer);else void refresh();};
    document.addEventListener('visibilitychange',visibility);
    void refresh();
    const clock=window.setInterval(()=>setNow(Date.now()),10000);
    return ()=>{controller.abort();clearTimeout(timer);clearInterval(clock);document.removeEventListener('visibilitychange',visibility);};
  },[endpoint,center,attempt,kafka]);
  const aircraft=result?.aircraft??empty;
  const flights=useMemo(()=>{
    const term=query.trim().toUpperCase();
    return aircraft.filter(a=>(filter==='All' || (filter==='Ground')===a.ground) &&
      [a.callsign,a.registration,a.id].some(v=>v?.toUpperCase().includes(term)))
      .sort((a,b)=>Number(a.ground)-Number(b.ground)||Number(!a.registration)-Number(!b.registration)||a.callsign.localeCompare(b.callsign));
  },[aircraft,query,filter]);
  const selected=flights.find(a=>a.id===selectedId);
  const airborne=aircraft.reduce((count,a)=>count+Number(!a.ground),0);
  const ground=aircraft.length-airborne;
  const delayed=result && now-result.time>120000;
  const status=result?.recorded?'Recorded snapshot':error?(result?'Refresh interrupted':'Feed unavailable'):!result?'Connecting':kafka&&!result.aircraft.length?'Awaiting fresh stream':delayed?'Delayed feed':'Live feed';
  const extendedTime=!!result?.recorded||!!delayed||error;
  const name=kafka?'Kafka':custom?'Map area':regions[region].name;
  function changeRegion(next:Region,point?:Position) {
    setRegion(next);setCustom(point);setResult(undefined);select('');setQuery('');setFilter('All');setError(false);
  }
  return <section className="scope-workspace">
    <div className="scope-stage">
      <MapLibreTracker aircraft={flights} selected={selected} center={center} globe={globe&&!basic} routeMode={kafka} onSelect={select} onMove={setMapCenter} onGraphicsUnavailable={setBasic}/>
      <div className="scope-toolbar">
        {kafka?<div className="scope-region"><Signal size={18}/><span><small>Stream transport</small><strong>Kafka · Live observations</strong></span></div>:<label className="scope-region"><span className="scope-location-icon"><MapPin size={18}/></span><span>
          <small>Tracking region</small>
          <select aria-label="Tracking region" value={custom?'custom':region} onChange={e=>changeRegion(e.target.value as Region)}>
            {custom&&<option value="custom">Map area</option>}{Object.entries(regions).map(([k,r])=><option key={k} value={k}>{r.name}</option>)}
          </select></span><ChevronDown size={15}/></label>}
        <div className="scope-mode" aria-label="Map projection">
          <button aria-pressed={!globe||basic} onClick={()=>setGlobe(false)}><Layers size={16}/>2D</button>
          <button aria-pressed={globe&&!basic} disabled={basic} title={basic?'3D requires WebGL graphics':'View aircraft at reported altitude'} onClick={()=>setGlobe(true)}><Globe size={16}/>3D</button>
        </div>
      </div>
      {moved&&!kafka&&<button className="scope-area" onClick={()=>changeRegion(region,mapCenter)}><Crosshair size={15}/>Search this area</button>}
      <div className="scope-map-info"><div className="scope-map-key"><span><i/>Airborne</span><span><i/>Ground</span>{selected&&<span><i/>Selected</span>}</div>
        <div className="scope-position">{coordinate(mapCenter[1],true)} <b>/</b> {coordinate(mapCenter[0],false)}</div></div>
    </div>
    <aside className="scope-panel" aria-label="Aircraft data">
      <header className="scope-panel-header">
        <div className="scope-status-line"><div className="scope-section-label"><Radar size={15}/> Airspace monitor</div><span role="status" className={'scope-status '+(status==='Live feed'?'is-live':'')}>{status}</span></div>
        <h1>{name}{custom?'':' airspace'}</h1>
        <div className="scope-coverage">{kafka?'Provider → Kafka → consumer · positions under 2 min old':'ADS-B coverage · 80 NM radius'}</div>
        {!selected&&<div className="scope-totals">
          <div><strong>{result?aircraft.length.toLocaleString():'—'}</strong><span>Tracked</span></div>
          <div><strong>{result?airborne.toLocaleString():'—'}</strong><span><i/>Airborne</span></div>
          <div><strong>{result?ground.toLocaleString():'—'}</strong><span><i/>Ground</span></div>
        </div>}
      </header>
      {selected?<AircraftDetails aircraft={selected} back={()=>select('')}/>:<>
        <div className="scope-controls">
          <label className="scope-search"><Search size={16}/><input aria-label="Search aircraft" placeholder="Search callsign, tail or ICAO" value={query} onChange={e=>setQuery(e.target.value)}/>
            {query&&<button aria-label="Clear aircraft search" onClick={()=>setQuery('')}><X size={14}/></button>}</label>
          <div className="scope-filter" aria-label="Aircraft state">{(['All','Airborne','Ground'] as const).map(f=><button key={f} aria-pressed={f===filter} onClick={()=>setFilter(f)}>{f}</button>)}
            <span>{flights.length.toLocaleString()} shown</span></div>
        </div>
        <div className="traffic-list scope-list">
          {flights.map(a=><button key={a.id} onClick={()=>select(a.id)}>
            <span className={'scope-plane '+(a.ground?'is-ground':'')}><Plane size={17}/></span>
            <span className="scope-ident"><strong>{a.callsign}</strong><small>{[a.type,a.registration||a.id.toUpperCase()].filter(Boolean).join(' · ')}</small></span>
            <span className="scope-values"><b>{a.ground?'Ground':measure(a.altitude,'ft')}</b><small>{measure(a.speed,'kt')}</small></span><ChevronRight size={14}/>
          </button>)}
          {!flights.length&&<div className="scope-empty"><Radar size={26}/><p>{error&&!result?'Aircraft feed unavailable':!result?'Receiving positions…':query||filter!=='All'?'No matching aircraft':kafka?'Awaiting fresh Kafka observations':'No aircraft reported'}</p>
            {kafka&&!error&&<small>Start the broker, a provider producer and Kafka consumer. Archived and simulated positions are excluded.</small>}
            {error&&!result&&<small>Retrying every 30 seconds.</small>}{(query||filter!=='All')&&<button onClick={()=>{setQuery('');setFilter('All');}}>Clear filters</button>}</div>}
        </div>
      </>}
      <footer className="scope-footer"><div><Signal size={14}/>{kafka?'ADS-B via Kafka':<a href="https://www.adsb.lol/" target="_blank" rel="noreferrer">adsb.lol</a>}</div>
        <time>{result?.time?(extendedTime?fullTime(result.time):utc(result.time)):'Awaiting report'}</time>{(error||result?.recorded)&&<button onClick={()=>setAttempt(v=>v+1)}>Retry</button>}</footer>
    </aside>
  </section>;
}
