// ─────────────────────────────────────────────────────────
// FlightPulse Live — 3D Earth Aviation Globe (Three.js + R3F)
// Immersive orbital flight tracker with 3D arcs & interactive selection
// ─────────────────────────────────────────────────────────

import React, { useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Html } from '@react-three/drei';
import * as THREE from 'three';
import type { FlightTrack } from '../../types';
import { RotateCw, ZoomIn, ZoomOut, Compass, Sparkles } from 'lucide-react';

const GLOBE_RADIUS = 2.0;

// Convert geographic coordinates (lat, lon) to 3D Cartesian coordinates
export function geoToCartesian(
  lat: number,
  lon: number,
  radius: number = GLOBE_RADIUS
): [number, number, number] {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lon + 180) * (Math.PI / 180);

  const x = -(radius * Math.sin(phi) * Math.cos(theta));
  const z = radius * Math.sin(phi) * Math.sin(theta);
  const y = radius * Math.cos(phi);

  return [x, y, z];
}

// ── Great Circle 3D Arc Component ──────────────────────────

interface FlightArc3DProps {
  flight: FlightTrack;
  isSelected: boolean;
  onSelect: (flight: FlightTrack) => void;
}

const FlightArc3D: React.FC<FlightArc3DProps> = ({ flight, isSelected, onSelect }) => {
  const [hovered, setHovered] = useState(false);

  // Compute 3D curved arc points using Quadratic Bezier Curve
  const { curvePoints, planePos, planeHeading } = useMemo(() => {
    if (flight.dataKind === 'live_state_vectors' && flight.telemetry.latitude != null && flight.telemetry.longitude != null) {
      return { curvePoints: [], planePos: new THREE.Vector3(...geoToCartesian(flight.telemetry.latitude, flight.telemetry.longitude, GLOBE_RADIUS * 1.01)), planeHeading: new THREE.Vector3() };
    }
    if (!flight.origin.coordinates || !flight.destination.coordinates) {
      return { curvePoints: [], planePos: new THREE.Vector3(), planeHeading: new THREE.Vector3() };
    }
    const start = geoToCartesian(flight.origin.coordinates[1], flight.origin.coordinates[0]);
    const end = geoToCartesian(
      flight.destination.coordinates[1],
      flight.destination.coordinates[0]
    );

    const vStart = new THREE.Vector3(...start);
    const vEnd = new THREE.Vector3(...end);

    // Calculate midpoint lifted along surface normal
    const vMid = new THREE.Vector3().addVectors(vStart, vEnd).multiplyScalar(0.5);
    const distance = vStart.distanceTo(vEnd);
    const altitudeElevation = Math.min(1.2, Math.max(0.2, distance * 0.28));
    vMid.normalize().multiplyScalar(GLOBE_RADIUS + altitudeElevation);

    const curve = new THREE.QuadraticBezierCurve3(vStart, vMid, vEnd);
    const points = curve.getPoints(40);

    // Position of plane along arc based on progress percentage
    const t = Math.max(0.01, Math.min(0.99, flight.progress.percentage / 100));
    const planePoint = curve.getPoint(t);
    const tangent = curve.getTangent(t);

    return {
      curvePoints: points,
      planePos: planePoint,
      planeHeading: tangent,
    };
  }, [flight]);

  const lineGeometry = useMemo(() => {
    return new THREE.BufferGeometry().setFromPoints(curvePoints);
  }, [curvePoints]);

  const isCritical = flight.intelligence.riskLevel === 'critical';
  const arcColor = isCritical
    ? '#EF4444'
    : isSelected
    ? '#00E5FF'
    : hovered
    ? '#38BDF8'
    : '#1E40AF';

  const lineObject = useMemo(() => {
    const mat = new THREE.LineBasicMaterial({
      color: arcColor,
      transparent: true,
      opacity: isSelected ? 0.95 : hovered ? 0.8 : 0.45,
    });
    return new THREE.Line(lineGeometry, mat);
  }, [arcColor, lineGeometry, isSelected, hovered]);

  if (!curvePoints.length && flight.dataKind !== 'live_state_vectors') return null;
  return (
    <group>
      {/* Flight Arc Line */}
      <primitive object={lineObject} />

      {/* 3D Aircraft Marker */}
      <mesh
        position={planePos}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(flight);
        }}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHovered(true);
        }}
        onPointerOut={(e) => {
          e.stopPropagation();
          setHovered(false);
        }}
      >
        <sphereGeometry args={[isSelected ? 0.045 : 0.03, 12, 12]} />
        <meshBasicMaterial
          color={isCritical ? '#EF4444' : isSelected ? '#00E5FF' : '#38BDF8'}
        />

        {/* Hover / Selected Label in 3D Space */}
        {(hovered || isSelected) && (
          <Html distanceFactor={10} position={[0, 0.06, 0]}>
            <div className="px-2 py-0.5 rounded bg-slate-950/90 border border-cyan-500/60 text-[10px] font-mono text-cyan-400 whitespace-nowrap shadow-xl pointer-events-none">
              <span className="font-bold">{flight.callsign}</span> • FL
              {flight.telemetry.altitudeFt == null ? 'unknown' : Math.round(flight.telemetry.altitudeFt / 100)}
            </div>
          </Html>
        )}
      </mesh>
    </group>
  );
};

