// ─────────────────────────────────────────────────────────
// FlightPulse Live — Flights API & Simulation Service
// Connects to FastAPI backend with realistic live simulation fallback
// ─────────────────────────────────────────────────────────

import { API_BASE_URL, API_ENDPOINTS, apiFetch } from './apiConfig';
import { DEMO_FLIGHT_TRACKS, DEMO_ALERTS, AIRPORTS, AIRLINES } from '../data/aviationData';
import type { FlightTrack, AviationAlert, TrackerFilterState, KpiMetric } from '../types';

export interface BackendFlightItem {
  id: string;
  source: string;
  source_flight_id: string | null;
  flight_number: string | null;
  callsign: string | null;
  airline_code: string | null;
  origin_airport_id: number | null;
  destination_airport_id: number | null;
  scheduled_departure_at: string;
  scheduled_arrival_at: string | null;
  actual_departure_at: string | null;
  actual_arrival_at: string | null;
  status: string | null;
  updated_at: string;
  airline?: { code: string; name: string } | null;
  origin_airport?: {
    id: number;
    iata_code: string | null;
    icao_code: string | null;
    name: string;
    city: string | null;
    country_code: string | null;
    location?: { type: string; coordinates: [number, number] } | null;
  } | null;
  destination_airport?: {
    id: number;
    iata_code: string | null;
    icao_code: string | null;
    name: string;
    city: string | null;
    country_code: string | null;
    location?: { type: string; coordinates: [number, number] } | null;
  } | null;
}

export interface BackendFlightListResponse {
  data: BackendFlightItem[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  };
}

// ── In-Memory Simulation State ─────────────────────────────

let simulatedFlights: FlightTrack[] = JSON.parse(JSON.stringify(DEMO_FLIGHT_TRACKS));
let simulationSpeedMultiplier: number = 1; // 1x, 2x, 5x, or 0 (paused)
let isLiveBackendActive: boolean = false;

// ── Simulation Step Engine ─────────────────────────────────

export function stepAviationSimulation(deltaSeconds: number = 2): FlightTrack[] {
  if (simulationSpeedMultiplier === 0) return simulatedFlights;

  const effectiveDelta = deltaSeconds * simulationSpeedMultiplier;

  simulatedFlights = simulatedFlights.map((flight) => {
    // If flight has route waypoints, advance position along waypoints
    const wp = flight.routeWaypoints;
    if (!wp || wp.length < 2) return flight;

    // Calculate progression increment
    // 500 knots = ~257 meters/sec = ~0.257 km/sec
    const speedKmSec = ((flight.telemetry.groundSpeedKts || 480) * 1.852) / 3600;
    const distanceStepKm = speedKmSec * effectiveDelta;

    let newElapsed = flight.progress.distanceElapsedKm + distanceStepKm;
    if (newElapsed >= flight.progress.distanceTotalKm) {
      newElapsed = 50; // loop back for continuous simulation
    }

    const newPercentage = Math.min(
      99,
      Math.max(1, Math.round((newElapsed / flight.progress.distanceTotalKm) * 100))
    );
    const newRemainingKm = Math.max(0, flight.progress.distanceTotalKm - newElapsed);

    // Interpolate coordinate along waypoint polyline
    const targetIdx = Math.min(
      wp.length - 1,
      Math.floor((newPercentage / 100) * (wp.length - 1))
    );
    const nextIdx = Math.min(wp.length - 1, targetIdx + 1);

    const [lonA, latA] = wp[targetIdx];
    const [lonB, latB] = wp[nextIdx];

    // Bearing calculation for realistic heading
    const y = Math.sin(((lonB - lonA) * Math.PI) / 180) * Math.cos((latB * Math.PI) / 180);
    const x =
      Math.cos((latA * Math.PI) / 180) * Math.sin((latB * Math.PI) / 180) -
      Math.sin((latA * Math.PI) / 180) *
        Math.cos((latB * Math.PI) / 180) *
        Math.cos(((lonB - lonA) * Math.PI) / 180);
    const heading = Math.round(((Math.atan2(y, x) * 180) / Math.PI + 360) % 360);

    // Micro speed variations (+/- 2 kts)
    const speedJitter = Math.sin(Date.now() / 10000 + (flight.telemetry.altitudeFt ?? 0)) * 2;
    const groundSpeed = Math.round((flight.telemetry.groundSpeedKts || 480) + speedJitter);

    return {
      ...flight,
      telemetry: {
        ...flight.telemetry,
        longitude: lonA,
        latitude: latA,
        headingDeg: heading || flight.telemetry.headingDeg,
        groundSpeedKts: groundSpeed,
        lastContact: Date.now() / 1000,
      },
      progress: {
        ...flight.progress,
        distanceElapsedKm: Math.round(newElapsed),
        distanceRemainingKm: Math.round(newRemainingKm),
        percentage: newPercentage,
        remainingTimeMin: Math.max(5, Math.round(newRemainingKm / (groundSpeed * 0.0308))),
      },
    };
  });

  return simulatedFlights;
}

