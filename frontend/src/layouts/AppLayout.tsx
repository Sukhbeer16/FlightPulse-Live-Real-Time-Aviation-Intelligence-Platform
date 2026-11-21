import { Outlet } from 'react-router-dom';
import { Topbar } from '../components/Topbar/Topbar';
import '../styles/tracker.css';

export function AppLayout() {
  return <div className="fp-shell"><Topbar /><main><Outlet /></main></div>;
}
