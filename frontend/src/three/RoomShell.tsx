import { useMemo } from "react";
import * as THREE from "three";

import { useSceneStore } from "../store/sceneStore";

/**
 * Floor plus wall outlines derived from the scene graph's bounds.
 *
 * Phase 5 replaces this with the real reconstructed room.glb. Until then this
 * gives the space a floor to cast shadows onto and walls to judge scale
 * against - without it ARIA floats in a void and the room reads as nothing.
 */
export function RoomShell() {
  const graph = useSceneStore((s) => s.graph);

  const geom = useMemo(() => {
    if (!graph) return null;
    const [minX, , minZ] = graph.bounds.min;
    const [maxX, maxY, maxZ] = graph.bounds.max;
    return {
      w: maxX - minX,
      d: maxZ - minZ,
      h: maxY - graph.floor_y,
      cx: (minX + maxX) / 2,
      cz: (minZ + maxZ) / 2,
      minX, maxX, minZ, maxZ,
      y: graph.floor_y,
    };
  }, [graph]);

  if (!geom) return null;
  const { w, d, h, cx, cz, y } = geom;

  const wallOutline: [number, number, number][] = [
    [geom.minX, y, geom.minZ],
    [geom.maxX, y, geom.minZ],
    [geom.maxX, y, geom.maxZ],
    [geom.minX, y, geom.maxZ],
    [geom.minX, y, geom.minZ],
  ];

  return (
    <group>
      <mesh
        receiveShadow
        position={[cx, y, cz]}
        rotation={[-Math.PI / 2, 0, 0]}
      >
        <planeGeometry args={[w, d]} />
        <meshStandardMaterial color="#0F172A" roughness={0.95} metalness={0.05} />
      </mesh>

      {/* floor perimeter */}
      <lineSegments position={[0, 0.002, 0]}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[
              new Float32Array(
                wallOutline.flatMap((p, i, arr) =>
                  i < arr.length - 1 ? [...p, ...arr[i + 1]] : [],
                ),
              ),
              3,
            ]}
          />
        </bufferGeometry>
        <lineBasicMaterial color="#334155" />
      </lineSegments>

      {/* wall volume as a wireframe box - suggests the room without occluding it */}
      <lineSegments position={[cx, y + h / 2, cz]}>
        <edgesGeometry args={[new THREE.BoxGeometry(w, h, d)]} />
        <lineBasicMaterial color="#1E293B" transparent opacity={0.75} />
      </lineSegments>
    </group>
  );
}
