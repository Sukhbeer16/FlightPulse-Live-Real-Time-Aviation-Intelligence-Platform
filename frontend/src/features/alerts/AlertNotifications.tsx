import { useEffect } from 'react';
import { fetchAlerts } from '../../services/flightsService';

// Mounted once for every route. Delivery requires an explicit browser permission grant.
export function AlertNotifications() {
  useEffect(() => {
    let stopped = false;
    let timer: number;
    const seen = new Set<string>();
    try { for (const id of JSON.parse(localStorage.getItem('flightpulse.notified') ?? '[]')) seen.add(id); } catch { /* Storage optional. */ }
    async function poll() {
      try {
        const alerts = await fetchAlerts();
        if (stopped) return;
        let enabled = false;
        try {enabled = 'Notification' in window && Notification.permission === 'granted' && localStorage.getItem('flightpulse.notifications') === 'on';} catch { /* Inbox polling works without storage. */ }
        for (const a of alerts) {
          if (seen.has(a.id)) continue;
          if (enabled && a.status === 'ACTIVE' && !a.isDemo && Date.now() - Date.parse(a.detectionTime) < 120000) {
            try {
              const n = new Notification(a.title, {body:a.explanation, tag:a.id});
              n.onclick = () => {window.focus(); window.location.assign('/alerts'); n.close();};
            } catch { /* Native notifications can be unavailable; retain the inbox update. */ }
          }
          seen.add(a.id);
        }
        try {localStorage.setItem('flightpulse.notified', JSON.stringify([...seen].slice(-500)));} catch { /* Still usable without persistence. */ }
        window.dispatchEvent(new Event('flightpulse-alerts-updated'));
      } catch { /* Inbox shows connectivity errors; next poll retries. */ }
      if (!stopped) timer = window.setTimeout(poll, 15000);
    }
    void poll();
    return () => {stopped=true; clearTimeout(timer);};
  },[]);
  return null;
}
