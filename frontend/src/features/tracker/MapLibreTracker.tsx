import { useEffect, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { Aircraft } from './airspace';
import { aircraftPath, attribution, colors, elevatedAircraft, tileUrl, type Position } from './aircraftDrawing';
import { RasterRadar } from './RasterRadar';

function aircraftIcon(fill: string) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 48;
  const ctx = canvas.getContext('2d')!;
  ctx.scale(2, 2);
  const path = new Path2D(aircraftPath);
  ctx.lineWidth = 1.5;
  ctx.lineJoin = 'round';
  ctx.strokeStyle = '#101b25';
  ctx.stroke(path);
  ctx.fillStyle = fill;
  ctx.fill(path);
  return ctx.getImageData(0, 0, 48, 48);
}

function rangeRing([lon,lat]: Position, nm: number): Position[] {
  const rad = Math.PI/180, radius = nm * 1852 / 6371008.8, phi = lat * rad;
  return Array.from({length:145}, (_,i) => {
    const angle = i * 2 * Math.PI / 144;
    const y = Math.asin(Math.sin(phi)*Math.cos(radius)+Math.cos(phi)*Math.sin(radius)*Math.cos(angle));
    const x = lon*rad + Math.atan2(Math.sin(angle)*Math.sin(radius)*Math.cos(phi),Math.cos(radius)-Math.sin(phi)*Math.sin(y));
    return [x/rad,y/rad];
  });
}