export function setSimulationSpeed(multiplier: number) {
  simulationSpeedMultiplier = multiplier;
}

export function getSimulationSpeed(): number {
  return simulationSpeedMultiplier;
}

export function isUsingLiveBackend(): boolean {
  return isLiveBackendActive;
}

export function setUseLiveBackend(active: boolean) {
  isLiveBackendActive = active;
}

// ── Flight Data Fetching ───────────────────────────────────

export interface HistoricalFlightItem {
  airline_name?: string | null;
  origin_name?: string | null;
  destination_name?: string | null;
  origin_coordinates?: [number, number] | null;
  destination_coordinates?: [number, number] | null;
  delay_reasons?: {label:string; minutes:number; source:string}[];
  distance_miles: number | null;
  scheduled_elapsed_time_minutes: number | null;
  data_kind: 'historical_bts';
  source_file: string;
  source_row_number: number;
  flight_date: string;
  reporting_airline: string | null;
  flight_number: string | null;
  origin_bts_code: string | null;
  destination_bts_code: string | null;
  scheduled_departure_local_hhmm: number | null;
  actual_departure_local_hhmm: number | null;
  scheduled_arrival_local_hhmm: number | null;
  actual_arrival_local_hhmm: number | null;
  departure_delay_minutes: number | null;
  arrival_delay_minutes: number | null;
  cancelled: number | null;
  diverted: number | null;
  cancellation_code: string | null;
}

export interface HistoricalFlightResponse {
  data_kind: 'historical_bts';
  source_period: string;
  data: HistoricalFlightItem[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  };
}

