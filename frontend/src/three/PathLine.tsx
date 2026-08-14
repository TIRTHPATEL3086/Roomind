import { Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import { useRobotStore } from "../store/robotStore";
import { useSceneStore } from "../store/sceneStore";

/** The planned route, drawn on the floor, with a dot travelling along it.
 *  Seeing the plan before the robot moves is what makes the A* believable. */
export function PathLine() {
  const path = useRobotStore((s) => s.aria.path);
  const accent = useRobotStore((s) => s.aria.accent_color);
  const floorY = useSceneStore((s) => s.graph?.floor_y ?? 0);
  const dot = useRef<THREE.Mesh>(null!);

  const points = useMemo<[number, number, number][]>(
    () => (path ?? []).map(([x, z]) => [x, floorY + 0.02, z]),
    [path, floorY],
  );

  const curve = useMemo(
    () =>
      points.length > 1
        ? new THREE.CatmullRomCurve3(points.map((p) => new THREE.Vector3(...p)))
        : null,
    [points],
  );

  useFrame(({ clock }) => {
    if (!curve || !dot.current) return;
    const t = (clock.elapsedTime * 0.35) % 1;
    dot.current.position.copy(curve.getPointAt(t));
  });

  if (points.length < 2) return null;

  return (
    <group>
      <Line points={points} color={accent} lineWidth={3} transparent opacity={0.9} />
      <Line
        points={points}
        color={accent}
        lineWidth={9}
        transparent
        opacity={0.15}
      />
      {/* goal marker */}
      <mesh position={points[points.length - 1]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.07, 0.1, 24]} />
        <meshBasicMaterial color={accent} side={THREE.DoubleSide} />
      </mesh>
      <mesh ref={dot}>
        <sphereGeometry args={[0.028, 12, 12]} />
        <meshBasicMaterial color={accent} toneMapped={false} />
      </mesh>
    </group>
  );
}
