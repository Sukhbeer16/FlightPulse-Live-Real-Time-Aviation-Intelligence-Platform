import { useEffect, useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { Activity, ChevronDown } from 'lucide-react';

export function Topbar() {
  const { pathname } = useLocation();
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  const links = [['/overview', 'Overview'], ['/delay-prediction', 'Delays'], ['/anomaly-detection', 'Alerts'], ['/historical', 'History'], ['/disruption', 'Disruptions'], ['/system-status', 'System status'], ['/settings', 'Settings']];
  return <header className="fp-header">
    <Link to="/" className="fp-brand"><Activity aria-hidden="true" />FlightPulse</Link>
    <nav aria-label="Main navigation">
      <NavLink className={pathname === '/live-tracking' || pathname === '/' ? 'active' : ''} to="/">Flight radar</NavLink>
      {links.slice(0, 3).map(([to, label]) => <NavLink key={to} to={to}>{label}</NavLink>)}
      <details key={pathname} className="fp-more"><summary>More <ChevronDown size={14}/></summary><div>{links.slice(3).map(([to,label]) => <NavLink key={to} to={to}>{label}</NavLink>)}</div></details>
    </nav>
    <time>{now.toISOString().slice(11,19)} UTC</time>
  </header>;
}
