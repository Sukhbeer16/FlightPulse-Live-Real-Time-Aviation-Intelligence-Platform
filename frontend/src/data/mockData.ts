// ─────────────────────────────────────────────
// FlightPulse Live — Mock / Demo Data
// All data in this file is clearly labelled DEMO.
// Replace with live API calls as backends come online.
// ─────────────────────────────────────────────

import type {
  Aircraft,
  KpiMetric,
  DelayTrendPoint,
  AirlinePerformance,
  FlightActivitySummary,
  AnomalyEvent,
  ActivityEvent,
  SystemStatus,
} from '../types';

// ── Demo Aircraft ─────────────────────────────

export const DEMO_AIRCRAFT: Aircraft[] = [
  {
    icao24: 'a1b2c3',
    callsign: 'UAL328',
    originCountry: 'United States',
    longitude: -87.6298,
    latitude: 41.8781,
    baroAltitude: 10668,
    onGround: false,
    velocity: 248,
    trueTrack: 270,
    verticalRate: 0,
    squawk: '2471',
    positionSource: 0,
    lastContact: Date.now() / 1000,
    isDemo: true,
  },
  {
    icao24: 'd4e5f6',
    callsign: 'AAL102',
    originCountry: 'United States',
    longitude: -73.7781,
    latitude: 40.6413,
    baroAltitude: 7620,
    onGround: false,
    velocity: 215,
    trueTrack: 45,
    verticalRate: -3.5,
    squawk: '4521',
    positionSource: 0,
    lastContact: Date.now() / 1000,
    isDemo: true,
  },
  {
    icao24: 'g7h8i9',
    callsign: 'DAL456',
    originCountry: 'United States',
    longitude: -84.4277,
    latitude: 33.6407,
    baroAltitude: 11278,
    onGround: false,
    velocity: 262,
    trueTrack: 180,
    verticalRate: 0,
    squawk: '3310',
    positionSource: 0,
    lastContact: Date.now() / 1000,
    isDemo: true,
  },
  {
    icao24: 'j1k2l3',
    callsign: 'SWA789',
    originCountry: 'United States',
    longitude: -118.4085,
    latitude: 33.9425,
    baroAltitude: 6096,
    onGround: false,
    velocity: 193,
    trueTrack: 320,
    verticalRate: 5.2,
    squawk: '1200',
    positionSource: 0,
    lastContact: Date.now() / 1000,
    isDemo: true,
  },
  {
    icao24: 'm4n5o6',
    callsign: 'BAW175',
    originCountry: 'United Kingdom',
    longitude: -0.4614,
    latitude: 51.4775,
    baroAltitude: 12192,
    onGround: false,
    velocity: 280,
    trueTrack: 240,
    verticalRate: 0,
    squawk: '5230',
    positionSource: 0,
    lastContact: Date.now() / 1000,
    isDemo: true,
  },
  {
    icao24: 'p7q8r9',
    callsign: 'DLH441',
    originCountry: 'Germany',
    longitude: 8.5706,
    latitude: 50.0379,
    baroAltitude: 11582,
    onGround: false,
    velocity: 271,
    trueTrack: 95,
    verticalRate: 0,
    squawk: '6104',
    positionSource: 0,
    lastContact: Date.now() / 1000,
    isDemo: true,
  },
];

// ── KPI Metrics ───────────────────────────────

export const DEMO_KPI_METRICS: KpiMetric[] = [
  {
    id: 'aircraft_tracked',
    label: 'Aircraft Tracked',
    value: '9,847',
    unit: 'aircraft',
    change: 3.2,
    changeLabel: 'vs last hour',
    trend: 'up',
    isDemo: true,
  },
  {
    id: 'aircraft_airborne',
    label: 'Aircraft Airborne',
    value: '6,213',
    unit: 'in flight',
    change: -1.1,
    changeLabel: 'vs last hour',
    trend: 'down',
    isDemo: true,
  },
  {
    id: 'delay_rate',
    label: 'Historical Delay Rate',
    value: '18.4',
    unit: '%',
    change: -2.3,
    changeLabel: 'Jan–Feb 2024',
    trend: 'down',
    isDemo: false, // Derived from BTS ingested data
  },
  {
    id: 'anomalies',
    label: 'Anomalies Detected',
    value: '12',
    unit: 'today',
    change: 4,
    changeLabel: 'vs yesterday',
    trend: 'up',
    isDemo: true,
  },
];

