import { ShieldAlert } from 'lucide-react';
import { PlaceholderPage } from './PlaceholderPage';

export function AnomalyDetectionPage() {
  return (
    <PlaceholderPage
      Icon={ShieldAlert}
      title="Anomaly Detection"
      description="Isolation Forest–based aircraft anomaly detection identifying unusual altitude, speed, trajectory, squawk codes and signal patterns in real-time tracking data."
      status="Isolation Forest Under Development"
      features={[
        'Isolation Forest model integration',
        'Real-time anomaly scoring',
        'Anomaly type classification (altitude, speed, trajectory, squawk)',
        'Severity tier display (low / medium / high / critical)',
        'Geographic anomaly map overlay',
        'Historical anomaly timeline',
        'Alert configuration panel',
      ]}
    />
  );
}

