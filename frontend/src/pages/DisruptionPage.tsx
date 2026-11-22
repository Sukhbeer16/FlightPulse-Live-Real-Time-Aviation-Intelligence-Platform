import { HistoricalAssessment } from '../features/intelligence/HistoricalAssessment';
import '../styles/operations.css';

export function DisruptionPage() {
  return <div className="ops-page"><div className="ops-wrap">
    <header className="ops-heading"><h1>Disruption analysis</h1><p>Inspect observed delays and model evidence for an individual flight.</p></header>
    <HistoricalAssessment />
  </div></div>;
}
