// ─────────────────────────────────────────────────────────
// FlightPulse Live — Delay Prediction ML Sandbox
// Test origin, destination, carrier and departure timing against ML delay model
// ─────────────────────────────────────────────────────────

import React, { useState } from 'react';
import { Cpu, Sparkles, AlertCircle, CheckCircle2, ArrowRight } from 'lucide-react';
import { AIRPORTS, AIRLINES } from '../../data/aviationData';
import { API_BASE_URL, apiFetch } from '../../services/apiConfig';
import type { DelayPredictionRequest, DelayPredictionResult } from '../../types';

export const DelayPredictionTool: React.FC = () => {
  const [origin, setOrigin] = useState('ORD');
  const [destination, setDestination] = useState('LHR');
  const [carrier, setCarrier] = useState('UA');
  const [departureTime, setDepartureTime] = useState('14:30');
  const [month, setMonth] = useState(11);
  const [dayOfWeek, setDayOfWeek] = useState(4);
  const [flightDate, setFlightDate] = useState('2024-02-01');
  const [modelName, setModelName] = useState('logistic-regression');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DelayPredictionResult | null>(null);

  const handlePredict = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const hhmm = Number(departureTime.replace(':', ''));
      const res = await apiFetch<{
        status: 'available' | 'unavailable';
        model_id?: string;
        model_score?: number;
        threshold?: number;
        predicted_class?: 'delayed' | 'not_delayed';
        feature_contributions?: Array<{
          feature: string;
          contribution_logit: number;
          direction: string;
        }>;
        limitations?: string[];
        reason?: string;
      }>(
        API_BASE_URL + `/api/v1/predictions/delay?model=${encodeURIComponent(modelName)}`,
        {
          method: 'POST',
          body: JSON.stringify({
            reporting_airline: carrier,
            origin,
            destination,
            flight_date: flightDate,
            scheduled_departure_hhmm: hhmm,
            scheduled_arrival_hhmm: null,
            scheduled_elapsed_time_minutes: null,
            distance_miles: null,
          }),
        }
      );
      if (res.status !== 'available' || res.model_score == null) {
        setError(res.reason ?? 'Model prediction is unavailable.');
        setResult(null);
      } else {
        setResult({
          predictedDelay: 0,
          probability: res.model_score,
          confidence: 0,
          modelUsed: res.model_id ?? modelName,
          features: Object.fromEntries(
            (res.feature_contributions ?? []).map((item) => [
              item.feature,
              item.contribution_logit,
            ])
          ),
          isDemo: false,
        });
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Prediction unavailable.');
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 rounded-2xl bg-slate-900/80 border border-slate-800/80 backdrop-blur-md shadow-xl text-slate-100 space-y-5">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2">
          <Cpu className="w-5 h-5 text-cyan-400" />
          <h2 className="font-mono text-base font-bold tracking-wider text-slate-100">
            PREDICTIVE DELAY ESTIMATION MODEL
          </h2>
        </div>
        <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-cyan-950/60 border border-cyan-500/30 text-cyan-300">
          BTS HISTORICAL CALIBRATION
        </span>
      </div>

      <form onSubmit={handlePredict} className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-6 gap-3 text-xs font-mono">
        {/* Origin */}
        <div>
          <label className="text-[10px] text-slate-400 uppercase block mb-1">Origin Hub</label>
          <select
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
          >
            {Object.keys(AIRPORTS).map((code) => (
              <option key={code} value={code}>
                {code} - {AIRPORTS[code].city}
              </option>
            ))}
          </select>
        </div>

        {/* Destination */}
        <div>
          <label className="text-[10px] text-slate-400 uppercase block mb-1">Destination Hub</label>
          <select
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
          >
            {Object.keys(AIRPORTS).map((code) => (
              <option key={code} value={code}>
                {code} - {AIRPORTS[code].city}
              </option>
            ))}
          </select>
        </div>

        {/* Carrier */}
        <div>
          <label className="text-[10px] text-slate-400 uppercase block mb-1">Operating Airline</label>
          <select
            value={carrier}
            onChange={(e) => setCarrier(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
          >
            {Object.entries(AIRLINES).map(([code, a]) => (
              <option key={code} value={a.code}>
                {a.code} - {a.name}
              </option>
            ))}
          </select>
        </div>

        {/* Departure Time */}
        <div>
          <label className="text-[10px] text-slate-400 uppercase block mb-1">Departure Time (UTC)</label>
          <input
            type="time"
            value={departureTime}
            onChange={(e) => setDepartureTime(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
          />
        </div>

        {/* Month */}
        <div>
          <label className="text-[10px] text-slate-400 uppercase block mb-1">Flight Date</label>
          <input
            type="date"
            value={flightDate}
            onChange={(e) => setFlightDate(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
          />
        </div>

        <div>
          <label className="text-[10px] text-slate-400 uppercase block mb-1">Model</label>
          <select
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-200"
          >
            <option value="logistic-regression">Logistic Regression</option>
            <option value="random-forest">Random Forest</option>
            <option value="decision-tree">Decision Tree</option>
            <option value="xgboost">XGBoost</option>
          </select>
        </div>

        {/* Submit */}
        <div className="flex items-end">
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 px-3 rounded-lg bg-cyan-600 hover:bg-cyan-500 font-bold text-slate-950 transition-colors flex items-center justify-center gap-1.5 shadow-md shadow-cyan-500/20"
          >
            {loading ? (
              <span>Running...</span>
            ) : (
              <>
                <Sparkles className="w-3.5 h-3.5" />
                <span>COMPUTE</span>
              </>
            )}
          </button>
        </div>
      </form>

      {error && (
        <div className="p-3 rounded-lg border border-red-500/40 bg-red-950/30 text-xs font-mono text-red-300">
          {error}
        </div>
      )}

      {/* Prediction Output Results */}
      {result && (
        <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800/80 space-y-3">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 border-b border-slate-800/60 pb-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-bold text-slate-100">
                {origin} ➔ {destination} ({carrier})
              </span>
              <span className="text-xs text-slate-400 font-mono">
                Departure: {departureTime} UTC
              </span>
            </div>
            <span className="text-[10px] font-mono text-slate-400">
              Model: {result.modelUsed}
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {/* Probability */}
            <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800/70">
              <span className="text-[10px] font-mono text-slate-500 uppercase">Delay Probability</span>
              <div className="text-2xl font-mono font-bold text-cyan-400 mt-0.5">
                {(result.probability * 100).toFixed(0)}%
              </div>
              <span className="text-[10px] font-mono text-slate-400">
                Relative model score for arrival &gt;15m late
              </span>
            </div>

            {/* Actual response metadata */}
            <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800/70">
              <span className="text-[10px] font-mono text-slate-500 uppercase">Top Model Contributions</span>
              <div className="mt-1 space-y-1 max-h-20 overflow-y-auto">
                {Object.entries(result.features).slice(0, 5).map(([feature, value]) => (
                  <div key={feature} className="flex justify-between gap-2 text-[10px] font-mono text-slate-300">
                    <span className="truncate">{feature}</span>
                    <span className={value >= 0 ? 'text-amber-300' : 'text-cyan-300'}>
                      {value >= 0 ? '+' : ''}{value.toFixed(4)}
                    </span>
                  </div>
                ))}
              </div>
              <span className="text-[10px] font-mono text-slate-400">
                Associations, not causes or confidence values
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