export async function fetchHistoricalFlights(params: {
  page?: number;
  pageSize?: number;
  flightIdentifier?: string;
  airlineCode?: string;
  origin?: string;
  destination?: string;
  dateFrom?: string;
  dateTo?: string;
  cancelled?: boolean;
  diverted?: boolean;
  delayed?: boolean;
  arrivalDelayMin?: number;
  arrivalDelayMax?: number;
  sortBy?: 'source_row' | 'flight_date' | 'flight_number' | 'departure_delay' | 'arrival_delay';
  sortOrder?: 'asc' | 'desc';
} = {}): Promise<{ flights: FlightTrack[]; source: 'historical_fastapi'; response: HistoricalFlightResponse }> {
  const query = new URLSearchParams();
  query.set('page', String(params.page ?? 1));
  query.set('page_size', String(params.pageSize ?? 50));
  if (params.flightIdentifier) query.set('flight_identifier', params.flightIdentifier);
  if (params.airlineCode) query.set('airline_code', params.airlineCode);
  if (params.origin) query.set('origin', params.origin);
  if (params.destination) query.set('destination', params.destination);
  if (params.dateFrom) query.set('date_from', params.dateFrom);
  if (params.dateTo) query.set('date_to', params.dateTo);
  if (params.cancelled !== undefined) query.set('cancelled', String(params.cancelled));
  if (params.diverted !== undefined) query.set('diverted', String(params.diverted));
  if (params.delayed !== undefined) query.set('delayed', String(params.delayed));
  if (params.arrivalDelayMin !== undefined) query.set('arrival_delay_min', String(params.arrivalDelayMin));
  if (params.arrivalDelayMax !== undefined) query.set('arrival_delay_max', String(params.arrivalDelayMax));
  if (params.sortBy) query.set('sort_by', params.sortBy);
  if (params.sortOrder) query.set('sort_order', params.sortOrder);

  const response = await apiFetch<HistoricalFlightResponse>(
    `${API_ENDPOINTS.historicalFlights}?${query.toString()}`
  );
  const mapped = response.data.map((item): FlightTrack => {
    const airlineCode = item.reporting_airline ?? 'N/A';
    const flightNumber = item.flight_number ?? airlineCode;
    const arrivalDelay = item.arrival_delay_minutes;
    const delayCategory: FlightTrack['delayCategory'] =
      arrivalDelay == null ? 'on_time' :
      arrivalDelay > 60 ? 'severe' :
      arrivalDelay > 30 ? 'moderate' :
      arrivalDelay > 15 ? 'minor' : 'on_time';
    const delayMinutes = arrivalDelay ?? 0;
    return {
      id: `historical-${item.source_file}-${item.source_row_number}`,
      dataKind: 'historical_bts',
      sourceDetails: [item.flight_date, item.source_file + ' / row ' + item.source_row_number,
        'BTS route ' + item.origin_bts_code + ' to ' + item.destination_bts_code,
        'Observed arrival delay (minutes) ' + (item.arrival_delay_minutes ?? 'unavailable'),
        'Cancelled ' + (item.cancelled ?? 'unknown') + ' / diverted ' + (item.diverted ?? 'unknown')],
      flightNumber,
      callsign: `${airlineCode}${flightNumber}`,
      airline: {
        name: item.airline_name ?? 'BTS reporting carrier',
        code: airlineCode,
        icao: airlineCode,
        country: 'US',
        callsign: airlineCode,
        color: '#25BCEB',
      },
      aircraft: {
        model: 'Not provided by BTS record',
        icao24: 'Not provided',
        registration: 'Not provided',
        typeCode: 'Unknown',
      },
      origin: {
        btsCode: item.origin_bts_code,
        iata: item.origin_bts_code ?? 'Unknown',
        icao: 'Unknown',
        name: item.origin_name ?? 'BTS origin code',
        coordinates: item.origin_coordinates ?? undefined,
        city: 'Not provided',
        country: 'US',
        timezone: 'Source-local',
      },
      destination: {
        btsCode: item.destination_bts_code,
        iata: item.destination_bts_code ?? 'Unknown',
        icao: 'Unknown',
        name: item.destination_name ?? 'BTS destination code',
        coordinates: item.destination_coordinates ?? undefined,
        city: 'Not provided',
        country: 'US',
        timezone: 'Source-local',
      },
      telemetry: {
        longitude: null,
        latitude: null,
        altitudeFt: null,
        groundSpeedKts: null,
        headingDeg: null,
        verticalRateFpm: null,
        squawk: 'Not provided',
        lastContact: null,
      },
      progress: {
        distanceTotalKm: 0,
        distanceElapsedKm: 0,
        distanceRemainingKm: 0,
        percentage: 0,
        departureScheduled: item.scheduled_departure_local_hhmm == null
          ? 'Unknown' : String(item.scheduled_departure_local_hhmm).padStart(4, '0'),
        arrivalScheduled: item.scheduled_arrival_local_hhmm == null
          ? 'Unknown' : String(item.scheduled_arrival_local_hhmm).padStart(4, '0'),
        arrivalEstimated: item.actual_arrival_local_hhmm == null
          ? 'Unknown' : String(item.actual_arrival_local_hhmm).padStart(4, '0'),
        elapsedTimeMin: 0,
        remainingTimeMin: 0,
      },
      status: item.cancelled ? 'scheduled' : item.diverted ? 'diverted' : 'landed',
      delayCategory,
      delayMinutes,
      intelligence: {
        riskScore: 0,
        riskLevel: 'minimal',
        predictedDelayCategory: arrivalDelay == null ? 'Unknown' : arrivalDelay > 15 ? 'Delayed >15m' : 'Not delayed',
        predictedArrivalDelayMin: arrivalDelay ?? 0,
        confidence: 0,
        anomalies: [],
        intelligenceSummary: 'Historical BTS source record; no live telemetry or model prediction is claimed.',
        actualObservations: [
          arrivalDelay == null ? 'Arrival delay not provided.' : `Observed arrival delay: ${arrivalDelay} minutes.`,
          item.cancelled ? 'Cancelled in source record.' : 'No cancellation in source record.',
        ],
        historicalFacts: [
          `Source period: ${response.source_period}`,
          `Source row: ${item.source_row_number}`,
        ],
        modelPredictions: ['No live model prediction applied.'],
      },
      routeWaypoints: [],
      isDemo: false,
    };
  });
  return { flights: mapped, source: 'historical_fastapi', response };
}

