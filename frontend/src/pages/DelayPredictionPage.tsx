import { DelayPredictionTool } from '../features/intelligence/DelayPredictionTool';
import '../styles/operations.css';

export function DelayPredictionPage() {
  return <div className="ops-page"><div className="ops-wrap">
    <header className="ops-heading"><h1>Delay forecast</h1>
      <p>Explore how a scheduled flight scores against historical arrival patterns.</p>
    </header>
    <DelayPredictionTool />
  </div></div>;
}
export default DelayPredictionPage;
