import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import { useRobotStore, type RobotState } from "../store/robotStore";

const DEG = Math.PI / 180;

// ── Proportions (metres) — must match kinematics.py ───────────────────────────
// Redesigned as a cute white humanoid: round head, chunky torso, full legs+feet.
const FOOT_H     = 0.045;
const SHIN_H     = 0.10;
const THIGH_H    = 0.10;
const HIP_Y      = FOOT_H + SHIN_H + THIGH_H;           // ≈ 0.245
const TORSO_H    = 0.18;
const TORSO_Y    = HIP_Y + TORSO_H / 2;                  // ≈ 0.335
const SHOULDER_Y = HIP_Y + TORSO_H - 0.025;              // ≈ 0.405
const SHOULDER_X = 0.115;
const UPPER_ARM  = 0.095;
const FOREARM    = 0.085;
const NECK_Y     = HIP_Y + TORSO_H + 0.015;              // ≈ 0.44
const HEAD_R     = 0.075;
const HEAD_Y     = NECK_Y + HEAD_R + 0.01;               // ≈ 0.525
const LEG_X      = 0.06;

// ── Palette ────────────────────────────────────────────────────────────────────
const WHITE      = "#ECEFF4";
const LIGHT_GREY = "#CBD5E1";
const MID_GREY   = "#94A3B8";
const DARK_PANEL = "#1E293B";
const VISOR_DARK = "#0B1A2E";

const EMOTION_COLOR: Record<string, string> = {
  neutral:  "#22D3EE",   // cyan
  happy:    "#34D399",   // green
  curious:  "#A78BFA",   // violet
  confused: "#F59E0B",   // amber
  alert:    "#EF4444",   // red
};

/** Shortest-path rotation — prevents 350° head spins. */
function shortestAngle(from: number, to: number): number {
  return Math.atan2(Math.sin(to - from), Math.cos(to - from));
}

function WhiteMat({ metalness = 0.22, roughness = 0.28 }: { metalness?: number; roughness?: number }) {
  return <meshStandardMaterial color={WHITE} metalness={metalness} roughness={roughness} />;
}



// ── One arm: shoulder ball → upper arm → elbow → forearm → hand glow ──────────
function Arm({
  side, pitch, roll, elbow, color,
}: {
  side: "l" | "r"; pitch: number; roll: number; elbow: number; color: string;
}) {
  const sign = side === "r" ? 1 : -1;
  return (
    <group position={[sign * SHOULDER_X, SHOULDER_Y, 0]}>
      {/* shoulder ball */}
      <mesh>
        <sphereGeometry args={[0.038, 14, 14]} />
        <meshStandardMaterial color={LIGHT_GREY} metalness={0.3} roughness={0.4} />
      </mesh>
      <group rotation={[0, 0, -sign * roll * DEG]}>
        <group rotation={[-pitch * DEG, 0, 0]}>
          {/* upper arm */}
          <mesh castShadow position={[0, -UPPER_ARM / 2, 0]}>
            <capsuleGeometry args={[0.027, UPPER_ARM - 0.02, 6, 12]} />
            <WhiteMat />
          </mesh>
          {/* elbow ball */}
          <mesh position={[0, -UPPER_ARM, 0]}>
            <sphereGeometry args={[0.023, 12, 12]} />
            <meshStandardMaterial color={MID_GREY} metalness={0.4} roughness={0.45} />
          </mesh>
          <group position={[0, -UPPER_ARM, 0]} rotation={[elbow * DEG, 0, 0]}>
            {/* forearm */}
            <mesh castShadow position={[0, -FOREARM / 2, 0]}>
              <capsuleGeometry args={[0.021, FOREARM - 0.02, 6, 12]} />
              <WhiteMat />
            </mesh>
            {/* fingertip glow — "she is pointing at THAT" */}
            <mesh position={[0, -FOREARM - 0.018, 0]}>
              <sphereGeometry args={[0.020, 14, 14]} />
              <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.4} toneMapped={false} />
            </mesh>
            <pointLight color={color} intensity={0.35} distance={0.5} position={[0, -FOREARM - 0.018, 0]} />
          </group>
        </group>
      </group>
    </group>
  );
}