export interface LiveStateItem {
  icao24: string;
  callsign: string | null;
  origin_country: string;
  time_position: number | null;
  last_contact: number;
  longitude: number | null;
  latitude: number | null;
  barometric_altitude_m: number | null;
  on_ground: boolean;
  velocity_mps: number | null;
  true_track_degrees: number | null;
  vertical_rate_mps: number | null;
  geometric_altitude_m: number | null;
  squawk: string | null;
  spi: boolean;
  position_source: number;
  category: number | null;
}

export interface LiveStatesResponse {
  cached: boolean;
  data_kind: 'live_state_vectors';
  source: 'opensky';
  source_time: number;
  count: number;
  states: LiveStateItem[];
  limitations: string[];
}

export async function fetchLiveFlights(bounds?: {
  lamin?: number;
  lomin?: number;
  lamax?: number;
  lomax?: number;
}): Promise<{ states: LiveStateItem[]; sourceTime: number; cached?: boolean; unavailable?: string }> {
  const query = new URLSearchParams({
    lamin: String(bounds?.lamin ?? 40),
    lomin: String(bounds?.lomin ?? -75),
    lamax: String(bounds?.lamax ?? 42),
    lomax: String(bounds?.lomax ?? -72),
  });
  try {
    const response = await apiFetch<LiveStatesResponse>(
      `${API_ENDPOINTS.liveStates}?${query.toString()}`
    );
    return { states: response.states, sourceTime: response.source_time, cached: response.cached };
  } catch (error) {
    return {
      states: [],
      sourceTime: 0,
      unavailable: error instanceof Error ? error.message : 'OpenSky unavailable.',
    };
  }
}

export function mapLiveStatesToFlightTracks(
  states: LiveStateItem[],
  sourceTime: number
): FlightTrack[] {
  return states
    .filter((state) =>
      state.longitude !== null &&
      state.latitude !== null &&
      state.longitude >= -180 &&
      state.longitude <= 180 &&
      state.latitude >= -90 &&
      state.latitude <= 90
    )
    .map((state): FlightTrack => {
      const callsign = state.callsign?.trim() || 'UNKNOWN';
      const altitudeFt = state.barometric_altitude_m == null
        ? null
        : Math.round(state.barometric_altitude_m * 3.28084);
      const groundSpeedKts = state.velocity_mps == null
        ? null
        : Math.round(state.velocity_mps * 1.94384);
      return {
        id: state.icao24,
        dataKind: 'live_state_vectors',
        sourceDetails: ['OpenSky observation ' + new Date(state.last_contact * 1000).toISOString(),
          'ICAO24 ' + state.icao24, 'Origin country ' + state.origin_country,
          'Coordinates ' + state.latitude + ', ' + state.longitude,
          'Barometric altitude (m) ' + (state.barometric_altitude_m ?? 'unavailable'),
          'Ground speed (m/s) ' + (state.velocity_mps ?? 'unavailable'),
          'Track (degrees) ' + (state.true_track_degrees ?? 'unavailable'),
          'Vertical rate (m/s) ' + (state.vertical_rate_mps ?? 'unavailable')],
        flightNumber: callsign,
        callsign,
        airline: {
          name: 'OpenSky observed',
          code: 'Unknown',
          icao: 'Unknown',
          country: state.origin_country,
          callsign,
          color: '#38BDF8',
        },
        aircraft: {
          model: 'Not provided',
          icao24: state.icao24,
          registration: 'Not provided',
          typeCode: 'Unknown',
        },
        origin: {
          iata: 'UNK',
          icao: 'UNK',
          name: 'Not provided by OpenSky',
          city: 'Not provided',
          country: state.origin_country,
          timezone: 'UTC',
        },
        destination: {
          iata: 'UNK',
          icao: 'UNK',
          name: 'Not provided by OpenSky',
          city: 'Not provided',
          country: 'Unknown',
          timezone: 'UTC',
        },
        telemetry: {
          longitude: state.longitude,
          latitude: state.latitude,
          altitudeFt,
          groundSpeedKts,
          headingDeg: state.true_track_degrees,
          verticalRateFpm: state.vertical_rate_mps == null
            ? null
            : Math.round(state.vertical_rate_mps * 196.85),
          squawk: state.squawk ?? 'Not provided',
          lastContact: state.last_contact,
        },
        progress: {
          distanceTotalKm: 0,
          distanceElapsedKm: 0,
          distanceRemainingKm: 0,
          percentage: 0,
          departureScheduled: 'Not provided',
          arrivalScheduled: 'Not provided',
          arrivalEstimated: 'Not provided',
          elapsedTimeMin: 0,
          remainingTimeMin: 0,
        },
        status: state.on_ground ? 'landed' : 'active',
        delayCategory: 'on_time',
        delayMinutes: 0,
        intelligence: {
          riskScore: 0,
          riskLevel: 'minimal',
          predictedDelayCategory: 'Not provided',
          predictedArrivalDelayMin: 0,
          confidence: 0,
          anomalies: [],
          intelligenceSummary:
            `OpenSky state-vector observation at source time ${sourceTime}; not a confirmed schedule or route.`,
          actualObservations: [
            'Provider-observed ADS-B/Mode S state vector.',
            state.squawk ? `Transponder code: ${state.squawk}` : 'No transponder code provided.',
          ],
          historicalFacts: ['No confirmed historical flight match has been claimed.'],
          modelPredictions: ['No delay or anomaly model prediction applied.'],
        },
        routeWaypoints: [],
        isDemo: false,
      };
    });
}

