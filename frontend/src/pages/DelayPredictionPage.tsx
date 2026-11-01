import { BrainCircuit } from 'lucide-react';
import { PlaceholderPage } from './PlaceholderPage';

export function DelayPredictionPage() {
  return (
    <PlaceholderPage
      Icon={BrainCircuit}
      title="Delay Prediction"
      description="Machine learning–powered flight delay forecasting using Logistic Regression, Decision Tree, Random Forest and XGBoost models trained on BTS historical data."
      status="ML Models Under Development"
      features={[
        'Route and carrier input form',
        'Multi-model prediction comparison (LR, DT, RF, XGBoost)',
        'Confidence score and probability display',
        'Feature importance visualisation',
        'Historical prediction accuracy tracking',
        'BTS feature engineering pipeline integration',
      ]}
    />
  );
}

