import { Zap } from 'lucide-react';
import { PlaceholderPage } from './PlaceholderPage';

export function DisruptionPage() {
  return (
    <PlaceholderPage
      Icon={Zap}
      title="Disruption Intelligence"
      description="Proactive disruption monitoring combining weather data, NOTAMs, airspace restrictions and predictive modelling to anticipate and quantify flight disruption risk."
      status="Planned — Phase 3"
      features={[
        'Weather-correlated delay risk scoring',
        'NOTAM integration and visualisation',
        'Airspace restriction overlay',
        'Airport congestion index',
        'Network effect disruption propagation',
        'Carrier disruption comparison',
      ]}
    />
  );
}

