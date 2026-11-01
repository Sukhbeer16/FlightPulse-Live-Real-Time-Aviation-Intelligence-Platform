// ─────────────────────────────────────────────
// FlightPulse Live — Core Type Definitions
// ─────────────────────────────────────────────

// ── Aircraft & Live Tracking ──────────────────

export interface Aircraft {
  icao24: string;
  callsign: string | null;
  originCountry: string;
  longitude: number | null;
  latitude: number | null;
  baroAltitude: number | null;
  onGround: boolean;
  velocity: number | null;
  trueTrack: number | null;
  verticalRate: number | null;
  squawk: string | null;
  positionSource: number;
  lastContact: number;
  isDemo?: boolean;
}

export interface AircraftDetails extends Aircraft {
  origin?: string;
  destination?: string;
  airline?: string;
  aircraftType?: string;
  flightNumber?: string;
}

// ── KPI Metrics ───────────────────────────────

export interface KpiMetric {
  id: string;
  label: string;
  value: string | number;
  unit?: string;
  change?: number;
  changeLabel?: string;
  trend?: 'up' | 'down' | 'neutral';
  isDemo?: boolean;
}

// ── Historical Analytics ──────────────────────

export interface DelayTrendPoint {
  month: string;
  avgDelayMin: number;
  delayRate: number;
  totalFlights: number;
}

export interface AirlinePerformance {
  airline: string;
  code: string;
  onTimeRate: number;
  avgDelay: number;
  totalFlights: number;
  cancelRate: number;
}

export interface FlightActivitySummary {
  date: string;
  departures: number;
  arrivals: number;
  cancelled: number;
  diverted: number;
}

// ── Prediction ────────────────────────────────

export interface DelayPredictionRequest {
  origin: string;
  destination: string;
  carrier: string;
  scheduledDeparture: string;
  month: number;
  dayOfWeek: number;
}

export interface DelayPredictionResult {
  predictedDelay: number;
  probability: number;
  confidence: number;
  modelUsed: string;
  features: Record<string, number>;
  isDemo?: boolean;
}

// ── Anomaly Detection ─────────────────────────

export interface AnomalyEvent {
  id: string;
  aircraftId: string;
  callsign: string;
  timestamp: number;
  anomalyType: 'altitude' | 'speed' | 'trajectory' | 'squawk' | 'signal_loss';
  severity: 'low' | 'medium' | 'high' | 'critical';
  description: string;
  latitude?: number;
  longitude?: number;
  score: number;
  isDemo?: boolean;
}

// ── Activity Feed ─────────────────────────────

export type ActivityType =
  | 'aircraft_tracked'
  | 'prediction_made'
  | 'anomaly_detected'
  | 'data_updated'
  | 'system_event';

export interface ActivityEvent {
  id: string;
  type: ActivityType;
  title: string;
  description: string;
  timestamp: string;
  severity?: 'info' | 'warning' | 'critical';
  isDemo: boolean;
}

// ── System Status ─────────────────────────────

export type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'error';

export interface SystemStatus {
  opensky: ConnectionStatus;
  btsApi: ConnectionStatus;
  mlService: ConnectionStatus;
  lastUpdated: string;
}

// ── Navigation ────────────────────────────────

export interface NavItem {
  id: string;
  label: string;
  path: string;
  icon: string;
  badge?: string | number;
}

// ── API ───────────────────────────────────────

export interface ApiResponse<T> {
  data: T;
  success: boolean;
  message?: string;
  timestamp: string;
}

export type LoadingState = 'idle' | 'loading' | 'success' | 'error';

export interface AsyncState<T> {
  data: T | null;
  status: LoadingState;
  error: string | null;
}

