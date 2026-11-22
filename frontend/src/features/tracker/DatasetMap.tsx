import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, BellPlus, ChevronLeft, ChevronRight, Database, Plane, Search } from 'lucide-react';
import { MapLibreTracker } from './MapLibreTracker';
import type { Aircraft } from './airspace';
import type { Position } from './aircraftDrawing';
import { fetchHistoricalFlights, type HistoricalFlightResponse, type HistoricalFlightItem } from '../../services/flightsService';
import { apiFetch, API_ENDPOINTS } from '../../services/apiConfig';
import { DelayReasons } from '../intelligence/DelayReasons';
import '../../styles/operations.css';

const center: Position = [-98,39];
const identity = (r:HistoricalFlightItem) => r.source_file+'#'+r.source_row_number;
const defaults = {origin:'',destination:'',airline:'',flight:'',date:'',delayed:false};
const flightLabel = (row: HistoricalFlightItem) =>
  [row.reporting_airline, row.flight_number].filter(Boolean).join('') || 'Flight number unavailable';
interface RouteCoverage {
  flights:number; mapped_flights:number; airport_count:number; city_count:number; route_count:number;
  cities:string[];
  airports:Array<{code:string;name:string|null;city:string|null;flights:number}>;
  routes:Array<{origin:string;destination:string;origin_name:string|null;destination_name:string|null;
    origin_city:string|null;destination_city:string|null;origin_coordinates:Position|null;
    destination_coordinates:Position|null;flights:number;delay_percent:number|null}>;
  pagination:{page:number;total_pages:number};
}
export function DatasetMap() {
  const [draft,setDraft]=useState(defaults);
  const [filters,setFilters]=useState(defaults);
  const [page,setPage]=useState(1);
  const [response,setResponse]=useState<HistoricalFlightResponse>();
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const [selectedId,select]=useState('');
  const [routePage,setRoutePage]=useState(1);
  const [city,setCity]=useState('');
  const [airport,setAirport]=useState('');
  const [coverage,setCoverage]=useState<RouteCoverage>();
  const coverageRef=useRef<RouteCoverage|undefined>(undefined);
  coverageRef.current=coverage;
  const [availableCities,setAvailableCities]=useState<string[]>([]);
  const [availableAirports,setAvailableAirports]=useState<RouteCoverage['airports']>([]);
  const [coverageError,setCoverageError]=useState('');
  const [,setMapCenter]=useState(center);
  const [,setBasic]=useState(false);
  const [message,setMessage]=useState('');
  const [saving,setSaving]=useState(false);
  useEffect(()=>{
    let active=true;
    setLoading(true);setError('');setResponse(undefined);select('');setMessage('');
    fetchHistoricalFlights({page,pageSize:100,origin:filters.origin||undefined,destination:filters.destination||undefined,airport:airport||undefined,
      airlineCode:filters.airline||undefined,flightIdentifier:filters.flight||undefined,dateFrom:filters.date||undefined,
      dateTo:filters.date||undefined,delayed:filters.delayed?true:undefined}).then(r=>{if(active)setResponse(r.response);})
      .catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[filters,page,airport]);
  useEffect(()=>{
    let active=true;
    setCoverage(undefined);setCoverageError('');
    const query=new URLSearchParams({page:String(routePage),page_size:'15'});
    if(city)query.set('city',city);
    if(airport)query.set('airport',airport);
    if(filters.origin)query.set('origin',filters.origin);
    if(filters.destination)query.set('destination',filters.destination);
    if(filters.airline)query.set('airline',filters.airline);
    if(filters.flight)query.set('flight_number',filters.flight);
    if(filters.date){query.set('date_from',filters.date);query.set('date_to',filters.date);}
    if(filters.delayed)query.set('delayed','true');
    apiFetch<RouteCoverage>(API_ENDPOINTS.mapCoverage+'?'+query).then(data=>{if(active){setCoverage(data);if(!city&&!airport&&!filters.origin&&!filters.destination&&!filters.airline&&!filters.flight&&!filters.date&&!filters.delayed){setAvailableCities(data.cities);setAvailableAirports(data.airports);}setCoverageError('');}})
      .catch(e=>{if(active)setCoverageError(e instanceof Error?e.message:'Route coverage unavailable.');});
    return()=>{active=false;};
  },[filters,routePage,city,airport]);
  const rows=response?.data??[];
  const selected=rows.find(r=>identity(r)===selectedId);
  useEffect(()=>{setMessage('');},[selectedId]);
  const {aircraft,routes}=useMemo(()=>{
    const aircraft:Aircraft[]=[];
    const routes:{id:string;coordinates:Position[]}[]=[];
    for(const r of coverage?.routes??[]){
      const a=r.origin_coordinates,b=r.destination_coordinates;
      if(!a||!b)continue;
      const id='route:'+r.origin+':'+r.destination;
      routes.push({id,coordinates:[a,b]});
      aircraft.push({id,callsign:r.origin+'–'+r.destination+' · '+r.flights.toLocaleString()+' flights',
        registration:null,type:null,lon:(a[0]+b[0])/2,lat:(a[1]+b[1])/2,ground:false,
        altitude:null,speed:null,heading:Math.atan2(b[0]-a[0],b[1]-a[1])*180/Math.PI,
        verticalRate:null,observed:0,squawk:null});
    }
    return {aircraft,routes};
  },[coverage]);
  const chooseRoute=useCallback((origin:string,destination:string)=>{
    const next={...defaults,origin,destination};
    setDraft(next);setFilters(next);setPage(1);select('');
  },[]);
  const selectRoute=useCallback((id:string)=>{
    const route=coverageRef.current?.routes.find(r=>id==='route:'+r.origin+':'+r.destination);
    if(route)chooseRoute(route.origin,route.destination);
  },[chooseRoute]);
  async function saveAlert(row:HistoricalFlightItem){
    setSaving(true);setMessage('');
    try {await apiFetch(API_ENDPOINTS.historicalAlert,{method:'POST',body:JSON.stringify({source_file:row.source_file,source_row_number:row.source_row_number})});setMessage('Historical alert saved. View it in the alert center.');}
    catch(e){setMessage(e instanceof Error?e.message:'Unable to save alert.');}
    finally{setSaving(false);}
  }
  return <section className="scope-workspace dataset-workspace">
    <div className="scope-stage">
      <MapLibreTracker aircraft={aircraft} routes={routes} routeMode center={center} globe={false} onSelect={selectRoute} onMove={setMapCenter} onGraphicsUnavailable={setBasic}/>
      <div className="scope-toolbar"><div className="scope-region"><span className="scope-location-icon"><Database size={19}/></span><span><small>BTS January–February 2024</small><strong>Dataset route explorer</strong></span></div></div>
      <div className="scope-map-info"><div className="scope-map-key"><span><i/>Historical routes</span><span>Airport coordinates from BTS</span></div><p>Plane icons mark route midpoints, not aircraft positions.</p><small>{aircraft.length} aggregated routes on this page · overlapping routes share markers</small></div>
    </div>
    <aside className="scope-panel"><header className="scope-panel-header"><div className="scope-section-label"><Database size={15}/> Historical flight records</div><h1>Flights in your dataset</h1><p className="scope-coverage">{response?response.pagination.total.toLocaleString()+' matching records':'Search the BTS archive'}</p></header>
      {!selected&&<section className="dataset-route-browser" aria-label="Dataset route coverage">
        {coverageError?<p role="alert">{coverageError}</p>:coverage?<>
          <p>{coverage.flights.toLocaleString()} flights · {coverage.airport_count} airports · {coverage.city_count} cities · {coverage.route_count.toLocaleString()} routes</p>
          <label>City <select aria-label="Dataset city" value={city} onChange={e=>{setCoverage(undefined);setCity(e.target.value);setRoutePage(1);}}><option value="">All source cities</option>{availableCities.map(name=><option key={name} value={name}>{name}</option>)}</select></label>
          <label>Airport <select aria-label="Dataset airport" value={airport} onChange={e=>{setCoverage(undefined);setAirport(e.target.value);setRoutePage(1);setPage(1);}}><option value="">All source airports</option>{availableAirports.map(row=><option key={row.code} value={row.code}>{row.code} · {row.name??'Name unavailable'}</option>)}</select></label>
          <div className="dataset-route-list">{coverage.routes.map(route=><button key={route.origin+':'+route.destination} onClick={()=>chooseRoute(route.origin,route.destination)} title="Filter flights to this route">
            <strong>{route.origin}–{route.destination}</strong><span>{route.origin_city??route.origin_name??'Unknown city'} to {route.destination_city??route.destination_name??'Unknown city'}</span><small>{route.flights.toLocaleString()} flights · {route.delay_percent==null?'Delay rate unavailable':route.delay_percent+'% delayed'}</small>
          </button>)}</div>
          <div className="dataset-route-pages"><button disabled={routePage===1} onClick={()=>setRoutePage(p=>p-1)}>Previous routes</button><span>{routePage} / {coverage.pagination.total_pages||1}</span><button disabled={routePage>=coverage.pagination.total_pages} onClick={()=>setRoutePage(p=>p+1)}>Next routes</button></div>
        </>:<p>Loading airport and route coverage…</p>}
      </section>}
      {selected?<div className="dataset-details ops-page"><button className="scope-back" onClick={()=>select('')}><ArrowLeft size={16}/> Flight list</button>
        <h2>{flightLabel(selected)}</h2><p>{selected.airline_name??'Carrier name unavailable'}</p>
        <div className="dataset-route-title">{selected.origin_bts_code}<Plane size={22}/>{selected.destination_bts_code}</div>
        <p>{selected.origin_name} to {selected.destination_name}</p><p>{selected.flight_date} · Historical observation</p>
        {(!selected.origin_coordinates||!selected.destination_coordinates)&&<p>Airport reference coordinates unavailable for this record.</p>}
        <DelayReasons row={selected}/>
        <button className="ops-primary" disabled={saving||(!selected.cancelled&&!selected.diverted&&(selected.arrival_delay_minutes??0)<=15)} onClick={()=>saveAlert(selected)}><BellPlus size={17}/>{saving?'Saving…':'Save disruption alert'}</button>
        {message&&<p role="status" className="ops-note">{message}</p>}
        <small className="dataset-provenance">{selected.source_file} · row {selected.source_row_number}</small>
      </div>:<>
        <form className="dataset-filters" onSubmit={e=>{e.preventDefault();setPage(1);setFilters({...draft});}}>
          {(['origin','destination','airline','flight'] as const).map(key=><label key={key}>{key==='flight'?'Flight number':key==='airline'?'Airline code':key}<input aria-label={'Dataset '+key} maxLength={key==='flight'?16:3} value={draft[key]} onChange={e=>setDraft({...draft,[key]:e.target.value.toUpperCase()})} placeholder={key==='origin'?'ORD':key==='destination'?'Any airport':key==='airline'?'Any carrier':'Any flight'}/></label>)}
          <label className="dataset-date">Flight date<input aria-label="Dataset date" type="date" value={draft.date} onChange={e=>setDraft({...draft,date:e.target.value})}/></label>
          <label className="dataset-check"><input type="checkbox" checked={draft.delayed} onChange={e=>setDraft({...draft,delayed:e.target.checked})}/>Delayed over 15m</label>
          <button className="dataset-search" disabled={loading}><Search size={16}/>{loading?'Searching…':'Search records'}</button>
        </form>
        <div className="traffic-list scope-list">{error?<p className="dataset-message" role="alert">{error}</p>:loading?<p className="dataset-message">Loading flight records…</p>:!rows.length?<p className="dataset-message">No flights match these filters.</p>:rows.map(r=><button key={identity(r)} onClick={()=>select(identity(r))}>
          <span className="scope-plane"><Plane size={17}/></span><span className="scope-ident"><strong>{flightLabel(r)} · {r.origin_bts_code}–{r.destination_bts_code}</strong><small>{r.airline_name??r.reporting_airline??'Carrier name unavailable'}</small><small>{r.flight_date}</small></span>
          <span className="scope-values"><b className={(r.arrival_delay_minutes??0)>15?'dataset-delayed':''}>{r.cancelled?'Cancelled':r.diverted?'Diverted':r.arrival_delay_minutes==null?'Unknown':r.arrival_delay_minutes>0?'+'+r.arrival_delay_minutes+'m':r.arrival_delay_minutes+'m'}</b><small>arrival</small></span><ChevronRight size={14}/>
        </button>)}</div>
        <footer className="scope-footer"><button aria-label="Previous dataset page" disabled={page===1||loading} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={18}/></button><span>Page {page} of {response?.pagination.total_pages??'—'}</span><button aria-label="Next dataset page" disabled={!response?.pagination.has_next||loading} onClick={()=>setPage(p=>p+1)}><ChevronRight size={18}/></button></footer>
      </>}
    </aside>
  </section>;
}
