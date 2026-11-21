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
  lastContact: number | null;
  isDemo?: boolean;
}

export interface AircraftDetails extends Aircraft {
  origin?: string;
  destination?: string;
  airline?: string;
  aircraftType?: string;
  flightNumber?: string;
}

// ── Comprehensive Aviation Intelligence Types ─

export interface AirportInfo {
  btsCode?: string | null;
  iata: string;
  icao: string;
  name: string;
  city: string;
  country: string;
  coordinates?: [number, number]; // [lon, lat]; omitted when coordinates are unavailable
  timezone: string;
}

export interface AirlineInfo {
  name: string;
  code: string; // IATA code
  icao: string;
  country: string;
  callsign: string;
  color: string;
}

export interface FlightTelemetry {
  latitude: number | null;
  longitude: number | null;
  altitudeFt: number | null;
  groundSpeedKts: number | null;
  headingDeg: number | null;
  verticalRateFpm: number | null;
  squawk: string;
  lastContact: number | null;
}

export interface FlightProgress {
  distanceTotalKm: number;
  distanceElapsedKm: number;
  distanceRemainingKm: number;
  percentage: number;
  departureScheduled: string;
  departureActual?: string;
  arrivalScheduled: string;
  arrivalEstimated: string;
  elapsedTimeMin: number;
  remainingTimeMin: number;
}

export type DelayCategory = 'on_time' | 'minor' | 'moderate' | 'severe';
export type RiskLevel = 'minimal' | 'elevated' | 'high' | 'critical';

export interface AnomalyIndicator {
  id: string;
  type:
    | 'holding_pattern'
    | 'altitude_deviation'
    | 'speed_anomaly'
    | 'squawk_emergency'
    | 'weather_deviation'
    | 'descent_rate_anomaly';
  severity: 'low' | 'medium' | 'high' | 'critical';
  title: string;
  description: string;
  timestamp: string;
  score: number;
}

export interface FlightIntelligence {
  riskScore: number; // 0 - 100
  riskLevel: RiskLevel;
  predictedDelayCategory: string;
  predictedArrivalDelayMin: number;
  confidence: number;
  anomalies: AnomalyIndicator[];
  intelligenceSummary: string;
  actualObservations: string[];
  historicalFacts: string[];
  modelPredictions: string[];
}

export interface FlightTrack {
  sourceDetails?: string[];
  id: string;
  dataKind?: 'historical_bts' | 'live_state_vectors' | 'demo';
  flightNumber: string;
  callsign: string;
  airline: AirlineInfo;
  aircraft: {
    model: string;
    icao24: string;
    registration: string;
    typeCode: string;
  };
  origin: AirportInfo;
  destination: AirportInfo;
  telemetry: FlightTelemetry;
  progress: FlightProgress;
  status: 'active' | 'scheduled' | 'holding' | 'diverted' | 'landed';
  delayCategory: DelayCategory;
  delayMinutes: number;
  intelligence: FlightIntelligence;
  routeWaypoints: [number, number][]; // Array of [lon, lat]
  isDemo: boolean;
}

// ── Alerts Center ─────────────────────────────

export interface AviationAlert {
  id: string;
  flightId: string;
  flightNumber: string;
  airline: string;
  callsign: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  category: 'ANOMALY' | 'WEATHER' | 'AIRSPACE' | 'TELEMETRY' | 'CONGESTION';
  title: string;
  explanation: string;
  detectionTime: string;
  origin: string;
  destination: string;
  coordinates: [number, number] | null; // [lon, lat]; null when no validated coordinate
  riskScore: number;
  status: 'ACTIVE' | 'MONITORING' | 'RESOLVED';
  isDemo: boolean;
}

// ── Tracker Filters ───────────────────────────

export interface TrackerFilterState {
  searchQuery: string;
  selectedAirline: string;
  selectedAirport: string;
  delayFilter: DelayCategory | 'all';
  riskFilter: RiskLevel | 'all';
  statusFilter: string;
  altitudeRange: [number, number];
  showRoutes: boolean;
  showLabels: boolean;
  radarSweeps: boolean;
  viewMode: '2d' | '3d';
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
