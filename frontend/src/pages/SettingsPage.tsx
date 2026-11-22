import { Link } from 'react-router-dom';
import { Cable, Database, Radio } from 'lucide-react';
import { API_BASE_URL } from '../services/apiConfig';
import '../styles/services.css';

export function SettingsPage() {
  return <div className="service-page"><div className="service-wrap">
    <header><h1>Workspace settings</h1><p>Connections and data sources for this installation.</p></header>
    <section className="service-surface"><h2><Cable/> API connection</h2>
      <dl><div><dt>Base URL</dt><dd>{API_BASE_URL || window.location.origin}</dd></div>
      <div><dt>Routing</dt><dd>{API_BASE_URL ? 'Configured API origin' : 'Same-origin proxy'}</dd></div></dl>
      <p>Set <code>VITE_API_BASE_URL</code> when building the frontend to connect to another API.</p>
      <Link to="/system-status">View connection status</Link>
    </section>
    <section className="service-surface"><h2><Radio/> Radar observations</h2><dl>
      <div><dt>Provider</dt><dd>adsb.lol</dd></div><div><dt>Coverage</dt><dd>80 nautical miles around the selected area</dd></div>
      <div><dt>Feed outage</dt><dd>Last available observation with its capture time</dd></div></dl></section>
    <section className="service-surface"><h2><Database/> Historical records</h2><p>Overview, forecasts, and historical assessments use US Bureau of Transportation Statistics flight records.</p><Link to="/historical">Browse flight history</Link></section>
  </div></div>;
}
