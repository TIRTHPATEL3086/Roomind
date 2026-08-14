import { Environment, Grid, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { Suspense, lazy, useEffect } from "react";
import * as THREE from "three";

import { useSceneStore } from "../store/sceneStore";
import { APP_CAMERA } from "./cameraPose";
import { AriaAvatar } from "./RobotAvatar";
import { ObjectLabels } from "./ObjectLabels";
import { PathLine } from "./PathLine";
import { RoomShell } from "./RoomShell";

/**
 * The camera rig is lazy because it is the only thing in the persistent Canvas
 * that imports GSAP. Statically importing it pulled the whole animation library
 * into the main bundle (+54 kB gzip) on a route that never animates the camera.
 *
 * APP_CAMERA lives in its own module for the same reason: SceneRoot needs the
 * pose constant, and importing it from CameraRig would drag GSAP back in.
 */
const CameraRig = lazy(() =>
  import("./CameraRig").then((m) => ({ default: m.CameraRig })),
);

/**
 * Exposes the live scene on `window.__rm` when the URL carries `?probe=1`.
 *
 * Gated behind a flag and inert otherwise, in the same spirit as `?nomotion=1`.
 * Without it there is no supported way to measure what the renderer actually
 * produced: R3F keeps its state on an internal handle that moves between
 * versions, and "the sofa looks about right" is not a measurement. The fit
 * check in scripts reads draw calls and per-object world bounds through this.
 */
function SceneProbe() {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  const camera = useThree((s) => s.camera);
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__rm = { gl, scene, camera, THREE };
    return () => {
      delete (window as unknown as Record<string, unknown>).__rm;
    };
  }, [gl, scene, camera]);
  return null;
}

function Lighting() {
  return (
    <>
      <ambientLight intensity={0.55} />
      <directionalLight
        position={[5, 8, 3]}
        intensity={1.1}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-6}
        shadow-camera-right={6}
        shadow-camera-top={6}
        shadow-camera-bottom={-6}
      />
      <Suspense fallback={null}>
        <Environment preset="apartment" />
      </Suspense>
    </>
  );
}

function Dock() {
  const graph = useSceneStore((s) => s.graph);
  if (!graph) return null;
  const [x, , z] = graph.robot_dock;
  return (
    <mesh position={[x, graph.floor_y + 0.006, z]} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[0.16, 0.2, 32]} />
      <meshBasicMaterial color="#22D3EE" transparent opacity={0.5} />
    </mesh>
  );
}

/**
 * The single <Canvas> for the whole application.
 *
 * It is mounted ONCE, above the router, and never unmounts. That is what makes
 * the landing -> /app hand-off seamless: the route change swaps DOM overlays
 * and hands camera control from the GSAP rig to OrbitControls, but the WebGL
 * context, the scene graph, and every GPU resource stay exactly as they were.
 * Remounting the Canvas here would cause a white flash and a full re-upload of
 * every buffer (spec 13.11).
 *
 * The landing deliberately showcases THE REAL ROOM rather than a separate
 * diorama asset. That is not a shortcut: it removes the entire 400 KB diorama
 * from the page budget, guarantees the hand-off matches because it is literally
 * the same scene, and keeps every mesh procedurally generated and original
 * (see public/CREDITS.md).
 */
export function SceneRoot({ landing }: { landing: boolean }) {
  const graph = useSceneStore((s) => s.graph);
  const floorY = graph?.floor_y ?? 0;

  return (
    <Canvas
      shadows
      camera={{
        position: [...APP_CAMERA.pos],
        fov: 50,
        near: 0.05,
        far: 100,
      }}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      dpr={[1, 2]}
      onPointerMissed={() => useSceneStore.getState().select(null)}
    >
      {new URLSearchParams(location.search).has("probe") && <SceneProbe />}

      <color attach="background" args={["#0B1020"]} />
      <fog attach="fog" args={["#0B1020", 12, 30]} />

      <Lighting />

      <Grid
        args={[20, 20]}
        cellColor="#1F2937"
        sectionColor="#374151"
        position={[0, floorY + 0.001, 0]}
        fadeDistance={22}
        infiniteGrid
      />

      <RoomShell />
      <Dock />
      <ObjectLabels interactive={!landing} />
      <PathLine />
      <AriaAvatar />

      {/* Only mounted on the landing route, so /app never fetches the GSAP chunk. */}
      {landing && (
        <Suspense fallback={null}>
          <CameraRig active />
        </Suspense>
      )}

      {/* Camera ownership is exclusive: the GSAP rig drives it during the
          landing, OrbitControls takes over in /app. Both enabled at once means
          they fight every frame. */}
      <OrbitControls
        makeDefault
        enabled={!landing}
        enableDamping
        dampingFactor={0.08}
        minDistance={1}
        maxDistance={20}
        maxPolarAngle={Math.PI / 2.05}
        target={[...APP_CAMERA.look]}
      />
    </Canvas>
  );
}