// ── Historical Delay Trend (BTS Jan–Feb 2024 approximate) ────

export const DEMO_DELAY_TREND: DelayTrendPoint[] = [
  { month: 'Jan 2023', avgDelayMin: 22.4, delayRate: 19.1, totalFlights: 512000 },
  { month: 'Feb 2023', avgDelayMin: 24.1, delayRate: 21.3, totalFlights: 468000 },
  { month: 'Mar 2023', avgDelayMin: 18.7, delayRate: 16.8, totalFlights: 597000 },
  { month: 'Apr 2023', avgDelayMin: 20.3, delayRate: 18.2, totalFlights: 574000 },
  { month: 'May 2023', avgDelayMin: 21.9, delayRate: 19.7, totalFlights: 601000 },
  { month: 'Jun 2023', avgDelayMin: 26.8, delayRate: 24.1, totalFlights: 618000 },
  { month: 'Jul 2023', avgDelayMin: 28.2, delayRate: 25.4, totalFlights: 631000 },
  { month: 'Aug 2023', avgDelayMin: 25.6, delayRate: 22.8, totalFlights: 624000 },
  { month: 'Sep 2023', avgDelayMin: 19.4, delayRate: 17.3, totalFlights: 580000 },
  { month: 'Oct 2023', avgDelayMin: 17.8, delayRate: 15.9, totalFlights: 575000 },
  { month: 'Nov 2023', avgDelayMin: 20.1, delayRate: 17.9, totalFlights: 541000 },
  { month: 'Dec 2023', avgDelayMin: 29.3, delayRate: 26.2, totalFlights: 563000 },
  { month: 'Jan 2024', avgDelayMin: 21.2, delayRate: 18.6, totalFlights: 524000 },
  { month: 'Feb 2024', avgDelayMin: 22.8, delayRate: 19.8, totalFlights: 481000 },
];

// ── Airline Performance ───────────────────────

export const DEMO_AIRLINE_PERFORMANCE: AirlinePerformance[] = [
  { airline: 'Delta Air Lines', code: 'DL', onTimeRate: 83.2, avgDelay: 14.1, totalFlights: 98420, cancelRate: 1.2 },
  { airline: 'Southwest Airlines', code: 'WN', onTimeRate: 79.4, avgDelay: 17.8, totalFlights: 112300, cancelRate: 2.1 },
  { airline: 'American Airlines', code: 'AA', onTimeRate: 77.8, avgDelay: 19.2, totalFlights: 105600, cancelRate: 1.8 },
  { airline: 'United Airlines', code: 'UA', onTimeRate: 81.1, avgDelay: 16.4, totalFlights: 94100, cancelRate: 1.5 },
  { airline: 'Alaska Airlines', code: 'AS', onTimeRate: 85.6, avgDelay: 12.3, totalFlights: 42800, cancelRate: 0.9 },
  { airline: 'JetBlue Airways', code: 'B6', onTimeRate: 73.2, avgDelay: 23.1, totalFlights: 51200, cancelRate: 2.4 },
  { airline: 'Spirit Airlines', code: 'NK', onTimeRate: 69.8, avgDelay: 26.4, totalFlights: 38900, cancelRate: 3.1 },
];

// ── Flight Activity Summary ────────────────────