interface Props {
  routes?: {id:string; coordinates:Position[]}[]; routeMode?: boolean;
  aircraft: Aircraft[]; selected?: Aircraft; onSelect: (id: string) => void;
  center: Position; globe: boolean; onMove: (center: Position) => void;
  onGraphicsUnavailable: (unavailable: boolean) => void;
}
export function MapLibreTracker({ aircraft, selected, onSelect, center, globe, onMove, onGraphicsUnavailable, routes, routeMode=false }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map>();
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(7);
  const initial = useRef(center);
  useEffect(() => {
    let map: maplibregl.Map;
    function unavailable() {setFailed(true); onGraphicsUnavailable(true);}
    try {
      map = new maplibregl.Map({
        container: container.current!, center: initial.current, zoom: routeMode?3.5:7, minZoom: 2,
        maxZoom: 18, attributionControl: {compact: true},
        style: { version: 8, sources: { streets: {
          type: 'raster', tileSize: 256, maxzoom: 19, tiles: [tileUrl], attribution,
        } }, layers: [
          { id: 'base', type: 'background', paint: {'background-color': '#122b3a'} },
          { id: 'streets', source: 'streets', type: 'raster', paint: {
            'raster-brightness-min':0.92,'raster-brightness-max':0.045,
            'raster-hue-rotate':170,'raster-saturation':-0.48,'raster-opacity':0.81,
          } },
        ] },
      });
    } catch { unavailable(); return; }
    mapRef.current = map;
    map.getCanvas().addEventListener('webglcontextlost', unavailable);
    map.on('moveend', () => { const p = map.getCenter().wrap(); onMove([p.lng, p.lat]); });
    map.on('zoomend', () => setZoom(map.getZoom()));
    map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
    map.addControl(new maplibregl.ScaleControl({unit: 'nautical'}), 'bottom-left');
    map.on('style.load', () => {
      for (const [name, color] of Object.entries(colors)) {
        map.addImage(name, aircraftIcon(color), {pixelRatio: 2});
      }
      for (const name of ['range', 'traffic', 'elevated', 'routes']) {
        map.addSource(name, {type: 'geojson', data: {type: 'FeatureCollection', features: []}});
      }
      map.addLayer({id:'range-lines', type:'line', source:'range', paint:{
        'line-color':'#72c6d1','line-opacity':0.32,'line-width':1,'line-dasharray':[5,7],
      }});
      map.addLayer({id:'dataset-routes',type:'line',source:'routes',paint:{
        'line-color':['case',['get','selected'],'#58dec4','#739da9'],
        'line-width':['case',['get','selected'],3,1.2],
        'line-opacity':['case',['get','selected'],1,.35],
      }});
      map.addLayer({id:'focus-ring', type:'circle', source:'traffic', filter:['==',['get','selected'],true],
        paint:{'circle-radius':18,'circle-color':'#49efcb','circle-opacity':0.15,
          'circle-stroke-color':'#49efcb','circle-stroke-width':1.5}});
      map.addLayer({id:'traffic',type:'symbol',source:'traffic',layout:{
        'icon-image':['get','symbol'],'icon-rotate':['get','heading'],'icon-rotation-alignment':'map',
        'icon-pitch-alignment':'viewport',
        'icon-size':['interpolate',['linear'],['zoom'],4,.48,7,.85,10,1.15],
        'icon-allow-overlap':true,'icon-ignore-placement':true,
        'symbol-sort-key':['case',['get','selected'],2,['==',['get','symbol'],'ground'],0,1],
      }});
      map.addLayer({id:'traffic-3d',type:'fill-extrusion',source:'elevated',layout:{visibility:'none'},
        paint:{'fill-extrusion-color':['get','color'],'fill-extrusion-base':['get','altitude'],
          'fill-extrusion-height':['+', ['get','altitude'], 20], 'fill-extrusion-vertical-gradient':false}});
      setReady(true);
    });
    const tooltip = new maplibregl.Popup({closeButton:false,closeOnClick:false,offset:11,className:'scope-tooltip'});
    for (const layer of ['traffic','traffic-3d']) {
      map.on('click',layer,e=>{const id=e.features?.[0]?.properties.id;if(id) onSelect(id);tooltip.remove();});
      map.on('mousemove',layer,e=>{
        const a=e.features?.[0]?.properties;
        if(!a) return;
        map.getCanvas().style.cursor='pointer';
        tooltip.setLngLat(e.lngLat).setText(a.callsign).addTo(map);
      });
      map.on('mouseleave',layer,()=>{map.getCanvas().style.cursor='';tooltip.remove();});
    }
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(container.current!);
    return () => {
      observer.disconnect();tooltip.remove();
      map.getCanvas().removeEventListener('webglcontextlost',unavailable);
      map.remove();mapRef.current=undefined;
    };
  }, [onSelect,onMove,onGraphicsUnavailable]);
  useEffect(() => {
    if (!ready || failed) return;
    const map=mapRef.current!;
    map.getSource<GeoJSONSource>('routes')?.setData({type:'FeatureCollection',features:(routes??[]).map(r=>({
      type:'Feature',properties:{selected:r.id===selected?.id},geometry:{type:'LineString',coordinates:r.coordinates},
    }))});
    const symbol=(a:Aircraft) => a.id===selected?.id ? 'selected' : a.ground ? 'ground' : 'air';
    map.getSource<GeoJSONSource>('traffic')?.setData({
      type:'FeatureCollection',features:aircraft.map(a=>({
        type:'Feature',geometry:{type:'Point',coordinates:[a.lon,a.lat]},
        properties:{id:a.id,callsign:a.callsign,heading:a.heading??0,selected:a.id===selected?.id,symbol:symbol(a)},
      })),
    });
    if (globe) {
      map.getSource<GeoJSONSource>('elevated')?.setData({
        type:'FeatureCollection',features:aircraft.map(a=>({
          type:'Feature',geometry:{type:'Polygon',coordinates:[elevatedAircraft(a,zoom)]},
          properties:{id:a.id,callsign:a.callsign,color:colors[symbol(a)],altitude:a.ground?0:Math.max(0,(a.altitude??0)*.3048)},
        })),
      });
    }
  },[aircraft,selected,globe,zoom,ready,failed,routes]);
  useEffect(()=>{
    if(!ready || failed) return;
    const map=mapRef.current!;
    map.setProjection({type:globe?'globe':'mercator'});
    map.setLayoutProperty('traffic','visibility',globe?'none':'visible');
    map.setLayoutProperty('focus-ring','visibility',globe?'none':'visible');
    map.setLayoutProperty('traffic-3d','visibility',globe?'visible':'none');
    map.getSource<GeoJSONSource>('range')?.setData({type:'FeatureCollection',features:(routeMode?[]:[40,80]).map(nm=>({
      type:'Feature',properties:{},geometry:{type:'LineString',coordinates:rangeRing(center,nm)},
    }))});
    map.easeTo({center,zoom:routeMode?3.5:globe?7.2:7,pitch:globe?52:0,bearing:0,duration:450});
  },[center,globe,ready,failed,routeMode]);
  const current=useRef(selected);
  current.current=selected;
  useEffect(()=>{
    const a=current.current;
    if(a && ready && !failed) mapRef.current?.easeTo({center:[a.lon,a.lat],duration:400});
  },[selected?.id,globe,ready,failed]);
  return <><div className="scope-canvas" ref={container} aria-label="Aircraft map" hidden={failed}/>
    {failed && <RasterRadar aircraft={aircraft} center={center} selected={selected} onSelect={onSelect} onMove={onMove} routes={routes} routeMode={routeMode}/>}</>;
}
