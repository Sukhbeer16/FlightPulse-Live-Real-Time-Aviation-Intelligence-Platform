import { useEffect, useRef } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Topbar } from '../components/Topbar/Topbar';
import { AlertNotifications } from '../features/alerts/AlertNotifications';
import '../styles/tracker.css';

export function AppLayout() {
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  useEffect(() => {
    main.current?.scrollTo(0, 0);
    const title = main.current?.querySelector('h1')?.textContent?.trim();
    document.title = title ? title + ' · FlightPulse' : 'FlightPulse · Flight radar';
  }, [pathname]);
  return <div className="fp-shell"><AlertNotifications/><Topbar /><main ref={main}><Outlet /></main></div>;
}
