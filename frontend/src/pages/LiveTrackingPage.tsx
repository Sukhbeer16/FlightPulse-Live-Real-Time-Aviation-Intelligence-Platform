import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ChevronRight, Globe, Layers, MapPin, Plane, Radar, Search } from 'lucide-react';
import { API_BASE_URL, apiFetch } from '../services/apiConfig';
import { MapLibreTracker } from '../features/tracker/MapLibreTracker';
import { measure, regions, utc, type Region, type Snapshot } from '../features/tracker/airspace';

export function LiveTrackingPage() {
  const [region, setRegion] = useState<Region>('new-york');
  const [custom, setCustom] = useState<[number, number]>();
  const center = custom ?? regions[region].center;
  const [mapCenter, setMapCenter] = useState(center);
  const moved = Math.abs(mapCenter[0] - center[0]) + Math.abs(mapCenter[1] - center[1]) > 0.3;
  const endpoint = custom ? '/airspace?lat=' + custom[1].toFixed(2) + '&lon=' + custom[0].toFixed(2) : '/airspace/' + region;
  const [globe, setGlobe] = useState(false);
  const [result, setResult] = useState<Snapshot>();
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [selectedId, select] = useState('');
  const [query, setQuery] = useState('');
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const controller = new AbortController();
    let timer: number;
    async function refresh() {
      try {
        const snapshot = await apiFetch<Snapshot>(API_BASE_URL + '/api/v1/live' + endpoint, {signal: controller.signal});
        if (controller.signal.aborted) return;
        setResult(snapshot);
        setError(false);
      } catch {
        if (!controller.signal.aborted) setError(true);
      }
      if (!controller.signal.aborted) timer = window.setTimeout(refresh, 30000);
    }
    void refresh();
    const clock = window.setInterval(() => setNow(Date.now()), 10000);
    return () => { controller.abort(); clearTimeout(timer); clearInterval(clock); };
  }, [endpoint, attempt]);
  const flights = useMemo(() => {
    const term = query.trim().toUpperCase();
    return (result?.aircraft ?? []).filter(a => [a.callsign,a.registration,a.id].some(v => v?.toUpperCase().includes(term)))
      .sort((a,b) => a.callsign.localeCompare(b.callsign));
  }, [result, query]);
  const selected = flights.find(a => a.id === selectedId);
  const delayed = result && now - result.time > 120000;
  const status = error ? (result ? 'Refresh interrupted' : 'Feed unavailable') : !result ? 'Connecting' : delayed ? 'Delayed feed' : 'Live feed';
  function changeRegion(next: Region, point?: [number, number]) {
    setRegion(next); setCustom(point); setResult(undefined); select(''); setQuery(''); setError(false);
  }
  return <section className="radar-workspace">
    <div className="radar-stage">
      <MapLibreTracker aircraft={flights} selected={selected} center={center} globe={globe} onSelect={select} onMove={setMapCenter} />
      <div className="radar-tools">
        <label className="region-picker"><MapPin size={17}/><select aria-label="Tracking region" value={custom ? 'custom' : region} onChange={e => changeRegion(e.target.value as Region)}>{custom && <option value="custom">Map area</option>}{Object.entries(regions).map(([key,r]) => <option key={key} value={key}>{r.name}</option>)}</select></label>
        <div className="mode-picker" aria-label="Map projection">
          <button aria-pressed={!globe} onClick={() => setGlobe(false)}><Layers size={16}/>2D</button>
          <button aria-pressed={globe} onClick={() => setGlobe(true)}><Globe size={16}/>3D</button>
        </div>
      </div>
      {moved && <button className="search-area" onClick={() => changeRegion(region, mapCenter)}>Search this area</button>}
      <div className="map-legend"><i/> Aircraft {selected && <><i className="focused"/> Selected</>}</div>
    </div>
    <aside className="traffic-panel" aria-label="Aircraft data">
      <div className="traffic-intro"><div className="traffic-kicker"><Radar size={17}/> REGIONAL RADAR</div>
        <h1>{custom ? 'Map area' : regions[region].name + ' airspace'}</h1>
        <div className="traffic-meta"><span className={'feed-state ' + (status === 'Live feed' ? 'connected' : '')}>{status}</span><span>80 NM radius</span></div>
      </div>
      {selected ? <div className="detail-body">
        <button className="back-link" onClick={() => select('')}><ArrowLeft size={15}/> Aircraft list</button>
        <div className="aircraft-title"><Plane/><h2>{selected.callsign}</h2></div>
        <p>{[selected.type, selected.registration].filter(Boolean).join(' · ') || selected.id.toUpperCase()}</p>
        <div className="metric-grid">{[
          ['Altitude', measure(selected.altitude,'ft')], ['Ground speed', measure(selected.speed,'kt')],
          ['Track', measure(selected.heading,'°')], ['Vertical rate', measure(selected.verticalRate,'ft/min')],
        ].map(([label,v]) => <div key={label}><small>{label}</small><strong>{v}</strong></div>)}</div>
        <dl>{[['ICAO address',selected.id.toUpperCase()],['Squawk',selected.squawk || '—'],['Latitude',selected.lat.toFixed(4)+'°'],['Longitude',selected.lon.toFixed(4)+'°'],['Position time',utc(selected.observed)]].map(([k,v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      </div> : <>
        <div className="list-head"><h2>Aircraft <span>{flights.length}</span></h2>
          <label className="traffic-search"><Search size={17}/><input aria-label="Search aircraft" placeholder="Callsign, registration or ICAO" value={query} onChange={e => setQuery(e.target.value)}/></label>
        </div>
        <div className="traffic-list">
          {flights.map(a => <button key={a.id} onClick={() => select(a.id)}><span className="plane-tile"><Plane size={18}/></span>
            <span className="aircraft-ident"><strong>{a.callsign}</strong><small>{a.registration || a.id.toUpperCase()}{a.type && ' · ' + a.type}</small></span>
            <span className="roster-values"><b>{a.ground ? 'Ground' : measure(a.altitude,'ft')}</b><small>{measure(a.speed,'kt')}</small></span><ChevronRight size={15}/></button>)}
          {!flights.length && <p className="empty-airspace">{error && !result ? 'The aircraft feed is unavailable. Retrying automatically.' : !result ? 'Receiving aircraft positions…' : query ? 'No aircraft match your search.' : 'No recent positions reported in this region.'}</p>}
        </div>
      </>}
      <footer><a href="https://www.adsb.lol/" target="_blank" rel="noreferrer">ADS-B · adsb.lol</a><span>{result ? utc(result.time) : 'Awaiting report'}</span>{error && <button onClick={() => setAttempt(a => a+1)}>Retry</button>}</footer>
    </aside>
  </section>;
}
