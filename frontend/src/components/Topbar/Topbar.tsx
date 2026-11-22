import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { Bell, ChartNoAxesCombined, Clock3, Ellipsis, History, Plane, Radar, SlidersHorizontal } from 'lucide-react';
import './topbar.css';

const sections = [
  { to: '/', label: 'Radar', icon: Radar, paths: ['/', '/live-tracking'] },
  { to: '/overview', label: 'Overview', icon: ChartNoAxesCombined, paths: ['/overview', '/intelligence'] },
  { to: '/delay-prediction', label: 'Delays', icon: Clock3, paths: ['/delay-prediction'] },
  { to: '/anomaly-detection', label: 'Alerts', icon: Bell, paths: ['/anomaly-detection', '/alerts'] },
  { to: '/historical', label: 'History', icon: History, paths: ['/historical'] },
];
const secondary = [['/disruption','Disruptions'], ['/system-status','System status'], ['/settings','Settings']];

function UtcClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <time className="shell-time" dateTime={now.toISOString()}>
    <span>{now.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'UTC' })}</span>
    <strong>{now.toISOString().slice(11,19)} <small>UTC</small></strong>
  </time>;
}

export function Topbar() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const more = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (!open) return;
    function closeOutside(e: PointerEvent) {
      if (!more.current?.contains(e.target as Node)) setOpen(false);
    }
    function escape(e: KeyboardEvent) {
      if (e.key === 'Escape') { setOpen(false); opener.current?.focus(); }
    }
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', closeOutside); document.removeEventListener('keydown', escape); };
  }, [open]);
  return <header className="shell-header">
    <Link to="/" className="shell-brand" aria-label="FlightPulse home"><span className="shell-mark"><Plane size={23} fill="currentColor" strokeWidth={1.3}/></span><span>Flight<strong>Pulse</strong></span></Link>
    <nav className="shell-tabs" aria-label="Main navigation">{sections.map(({to,label,icon:Icon,paths}) => {
      const active = paths.includes(pathname);
      return <Link to={to} key={to} aria-current={active ? 'page' : undefined}><Icon size={16} strokeWidth={1.8}/>{label}</Link>;
    })}</nav>
    <div className="shell-right"><UtcClock/><div ref={more} className="shell-menu">
      <button ref={opener} onClick={() => setOpen(v => !v)} aria-label="More navigation" aria-controls="secondary-nav" aria-expanded={open}><Ellipsis size={20}/></button>
      {open && <nav id="secondary-nav" aria-label="More navigation"><div><SlidersHorizontal size={15}/>Workspace</div>{secondary.map(([to,label]) => <NavLink key={to} to={to} onClick={() => setOpen(false)}>{label}</NavLink>)}</nav>}
    </div></div>
  </header>;
}
