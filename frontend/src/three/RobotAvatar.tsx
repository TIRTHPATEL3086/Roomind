import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
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

// ── One leg: hip ball → thigh → knee ball → shin → foot ──────────────────────
function Leg({ side, hipPitch = 0, kneeBend = 0 }: { side: "l" | "r"; hipPitch?: number; kneeBend?: number }) {
  const sign = side === "r" ? 1 : -1;
  return (
    <group position={[sign * LEG_X, HIP_Y, 0]}>
      {/* hip joint pitch */}
      <group rotation={[-hipPitch * DEG, 0, 0]}>
        {/* hip ball */}
        <mesh>
          <sphereGeometry args={[0.034, 14, 14]} />
          <meshStandardMaterial color={LIGHT_GREY} metalness={0.3} roughness={0.4} />
        </mesh>
        {/* thigh */}
        <mesh castShadow position={[0, -THIGH_H / 2, 0]}>
          <capsuleGeometry args={[0.030, THIGH_H - 0.02, 6, 12]} />
          <WhiteMat />
        </mesh>
        {/* knee joint */}
        <group position={[0, -THIGH_H, 0]} rotation={[kneeBend * DEG, 0, 0]}>
          {/* knee ball */}
          <mesh>
            <sphereGeometry args={[0.026, 12, 12]} />
            <meshStandardMaterial color={MID_GREY} metalness={0.4} roughness={0.45} />
          </mesh>
          {/* shin */}
          <mesh castShadow position={[0, -SHIN_H / 2, 0]}>
            <capsuleGeometry args={[0.024, SHIN_H - 0.02, 6, 12]} />
            <WhiteMat />
          </mesh>
          {/* foot */}
          <group position={[0, -SHIN_H, 0]} rotation={[-kneeBend * DEG * 0.5, 0, 0]}>
            <mesh castShadow receiveShadow position={[0.012, -FOOT_H / 2, 0]}>
              <boxGeometry args={[0.078, FOOT_H, 0.055]} />
              <WhiteMat metalness={0.2} roughness={0.35} />
            </mesh>
            {/* sole accent */}
            <mesh position={[0.012, -FOOT_H + 0.003, 0]}>
              <boxGeometry args={[0.080, 0.006, 0.057]} />
              <meshStandardMaterial color={DARK_PANEL} metalness={0.5} roughness={0.3} />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
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

// ── Animated holographic platform ─────────────────────────────────────────────
function Platform({ color }: { color: string }) {
  const ring1 = useRef<THREE.Mesh>(null!);
  const ring2 = useRef<THREE.Mesh>(null!);
  useFrame((_, dt) => {
    ring1.current.rotation.y += dt * 0.9;
    ring2.current.rotation.y -= dt * 0.55;
  });
  return (
    <group position={[0, -0.005, 0]}>
      <mesh receiveShadow>
        <cylinderGeometry args={[0.22, 0.245, 0.018, 42]} />
        <meshStandardMaterial color={DARK_PANEL} metalness={0.7} roughness={0.25} />
      </mesh>
      <mesh position={[0, 0.011, 0]}>
        <torusGeometry args={[0.18, 0.006, 8, 52]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.8} toneMapped={false} />
      </mesh>
      <mesh ref={ring1} position={[0, 0.013, 0]}>
        <torusGeometry args={[0.21, 0.003, 6, 56]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2.2} toneMapped={false} />
      </mesh>
      <mesh ref={ring2} position={[0, 0.014, 0]}>
        <torusGeometry args={[0.216, 0.002, 6, 56]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.5} toneMapped={false} />
      </mesh>
      <pointLight color={color} intensity={1.1} distance={0.8} position={[0, 0.04, 0]} />
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
  const j = useRef({ ...robot.joints });

  useEffect(() => {
    targetPos.current.set(robot.pose.x, robot.pose.y, robot.pose.z);
    targetYaw.current = robot.pose.yaw;
  }, [robot.pose]);

  const color    = EMOTION_COLOR[robot.emotion] ?? robot.accent_color;
  const eyeColor = useMemo(() => new THREE.Color(color), [color]);

  useFrame((_, dt) => {
    // Frame-rate-independent lerp (spec 13.4). Telemetry is 10 Hz, render at 60 — interpolate.
    const k = 1 - Math.exp(-10 * dt);
    idleT.current += dt;

    root.current.position.lerp(targetPos.current, k);
    root.current.rotation.y += shortestAngle(root.current.rotation.y, targetYaw.current) * k;

    // Idle breathing + animated joint elevations
    if (bodyBob.current) {
      const baseElevation = (j.current.body_y ?? 0);
      bodyBob.current.position.y = baseElevation + Math.sin(idleT.current * 1.4) * 0.005;
    }

    const t = robot.joints;
    for (const key of Object.keys(j.current) as (keyof typeof t)[]) {
      j.current[key] += (t[key] - j.current[key]) * k;
    }

    if (head.current) {
      head.current.rotation.y = (j.current.head_pan ?? 0) * DEG;
      head.current.rotation.x = -(j.current.head_tilt ?? 0) * DEG;
    }
    if (waist.current) {
      waist.current.rotation.y = (j.current.waist_yaw ?? 0) * DEG;
    }
  });

  const isEstopped = robot.state === "estop";

  return (
    <group ref={root} name="aria">
      {/* body group — bobs on idle + vertical motions */}
      <group ref={bodyBob}>

        {/* ── LEGS — with dynamic hip and knee articulation */}
        <Leg side="l" hipPitch={j.current.l_hip ?? 0} kneeBend={j.current.l_knee ?? 0} />
        <Leg side="r" hipPitch={j.current.r_hip ?? 0} kneeBend={j.current.r_knee ?? 0} />

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