export async function fetchFlights(): Promise<{
  flights: FlightTrack[];
  source: 'demo' | 'historical_fastapi';
}> {
  if (isLiveBackendActive) {
    return fetchHistoricalFlights();
  }

  // Explicit simulation mode
  return { flights: simulatedFlights, source: 'demo' };
}

export function filterFlights(
  flights: FlightTrack[],
  filters: Partial<TrackerFilterState>
): FlightTrack[] {
  return flights.filter((flight) => {
    // Search query: match flightNumber, callsign, airline, origin, destination
    if (filters.searchQuery) {
      const q = filters.searchQuery.trim().toLowerCase();
      const match =
        flight.flightNumber.toLowerCase().includes(q) ||
        flight.callsign.toLowerCase().includes(q) ||
        flight.airline.name.toLowerCase().includes(q) ||
        flight.airline.code.toLowerCase().includes(q) ||
        (flight.origin.btsCode ?? flight.origin.iata).toLowerCase().includes(q) ||
        flight.origin.city.toLowerCase().includes(q) ||
        (flight.destination.btsCode ?? flight.destination.iata).toLowerCase().includes(q) ||
        flight.destination.city.toLowerCase().includes(q);
      if (!match) return false;
    }

    // Airline filter
    if (filters.selectedAirline && filters.selectedAirline !== 'all') {
      if (
        flight.airline.code !== filters.selectedAirline &&
        flight.airline.icao !== filters.selectedAirline
      ) {
        return false;
      }
    }

    // Airport filter
    if (filters.selectedAirport && filters.selectedAirport !== 'all') {
      if (
        (flight.origin.btsCode ?? flight.origin.iata) !== filters.selectedAirport &&
        (flight.destination.btsCode ?? flight.destination.iata) !== filters.selectedAirport
      ) {
        return false;
      }
    }

    // Delay category filter
    if (filters.delayFilter && filters.delayFilter !== 'all') {
      if (flight.dataKind === 'live_state_vectors' || flight.delayCategory !== filters.delayFilter) return false;
    }

    if (filters.statusFilter && filters.statusFilter !== 'all' && flight.status !== filters.statusFilter) return false;
    if (filters.altitudeRange && (filters.altitudeRange[0] !== 0 || filters.altitudeRange[1] !== 50000)) {
      const altitude = flight.telemetry.altitudeFt;
      if (altitude == null || altitude < filters.altitudeRange[0] || altitude > filters.altitudeRange[1]) return false;
    }
    // Risk level filter
    if (filters.riskFilter && filters.riskFilter !== 'all') {
      if (!flight.isDemo || flight.intelligence.riskLevel !== filters.riskFilter) return false;
    }

    return true;
  });
}

