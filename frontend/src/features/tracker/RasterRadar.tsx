import { useEffect, useRef, useState } from 'react';
import { Minus, Plus } from 'lucide-react';
import type { Aircraft } from './airspace';
import { aircraftPath, colors, tileUrl, type Position } from './aircraftDrawing';

function project([lon, lat]: Position, size: number): Position {
  const sin = Math.sin(Math.max(-85.05, Math.min(85.05, lat)) * Math.PI / 180);
  return [(lon + 180) / 360 * size, (.5 - Math.log((1+sin)/(1-sin))/(4*Math.PI))*size];
}
function unproject(x: number, y: number, size: number): Position {
  return [((x / size * 360 + 540) % 360) - 180,
    Math.atan(Math.sinh(Math.PI * (1-2*Math.max(0, Math.min(1,y/size))))) * 180/Math.PI];
}

export function RasterRadar({aircraft, center, selected, onSelect, onMove, routes, routeMode=false}: {
  routes?: {id:string; coordinates:Position[]}[]; routeMode?:boolean;
  aircraft: Aircraft[]; center: Position; selected?: Aircraft;
  onSelect: (id: string) => void; onMove: (position: Position) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({width: 800, height: 600});
  const [position, setPosition] = useState(center);
  const [zoom, setZoom] = useState(routeMode?4:8);
  const drag = useRef<{x:number;y:number;world:Position}>();
  const currentAircraft = useRef(selected);
  currentAircraft.current = selected;
  useEffect(() => {setPosition(center);setZoom(routeMode?4:8);}, [center,routeMode]);
  useEffect(() => {
    const a = currentAircraft.current;
    if (a) setPosition([a.lon, a.lat]);
  }, [selected?.id]);
  useEffect(() => { onMove(position); }, [position, onMove]);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      setBox({width: entry.contentRect.width, height: entry.contentRect.height});
    });
    observer.observe(container.current!);
    return () => observer.disconnect();
  }, []);
  const size = 256 * 2 ** zoom;
  const world = project(position, size);
  const left = world[0] - box.width / 2, top = world[1] - box.height / 2;
  const tiles = [];
  for (let y = Math.max(0, Math.floor(top/256)); y <= Math.min(2**zoom-1, Math.floor((top+box.height)/256)); y++) {
    for (let x = Math.floor(left/256); x <= Math.floor((left+box.width)/256); x++) {
      const index = ((x % 2**zoom) + 2**zoom) % 2**zoom;
      tiles.push(<img draggable={false} alt="" key={[zoom,x,y].join('/')} style={{left:x*256-left, top:y*256-top}}
        src={tileUrl.replace('{z}',String(zoom)).replace('{x}',String(index)).replace('{y}',String(y))} onError={e => {e.currentTarget.style.visibility='hidden';}}/>);
    }
  }
  return <div className="scope-fallback" aria-label="Aircraft map" ref={container}
    onPointerDown={e => {
      if ((e.target as HTMLElement).closest('button, a')) return;
      drag.current={x:e.clientX,y:e.clientY,world};e.currentTarget.setPointerCapture(e.pointerId);
    }}
    onPointerMove={e => {const d=drag.current;if(d) setPosition(unproject(d.world[0]+d.x-e.clientX, d.world[1]+d.y-e.clientY,size));}}
    onPointerUp={()=>{drag.current=undefined;}} onPointerCancel={()=>{drag.current=undefined;}}>
    {tiles}
    {routes && <svg className="dataset-route-overlay" width={box.width} height={box.height} aria-hidden="true">{routes.map(r=><polyline key={r.id}
      points={r.coordinates.map(p=>{const c=project(p,size);return (c[0]-left-Math.round((c[0]-world[0])/size)*size)+','+(c[1]-top);}).join(' ')}
      fill="none" stroke={r.id===selected?.id?'#58dec4':'#739da9'} strokeWidth={r.id===selected?.id?3:1} opacity={r.id===selected?.id?1:.4}/>)}</svg>}
    {aircraft.map(a => {
      const coords=project([a.lon,a.lat], size);
      const x=coords[0]-left-Math.round((coords[0]-world[0])/size)*size, y=coords[1]-top;
      if(x < -20 || y < -20 || x > box.width+20 || y > box.height+20) return null;
      const active=a.id===selected?.id;
      return <button key={a.id} className="scope-fallback-plane" aria-label={'Select '+a.callsign} title={a.callsign}
        style={{left:x,top:y,zIndex:active?2:1,transform:'translate(-50%,-50%) rotate('+(a.heading??0)+'deg)'}}
        onClick={()=>onSelect(a.id)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d={aircraftPath} fill={active?colors.selected:a.ground?colors.ground:colors.air} stroke="#182331" strokeWidth="1"/></svg></button>;
    })}
    <div className="scope-basic-controls"><button aria-label="Zoom in" disabled={zoom>=16} onClick={()=>setZoom(z=>z+1)}><Plus size={17}/></button><button aria-label="Zoom out" disabled={zoom<=2} onClick={()=>setZoom(z=>z-1)}><Minus size={17}/></button></div>
    <div className="scope-attribution">© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a></div>
  </div>;
}