export const DEMO_FLIGHT_ACTIVITY: FlightActivitySummary[] = [
  { date: 'Jan 15', departures: 18240, arrivals: 18120, cancelled: 312, diverted: 48 },
  { date: 'Jan 22', departures: 19100, arrivals: 18980, cancelled: 289, diverted: 41 },
  { date: 'Jan 29', departures: 17800, arrivals: 17690, cancelled: 410, diverted: 62 },
  { date: 'Feb 05', departures: 16900, arrivals: 16820, cancelled: 540, diverted: 78 },
  { date: 'Feb 12', departures: 18400, arrivals: 18300, cancelled: 298, diverted: 52 },
  { date: 'Feb 19', departures: 17200, arrivals: 17100, cancelled: 380, diverted: 55 },
  { date: 'Feb 26', departures: 18700, arrivals: 18580, cancelled: 265, diverted: 44 },
];

// ── Anomaly Events ────────────────────────────

export const DEMO_ANOMALY_EVENTS: AnomalyEvent[] = [
  {
    id: 'anom-001',
    aircraftId: 'a1b2c3',
    callsign: 'UAL328',
    timestamp: Date.now() - 300000,
    anomalyType: 'altitude',
    severity: 'medium',
    description: 'Unusual altitude drop detected — 800ft in 90 seconds',
    latitude: 41.8781,
    longitude: -87.6298,
    score: 0.74,
    isDemo: true,
  },
  {
    id: 'anom-002',
    aircraftId: 'x9y0z1',
    callsign: 'SKW4411',
    timestamp: Date.now() - 900000,
    anomalyType: 'trajectory',
    severity: 'low',
    description: 'Minor trajectory deviation from filed flight plan',
    latitude: 39.9526,
    longitude: -75.1652,
    score: 0.61,
    isDemo: true,
  },
  {
    id: 'anom-003',
    aircraftId: 'r2s3t4',
    callsign: 'FDX801',
    timestamp: Date.now() - 1800000,
    anomalyType: 'squawk',
    severity: 'high',
    description: 'Squawk 7700 emergency code broadcast',
    latitude: 33.6407,
    longitude: -84.4277,
    score: 0.93,
    isDemo: true,
  },
];

// ── Activity Feed ─────────────────────────────

export const DEMO_ACTIVITY_EVENTS: ActivityEvent[] = [
  {
    id: 'act-001',
    type: 'anomaly_detected',
    title: 'Anomaly Detected',
    description: 'UAL328 — Altitude anomaly flagged by Isolation Forest (score: 0.74)',
    timestamp: new Date(Date.now() - 300000).toISOString(),
    severity: 'warning',
    isDemo: true,
  },
  {
    id: 'act-002',
    type: 'prediction_made',
    title: 'Delay Prediction',
    description: 'ORD→LAX — XGBoost predicts 23 min delay (82% confidence)',
    timestamp: new Date(Date.now() - 720000).toISOString(),
    severity: 'info',
    isDemo: true,
  },
  {
    id: 'act-003',
    type: 'aircraft_tracked',
    title: 'New Aircraft Acquired',
    description: 'BAW175 entered monitored airspace over North Atlantic',
    timestamp: new Date(Date.now() - 1200000).toISOString(),
    severity: 'info',
    isDemo: true,
  },
  {
    id: 'act-004',
    type: 'anomaly_detected',
    title: 'Emergency Squawk',
    description: 'FDX801 broadcast squawk 7700 — monitoring active',
    timestamp: new Date(Date.now() - 1800000).toISOString(),
    severity: 'critical',
    isDemo: true,
  },
  {
    id: 'act-005',
    type: 'data_updated',
    title: 'BTS Analytics Refreshed',
    description: 'Historical performance data updated — Jan & Feb 2024 processed',
    timestamp: new Date(Date.now() - 3600000).toISOString(),
    severity: 'info',
    isDemo: false,
  },
  {
    id: 'act-006',
    type: 'prediction_made',
    title: 'Delay Prediction',
    description: 'JFK→MIA — Random Forest predicts on-time arrival (76% confidence)',
    timestamp: new Date(Date.now() - 4800000).toISOString(),
    severity: 'info',
    isDemo: true,
  },
];

// ── System Status ─────────────────────────────

export const DEMO_SYSTEM_STATUS: SystemStatus = {
  opensky: 'disconnected',
  btsApi: 'connected',
  mlService: 'disconnected',
  lastUpdated: new Date().toISOString(),
};