export async function fetchAlerts(): Promise<AviationAlert[]> {
    const response = await apiFetch<{
    data_kind: 'operational_alerts';
    data: Array<{
      id: string;
      alert_type: string;
      severity: 'info' | 'warning' | 'high';
      flight_reference: string | null;
      timestamp: string;
      explanation: string;
      factors: Array<{ source: string; factor: string; contribution: number }>;
      source: 'demonstration' | 'historical_bts' | 'opensky' | 'adsb_lol';
      title: string;
      origin: string | null;
      destination: string | null;
      airline: string | null;
      delivery_status: string;
      delivery_error: string | null;
      confidence_status: string;
      status: 'open' | 'acknowledged' | 'resolved';
    }>;
  }>(API_ENDPOINTS.alerts + '?page_size=100');
  return response.data.map((alert) => ({
    id: alert.id,
    flightId: alert.flight_reference ?? '',
    flightNumber: alert.flight_reference ?? 'N/A',
    airline: alert.airline ?? alert.source,
    callsign: alert.flight_reference ?? 'DEMO-RISK',
    severity: alert.severity === 'high' ? 'high' : alert.severity === 'warning' ? 'medium' : 'low',
    category: 'TELEMETRY',
    title: alert.title,
    explanation: alert.explanation + ' Evidence: ' + alert.confidence_status + '. Source: ' + alert.source + '. Type: ' + alert.alert_type,
    detectionTime: alert.timestamp,
    origin: alert.origin ?? 'N/A',
    destination: alert.destination ?? 'N/A',
    coordinates: null,
    riskScore: alert.factors.reduce((sum, factor) => sum + factor.contribution, 0),
    status: alert.status === 'resolved' ? 'RESOLVED' : alert.status === 'acknowledged' ? 'MONITORING' : 'ACTIVE',
    isDemo: alert.source === 'demonstration',
    source: alert.source,
    deliveryStatus: alert.delivery_status,
    deliveryError: alert.delivery_error,
  }));

}

export async function checkBackendHealth(): Promise<{
  connected: boolean;
  status: string;
  version?: string;
}> {
  try {
    const res = await apiFetch<{ status: string; service: string; version: string }>(
      API_ENDPOINTS.health
    );
    return { connected: res.status === 'ok', status: res.status, version: res.version };
  } catch {
    return { connected: false, status: 'offline' };
  }
}

export function computeAviationKpis(flights: FlightTrack[]): KpiMetric[] {
  const total = flights.length;
  const delayed = flights.filter((f) => f.delayMinutes > 15).length;
  const highRisk = flights.filter(
    (f) => f.intelligence.riskLevel === 'high' || f.intelligence.riskLevel === 'critical'
  ).length;
  const activeAnomalies = flights.reduce(
    (acc, f) => acc + (f.intelligence.anomalies?.length || 0),
    0
  );

  return [
    {
      id: 'kpi-tracked',
      label: 'Flights Monitored',
      value: total,
      unit: 'aircraft',
      change: 4.8,
      changeLabel: 'vs last hour',
      trend: 'up',
      isDemo: true,
    },
    {
      id: 'kpi-delayed',
      label: 'Delayed Flights (>15m)',
      value: delayed,
      unit: `${Math.round((delayed / (total || 1)) * 100)}%`,
      change: -2.1,
      changeLabel: 'vs peak',
      trend: 'down',
      isDemo: true,
    },
    {
      id: 'kpi-high-risk',
      label: 'High-Risk Flights',
      value: highRisk,
      unit: 'active',
      change: highRisk > 0 ? 1 : 0,
      changeLabel: 'monitored',
      trend: highRisk > 0 ? 'up' : 'neutral',
      isDemo: true,
    },
    {
      id: 'kpi-anomalies',
      label: 'Active Anomalies',
      value: activeAnomalies,
      unit: 'alerts',
      change: 2,
      changeLabel: 'detected',
      trend: activeAnomalies > 0 ? 'up' : 'neutral',
      isDemo: true,
    },
  ];
}
