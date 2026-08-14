import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { useRobotStore, type RobotState } from "../store/robotStore";

const DEG = Math.PI / 180;

// ARIA's proportions, metres (spec 1.3). These must match kinematics.py, or the
// twin's arm points somewhere the real arm doesn't.
const BASE_R = 0.14;
const BASE_H = 0.10;
const TORSO_H = 0.20;
const TORSO_Y = BASE_H + TORSO_H / 2;
const SHOULDER_Y = 0.24;
const SHOULDER_X = 0.08;
const HEAD_Y = 0.30;
const UPPER_ARM = 0.11;
const FOREARM = 0.10;

const EMOTION_COLOR: Record<string, string> = {
  neutral: "#3B82F6",
  happy: "#22D3EE",
  curious: "#A78BFA",
  confused: "#F59E0B",
  alert: "#EF4444",
};

/** Smallest signed rotation - never the long way round. Without this the head
 *  spins 350 degrees whenever yaw crosses the +/-pi wrap. */
function shortestAngle(from: number, to: number): number {
  return Math.atan2(Math.sin(to - from), Math.cos(to - from));
}

/** One arm: shoulder pitch/roll drive a group, elbow bends the forearm. */
function Arm({
  side,
  pitch,
  roll,
  elbow,
  color,
}: {
  side: "l" | "r";
  pitch: number;
  roll: number;
  elbow: number;
  color: string;
}) {
  const sign = side === "r" ? 1 : -1;
  return (
    <group position={[sign * SHOULDER_X, SHOULDER_Y, 0]}>
      {/* roll abducts outward, pitch swings forward/up */}
      <group rotation={[0, 0, -sign * roll * DEG]}>
        <group rotation={[-pitch * DEG, 0, 0]}>
          <mesh castShadow position={[0, -UPPER_ARM / 2, 0]}>
            <capsuleGeometry args={[0.022, UPPER_ARM, 4, 8]} />
            <meshStandardMaterial color="#94A3B8" metalness={0.4} roughness={0.5} />
          </mesh>
          <group position={[0, -UPPER_ARM, 0]} rotation={[elbow * DEG, 0, 0]}>
            <mesh castShadow position={[0, -FOREARM / 2, 0]}>
              <capsuleGeometry args={[0.019, FOREARM, 4, 8]} />
              <meshStandardMaterial color="#CBD5E1" metalness={0.4} roughness={0.5} />
            </mesh>
            {/* fingertip marker - makes "she is pointing at THAT" unambiguous */}
            <mesh position={[0, -FOREARM - 0.015, 0]}>
              <sphereGeometry args={[0.016, 12, 12]} />
              <meshStandardMaterial
                color={color}
                emissive={color}
                emissiveIntensity={0.8}
              />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
}

export function RobotAvatar({ robot }: { robot: RobotState }) {
  const root = useRef<THREE.Group>(null!);
  const head = useRef<THREE.Group>(null!);
  const waist = useRef<THREE.Group>(null!);

  const targetPos = useRef(new THREE.Vector3());
  const targetYaw = useRef(0);

  // Smoothed joint values live in a ref, not state: they update every frame and
  // must never trigger a React render.
  const j = useRef({ ...robot.joints });

  useEffect(() => {
    targetPos.current.set(robot.pose.x, robot.pose.y, robot.pose.z);
    targetYaw.current = robot.pose.yaw;
  }, [robot.pose]);

  const color = EMOTION_COLOR[robot.emotion] ?? robot.accent_color;
  const eyeColor = useMemo(() => new THREE.Color(color), [color]);

  useFrame((_, dt) => {
    // Frame-rate-independent lerp (spec 13.4). Telemetry is 10 Hz, we render at
    // 60 - interpolate, never snap. A snapping avatar reads as fake.
    const k = 1 - Math.exp(-10 * dt);

    root.current.position.lerp(targetPos.current, k);
    root.current.rotation.y +=
      shortestAngle(root.current.rotation.y, targetYaw.current) * k;

    // The joints get the SAME treatment as the base - this is what makes the
    // twin read as one machine rather than a sliding box with twitching limbs.
    const t = robot.joints;
    for (const key of Object.keys(j.current) as (keyof typeof t)[]) {
      j.current[key] += (t[key] - j.current[key]) * k;
    }

    if (head.current) {
      head.current.rotation.y = j.current.head_pan * DEG;
      head.current.rotation.x = -j.current.head_tilt * DEG;
    }
    if (waist.current) {
      waist.current.rotation.y = j.current.waist_yaw * DEG;
    }
  });

  const isEstopped = robot.state === "estop";

  return (
    <group ref={root} name="aria">
      {/* base */}
      <mesh castShadow receiveShadow position={[0, BASE_H / 2, 0]}>
        <cylinderGeometry args={[BASE_R, BASE_R * 1.05, BASE_H, 24]} />
        <meshStandardMaterial color="#1F2937" metalness={0.5} roughness={0.45} />
      </mesh>

      <group ref={waist}>
        {/* torso */}
        <mesh castShadow position={[0, TORSO_Y, 0]}>
          <capsuleGeometry args={[0.075, TORSO_H - 0.03, 6, 16]} />
          <meshStandardMaterial
            color={robot.accent_color}
            metalness={0.35}
            roughness={0.4}
            emissive={robot.accent_color}
            emissiveIntensity={0.12}
          />
        </mesh>

        <Arm
          side="l"
          pitch={j.current.l_shoulder_pitch}
          roll={j.current.l_shoulder_roll}
          elbow={j.current.l_elbow}
          color={color}
        />
        <Arm
          side="r"
          pitch={j.current.r_shoulder_pitch}
          roll={j.current.r_shoulder_roll}
          elbow={j.current.r_elbow}
          color={color}
        />

        {/* head - 2 DoF, the single most important thing on the robot */}
        <group ref={head} position={[0, HEAD_Y, 0]}>
          <mesh castShadow>
            <boxGeometry args={[0.105, 0.085, 0.09]} />
            <meshStandardMaterial color="#E5E7EB" metalness={0.3} roughness={0.35} />
          </mesh>
          {/* the eye ring - highest personality-per-polygon in the build */}
          <mesh position={[0, 0.005, 0.047]} rotation={[0, 0, 0]}>
            <torusGeometry args={[0.028, 0.007, 10, 28]} />
            <meshStandardMaterial
              color={eyeColor}
              emissive={eyeColor}
              emissiveIntensity={isEstopped ? 2.5 : 1.4}
              toneMapped={false}
            />
          </mesh>
          <pointLight
            color={eyeColor}
            intensity={isEstopped ? 2.5 : 1.1}
            distance={1.1}
            position={[0, 0, 0.1]}
          />
        </group>
      </group>

      {isEstopped && (
        <Html center distanceFactor={6} position={[0, 0.62, 0]}>
          <div className="whitespace-nowrap rounded-lg bg-danger px-2 py-1 text-xs font-bold text-white shadow-lg">
            STOPPED
          </div>
        </Html>
      )}

      {!robot.online && (
        <Html center distanceFactor={7} position={[0, 0.62, 0]}>
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