// ── Atmospheric Glow Mesh ──────────────────────────────────

const AtmosphereGlow: React.FC = () => {
  return (
    <mesh scale={[1.12, 1.12, 1.12]}>
      <sphereGeometry args={[GLOBE_RADIUS, 32, 32]} />
      <meshBasicMaterial
        color="#00E5FF"
        transparent
        opacity={0.07}
        side={THREE.BackSide}
        blending={THREE.AdditiveBlending}
      />
    </mesh>
  );
};

// ── Main Earth Sphere ──────────────────────────────────────

const EarthSphere: React.FC<{ autoRotate: boolean }> = ({ autoRotate }) => {
  const earthRef = useRef<THREE.Group>(null);

  useFrame((_, delta) => {
    if (autoRotate && earthRef.current) {
      earthRef.current.rotation.y += delta * 0.03;
    }
  });

  return (
    <group ref={earthRef}>
      {/* Deep Ocean Midnight Base */}
      <mesh>
        <sphereGeometry args={[GLOBE_RADIUS, 48, 48]} />
        <meshStandardMaterial
          color="#080F1E"
          roughness={0.7}
          metalness={0.2}
          emissive="#030814"
        />
      </mesh>

      {/* Lat/Lon Aviation Graticule Wireframe */}
      <mesh>
        <sphereGeometry args={[GLOBE_RADIUS * 1.001, 24, 24]} />
        <meshBasicMaterial
          color="#1E293B"
          wireframe
          transparent
          opacity={0.25}
        />
      </mesh>

      {/* Atmospheric Glow Shell */}
      <AtmosphereGlow />
    </group>
  );
};

// ── 3D Scene Composition ───────────────────────────────────

interface EarthGlobe3DProps {
  flights: FlightTrack[];
  selectedFlight: FlightTrack | null;
  onSelectFlight: (flight: FlightTrack | null) => void;
}

export const EarthGlobe3D: React.FC<EarthGlobe3DProps> = ({
  flights,
  selectedFlight,
  onSelectFlight,
}) => {
  const [autoRotate, setAutoRotate] = useState(true);

  return (
    <div className="relative w-full h-full bg-[#050811] overflow-hidden select-none">
      {/* 3D Canvas */}
      <Canvas
        camera={{ position: [0, 1.5, 4.8], fov: 45 }}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      >
        <color attach="background" args={['#050811']} />
        <ambientLight intensity={0.75} />
        <directionalLight position={[5, 3, 5]} intensity={1.2} />

        {/* Orbit Controls with Damping */}
        <OrbitControls
          enablePan={false}
          minDistance={2.8}
          maxDistance={7.5}
          dampingFactor={0.06}
          rotateSpeed={0.6}
        />

        {/* Earth Base */}
        <EarthSphere autoRotate={autoRotate} />

        {/* Flight Arcs Group */}
        <group>
          {flights.map((flight) => (
            <FlightArc3D
              key={flight.id}
              flight={flight}
              isSelected={selectedFlight?.id === flight.id}
              onSelect={onSelectFlight}
            />
          ))}
        </group>
      </Canvas>

      {/* Globe HUD Overlay Controls */}
      <div className="absolute top-4 left-4 z-10 flex items-center gap-2">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/85 border border-slate-800 backdrop-blur-md text-xs font-mono text-slate-200 shadow-xl">
          <Sparkles className="w-4 h-4 text-cyan-400 animate-spin" />
          <span className="font-bold text-slate-100">3D ORBITAL VIEW</span>
          <span className="text-slate-500">|</span>
          <span className="text-cyan-400">{flights.filter(f => f.dataKind === 'live_state_vectors' || (f.origin.coordinates && f.destination.coordinates)).length}</span>
          <span className="text-slate-400">MAPPED FLIGHTS</span>
        </div>
      </div>

      {/* Orbit Controls (Bottom Left) */}
      <div className="absolute bottom-4 left-4 z-10 flex items-center gap-2">
        <button
          onClick={() => setAutoRotate((prev) => !prev)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono border backdrop-blur-md transition-colors shadow-lg ${
            autoRotate
              ? 'bg-cyan-950/80 border-cyan-500/50 text-cyan-400'
              : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:text-slate-200'
          }`}
        >
          <RotateCw className={`w-3.5 h-3.5 ${autoRotate ? 'animate-spin' : ''}`} />
          <span>{autoRotate ? 'ORBIT ACTIVE' : 'ORBIT PAUSED'}</span>
        </button>

        <span className="text-[11px] font-mono text-slate-500 hidden sm:inline">
          Drag to orbit • Scroll to zoom
        </span>
      </div>
    </div>
  );
};
export default EarthGlobe3D;
