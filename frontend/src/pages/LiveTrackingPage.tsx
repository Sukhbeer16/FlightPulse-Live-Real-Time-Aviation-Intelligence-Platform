import { Radio } from 'lucide-react';
import { PlaceholderPage } from './PlaceholderPage';

export function LiveTrackingPage() {
  return (
    <PlaceholderPage
      Icon={Radio}
      title="Live Flight Tracking"
      description="Real-time aircraft tracking powered by the OpenSky Network API. Monitor global aircraft positions, headings, altitudes and velocities with sub-minute refresh rates."
      status="Awaiting OpenSky Integration"
      features={[
        'Real-time OpenSky Network data ingestion',
        'Full-screen interactive MapLibre map',
        'Aircraft clustering for dense regions',
        'Flight path trail rendering',
        'Altitude and speed filtering',
        'Aircraft detail panel with historical lookup',
        'WebSocket live data streaming',
      ]}
    />
  );
}

