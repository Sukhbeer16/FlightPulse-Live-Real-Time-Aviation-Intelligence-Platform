import { BarChart3 } from 'lucide-react';
import { PlaceholderPage } from './PlaceholderPage';

export function HistoricalAnalyticsPage() {
  return (
    <PlaceholderPage
      Icon={BarChart3}
      title="Historical Analytics"
      description="Deep-dive analytics into BTS historical flight data. Explore delay patterns, airline performance, route statistics and seasonal trends from January–February 2024 and beyond."
      status="PySpark Pipelines Running"
      features={[
        'Full BTS dataset exploration (Jan–Feb 2024 ingested)',
        'PySpark analytics pipeline results',
        'Airport-level delay heatmap',
        'Route performance comparison',
        'Seasonal and day-of-week trend analysis',
        'Carrier punctuality ranking',
        'Cancellation and diversion analysis',
      ]}
    />
  );
}