// ── Main avatar ───────────────────────────────────────────────────────────────
export function RobotAvatar({ robot }: { robot: RobotState }) {
  const root     = useRef<THREE.Group>(null!);
  const head     = useRef<THREE.Group>(null!);
  const waist    = useRef<THREE.Group>(null!);
  const bodyBob  = useRef<THREE.Group>(null!);

  const targetPos = useRef(new THREE.Vector3());
  const targetYaw = useRef(0);
  const idleT     = useRef(0);

  // Smoothed joint values — never trigger a React render.
  // Initialized with REST_JOINTS keys; new sim keys (l_hip, l_knee, body_y, etc.)
  // are seeded lazily on first telemetry receipt so they interpolate from the start.
  const j = useRef<Record<string, number>>({ ...(robot.joints as Record<string, number>) });

  // Track latest robot prop in a ref so useFrame always reads fresh values
  // without being a stale closure — avoids the React/R3F re-subscription gap.
  const robotRef = useRef(robot);
  robotRef.current = robot;

  const color    = EMOTION_COLOR[robot.emotion] ?? robot.accent_color;
  const eyeColor = useMemo(() => new THREE.Color(color), [color]);

  const leftLegHip = useRef<THREE.Group>(null!);
  const leftLegKnee = useRef<THREE.Group>(null!);
  const rightLegHip = useRef<THREE.Group>(null!);
  const rightLegKnee = useRef<THREE.Group>(null!);

  useFrame((_, dt) => {
    const r = robotRef.current;
    // Frame-rate-independent lerp (spec 13.4). Telemetry is 10 Hz, render at 60 — interpolate.
    const k = 1 - Math.exp(-10 * dt);
    idleT.current += dt;

    // Update pose target every frame (no useEffect lag)
    targetPos.current.set(r.pose.x, r.pose.y, r.pose.z);
    targetYaw.current = r.pose.yaw;

    const t = r.joints as Record<string, number>;
    const jCur = j.current;

    // Seed any NEW joint keys arriving from telemetry (e.g. l_hip, l_knee, r_hip,
    // r_knee, body_y) that weren't in the initial REST_JOINTS.
    for (const key of Object.keys(t)) {
      if (!(key in jCur)) {
        jCur[key] = t[key]; // start from the live value, not zero
      }
    }

    // Smooth all known joints toward their telemetry targets.
    for (const key of Object.keys(jCur)) {
      if (t[key] !== undefined) {
        jCur[key] += (t[key] - jCur[key]) * k;
      }
    }

    const baseElevation = jCur.body_y ?? 0;
    const elevatedPos = targetPos.current.clone();
    elevatedPos.y += baseElevation;

    root.current.position.lerp(elevatedPos, k);
    root.current.rotation.y += shortestAngle(root.current.rotation.y, targetYaw.current) * k;

    // Idle breathing bob
    if (bodyBob.current) {
      bodyBob.current.position.y = Math.sin(idleT.current * 1.4) * 0.005;
    }

    if (head.current) {
      head.current.rotation.y = (jCur.head_pan ?? 0) * DEG;
      head.current.rotation.x = -(jCur.head_tilt ?? 0) * DEG;
    }
    if (waist.current) {
      waist.current.rotation.y = (jCur.waist_yaw ?? 0) * DEG;
    }
    if (leftLegHip.current) {
      leftLegHip.current.rotation.x = -(jCur.l_hip ?? 0) * DEG;
    }
    if (leftLegKnee.current) {
      leftLegKnee.current.rotation.x = (jCur.l_knee ?? 0) * DEG;
    }
    if (rightLegHip.current) {
      rightLegHip.current.rotation.x = -(jCur.r_hip ?? 0) * DEG;
    }
    if (rightLegKnee.current) {
      rightLegKnee.current.rotation.x = (jCur.r_knee ?? 0) * DEG;
    }
  });

  const isEstopped = robot.state === "estop";

  return (
    <group ref={root} name="aria">
      {/* body group — bobs on idle + vertical motions */}
      <group ref={bodyBob}>

        {/* ── LEGS — with dynamic hip and knee articulation */}
        {/* Left leg */}
        <group position={[-LEG_X, HIP_Y, 0]}>
          <group ref={leftLegHip}>
            <mesh>
              <sphereGeometry args={[0.034, 14, 14]} />
              <meshStandardMaterial color={LIGHT_GREY} metalness={0.3} roughness={0.4} />
            </mesh>
            <mesh castShadow position={[0, -THIGH_H / 2, 0]}>
              <capsuleGeometry args={[0.030, THIGH_H - 0.02, 6, 12]} />
              <WhiteMat />
            </mesh>
            <group ref={leftLegKnee} position={[0, -THIGH_H, 0]}>
              <mesh>
                <sphereGeometry args={[0.026, 12, 12]} />
                <meshStandardMaterial color={MID_GREY} metalness={0.4} roughness={0.45} />
              </mesh>
              <mesh castShadow position={[0, -SHIN_H / 2, 0]}>
                <capsuleGeometry args={[0.024, SHIN_H - 0.02, 6, 12]} />
                <WhiteMat />
              </mesh>
              <group position={[0, -SHIN_H, 0]}>
                <mesh castShadow receiveShadow position={[0.012, -FOOT_H / 2, 0]}>
                  <boxGeometry args={[0.078, FOOT_H, 0.055]} />
                  <WhiteMat metalness={0.2} roughness={0.35} />
                </mesh>
                <mesh position={[0.012, -FOOT_H + 0.003, 0]}>
                  <boxGeometry args={[0.080, 0.006, 0.057]} />
                  <meshStandardMaterial color={DARK_PANEL} metalness={0.5} roughness={0.3} />
                </mesh>
              </group>
            </group>
          </group>
        </group>

        {/* Right leg */}
        <group position={[LEG_X, HIP_Y, 0]}>
          <group ref={rightLegHip}>
            <mesh>
              <sphereGeometry args={[0.034, 14, 14]} />
              <meshStandardMaterial color={LIGHT_GREY} metalness={0.3} roughness={0.4} />
            </mesh>
            <mesh castShadow position={[0, -THIGH_H / 2, 0]}>
              <capsuleGeometry args={[0.030, THIGH_H - 0.02, 6, 12]} />
              <WhiteMat />
            </mesh>
            <group ref={rightLegKnee} position={[0, -THIGH_H, 0]}>
              <mesh>
                <sphereGeometry args={[0.026, 12, 12]} />
                <meshStandardMaterial color={MID_GREY} metalness={0.4} roughness={0.45} />
              </mesh>
              <mesh castShadow position={[0, -SHIN_H / 2, 0]}>
                <capsuleGeometry args={[0.024, SHIN_H - 0.02, 6, 12]} />
                <WhiteMat />
              </mesh>
              <group position={[0, -SHIN_H, 0]}>
                <mesh castShadow receiveShadow position={[0.012, -FOOT_H / 2, 0]}>
                  <boxGeometry args={[0.078, FOOT_H, 0.055]} />
                  <WhiteMat metalness={0.2} roughness={0.35} />
                </mesh>
                <mesh position={[0.012, -FOOT_H + 0.003, 0]}>
                  <boxGeometry args={[0.080, 0.006, 0.057]} />
                  <meshStandardMaterial color={DARK_PANEL} metalness={0.5} roughness={0.3} />
                </mesh>
              </group>
            </group>
          </group>
        </group>

        {/* ── WAIST + TORSO + ARMS + HEAD */}
        <group ref={waist}>

          {/* waist connector disc */}
          <mesh castShadow position={[0, HIP_Y, 0]}>
            <cylinderGeometry args={[0.046, 0.056, 0.038, 18]} />
            <meshStandardMaterial color={DARK_PANEL} metalness={0.55} roughness={0.3} />
          </mesh>

          {/* torso — white shell */}
          <mesh castShadow position={[0, TORSO_Y, 0]}>
            <capsuleGeometry args={[0.086, TORSO_H - 0.04, 8, 20]} />
            <WhiteMat metalness={0.2} roughness={0.25} />
          </mesh>

          {/* chest dark panel */}
          <mesh position={[0, TORSO_Y + 0.01, 0.083]}>
            <boxGeometry args={[0.062, 0.062, 0.012]} />
            <meshStandardMaterial color={DARK_PANEL} metalness={0.6} roughness={0.25} />
          </mesh>
          {/* chest emblem glow */}
          <mesh position={[0, TORSO_Y + 0.01, 0.092]}>
            <sphereGeometry args={[0.013, 12, 12]} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2.0} toneMapped={false} />
          </mesh>

          {/* shoulder pads */}
          {([-1, 1] as const).map((sign) => (
            <mesh key={sign} castShadow position={[sign * (SHOULDER_X - 0.01), SHOULDER_Y + 0.02, 0]}>
              <sphereGeometry args={[0.043, 14, 14]} />
              <WhiteMat metalness={0.28} />
            </mesh>
          ))}

          {/* arms */}
          <Arm side="l" pitch={j.current.l_shoulder_pitch} roll={j.current.l_shoulder_roll} elbow={j.current.l_elbow} color={color} />
          <Arm side="r" pitch={j.current.r_shoulder_pitch} roll={j.current.r_shoulder_roll} elbow={j.current.r_elbow} color={color} />

          {/* ── HEAD */}
          <group ref={head} position={[0, HEAD_Y, 0]}>
            {/* neck */}
            <mesh position={[0, -HEAD_R - 0.008, 0]}>
              <cylinderGeometry args={[0.026, 0.032, 0.038, 14]} />
              <meshStandardMaterial color={LIGHT_GREY} metalness={0.35} roughness={0.4} />
            </mesh>

            {/* round head shell */}
            <mesh castShadow>
              <sphereGeometry args={[HEAD_R, 30, 30]} />
              <WhiteMat metalness={0.18} roughness={0.22} />
            </mesh>

            {/* visor recess */}
            <mesh position={[0, 0.004, 0.063]}>
              <boxGeometry args={[0.092, 0.042, 0.024]} />
              <meshStandardMaterial color={VISOR_DARK} metalness={0.1} roughness={0.04} transparent opacity={0.93} />
            </mesh>

            {/* LEFT eye */}
            <mesh position={[-0.027, 0.005, 0.073]}>
              <circleGeometry args={[0.017, 22]} />
              <meshStandardMaterial color={eyeColor} emissive={eyeColor} emissiveIntensity={isEstopped ? 3.5 : 2.2} toneMapped={false} />
            </mesh>
            {/* RIGHT eye */}
            <mesh position={[0.027, 0.005, 0.073]}>
              <circleGeometry args={[0.017, 22]} />
              <meshStandardMaterial color={eyeColor} emissive={eyeColor} emissiveIntensity={isEstopped ? 3.5 : 2.2} toneMapped={false} />
            </mesh>

            {/* ear / headphone caps */}
            {([-1, 1] as const).map((sign) => (
              <group key={sign} position={[sign * HEAD_R * 0.95, 0.02, 0]}>
                <mesh>
                  <cylinderGeometry args={[0.026, 0.026, 0.018, 16]} />
                  <meshStandardMaterial color={DARK_PANEL} metalness={0.6} roughness={0.25} />
                </mesh>
              </group>
            ))}

            {/* eye glow point light */}
            <pointLight color={eyeColor} intensity={isEstopped ? 3 : 1.8} distance={1.2} position={[0, 0.005, 0.1]} />
          </group>
        </group>
      </group>

      {isEstopped && (
        <Html center distanceFactor={6} position={[0, HEAD_Y + 0.15, 0]}>
          <div className="whitespace-nowrap rounded-lg bg-danger px-2 py-1 text-xs font-bold text-white shadow-lg">
            STOPPED
          </div>
        </Html>
      )}

      {!robot.online && (
        <Html center distanceFactor={7} position={[0, HEAD_Y + 0.15, 0]}>
          <div className="whitespace-nowrap rounded-lg bg-black/70 px-2 py-1 text-xs font-semibold text-ink-muted">
            offline
          </div>
        </Html>
      )}
    </group>
  );
}

export function AriaAvatar() {
  const aria = useRobotStore((s) => s.aria);
  return <RobotAvatar robot={aria} />;
}
