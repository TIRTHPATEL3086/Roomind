import { Html } from "@react-three/drei";
import { Suspense, useEffect, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";

import { useSceneStore } from "../store/sceneStore";
import type { SceneGraphObject } from "../types";
import { FurnitureModel } from "./models/FurnitureModel";
import { modelFor, urlsForLabels } from "./models/registry";

/** Shown while an object's model is still in flight. */
function FallbackBox({
  dims,
  color,
}: {
  dims: [number, number, number];
  color: string;
}) {
  return (
    <mesh>
      <boxGeometry args={dims} />
      <meshStandardMaterial color={color} transparent opacity={0.25} />
    </mesh>
  );
}

/** A ring that pulses on the floor under an object - used for selection and,
 *  in Phase 3, for the citation "wow" moment. */
function RingPulse({ y, color }: { y: number; color: string }) {
  const ref = useRef<THREE.Mesh>(null!);
  useFrame(({ clock }) => {
    const t = (clock.elapsedTime % 1.6) / 1.6;
    const s = 0.6 + t * 0.9;
    ref.current.scale.set(s, s, s);
    (ref.current.material as THREE.MeshBasicMaterial).opacity = 1 - t;
  });
  return (
    <mesh ref={ref} position={[0, y + 0.004, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[0.24, 0.28, 40]} />
      <meshBasicMaterial color={color} transparent opacity={0.8} side={THREE.DoubleSide} />
    </mesh>
  );
}

function ObjectBox({
  obj,
  floorY,
  hovered,
  selected,
  onHover,
  onSelect,
}: {
  obj: SceneGraphObject;
  floorY: number;
  hovered: boolean;
  selected: boolean;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const [x, y, z] = obj.position;
  const [w, h, d] = obj.dimensions;
  const attrs = obj.attributes;
  // A size prior is a measurement, not recognition. Marking it keeps the UI
  // honest about which labels a detector actually stands behind.
  const guessed = attrs?.label_source === "size_prior";
  const generated = obj.source === "generated";
  const accent = generated ? "#A78BFA" : (obj.color ?? "#888888");
  const active = hovered || selected;
  const model = modelFor(obj.label);

  return (
    // Named so the object is findable by id in three.js devtools and in the
    // fit verification — a fitted model is easy to eyeball and impossible to
    // eyeball to the centimetre.
    <group
      name={obj.id}
      userData={{ label: obj.label, dims: obj.dimensions }}
      position={[x, y, z]}
      rotation={[0, obj.rotation_y ?? 0, 0]}
    >
      {/* The hit volume is ALWAYS the scene graph's box, never the model.
          It is what A* avoids and what ARIA points at, so picking has to agree
          with it — and an invisible box is also a far kinder click target than
          the gaps between a bookcase's shelves. */}
      <mesh
        visible={!model}
        castShadow={!model}
        receiveShadow={!model}
        onPointerOver={(e) => {
          e.stopPropagation();
          onHover(obj.id);
        }}
        onPointerOut={() => onHover(null)}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(obj.id);
        }}
      >
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial
          color={obj.color ?? "#888888"}
          transparent
          opacity={active ? 0.55 : 0.3}
          metalness={0.15}
          roughness={0.75}
        />
      </mesh>

      {/* Suspense per object, so one still-loading model never blanks the
          room; the box below shows until its own model arrives. */}
      {model && (
        <Suspense fallback={<FallbackBox dims={[w, h, d]} color={accent} />}>
          <FurnitureModel
            url={model.url}
            dims={[w, h, d]}
            fit={model.fit}
            yawOffset={model.yawOffset}
            // Kenney's kit has its own warm palette, which fights this dark
            // UI. The scene graph already carries a colour per object — the
            // fixture's designed palette, or for a scanned room the object's
            // real median pixel colour — so use that and keep the whole scene
            // coherent with the labels, which are tinted from the same field.
            tint={model.tint === false ? undefined : obj.color}
          />
        </Suspense>
      )}

      {/* With a real model the wireframe is selection feedback, not decoration:
          drawing it permanently around every object buries the furniture in a
          cage. Without a model it IS the object's silhouette, so it stays. */}
      {(!model || active) && (
        <lineSegments>
          <edgesGeometry args={[new THREE.BoxGeometry(w, h, d)]} />
          <lineBasicMaterial
            color={accent}
            transparent
            opacity={active ? 1 : 0.55}
          />
        </lineSegments>
      )}

      {selected && <RingPulse y={floorY - y} color={accent} />}

      <Html
        center
        distanceFactor={8}
        position={[0, h / 2 + 0.11, 0]}
        style={{ pointerEvents: "none" }}
      >
        <div
          className={`flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 font-mono text-[10px] transition-opacity ${
            active ? "bg-black/80 opacity-100" : "bg-black/45 opacity-70"
          }`}
          style={{ color: accent }}
        >
          {generated && <span title="generated from an image">✨</span>}
          {obj.id}
          {active && attrs?.color?.value && (
            // The word the resolver matches "the red chair" against. Showing it
            // on hover is the difference between trusting the answer and taking
            // it on faith: two chairs that look similar on a dark background
            // are unambiguous once you can see one is named "red" and the
            // other "brown".
            <span className="text-ink-muted">{attrs.color.value}</span>
          )}
          {active && attrs?.size_class && (
            <span className="text-ink-muted">{attrs.size_class}</span>
          )}
          {active && obj.confidence != null && (
            <span
              className={guessed ? "text-amber-300" : "text-ink-muted"}
              title={
                guessed
                  ? "class inferred from this object's 3D size, not recognised " +
                    "by a detector"
                  : "recognised by the detector"
              }
            >
              {Math.round(obj.confidence * 100)}%{guessed ? " ~" : ""}
            </span>
          )}
        </div>
      </Html>
    </group>
  );
}

/**
 * `interactive` is false during the landing: pointer events on objects there
 * would fight the scroll (a hover mid-scrub reads as the page snagging) and
 * selecting an object has no meaning before the app UI exists.
 */
export function ObjectLabels({ interactive = true }: { interactive?: boolean }) {
  const graph = useSceneStore((s) => s.graph);
  const hovered = useSceneStore((s) => s.hoveredObjectId);
  const selected = useSceneStore((s) => s.selectedObjectId);
  const hover = useSceneStore((s) => s.hover);
  const select = useSceneStore((s) => s.select);

  // Warm every model this room needs as soon as the graph lands, rather than
  // letting each one start downloading when its object first renders. Objects
  // appear together, so staggered fetches mean furniture popping in one piece
  // at a time while the camera is already flying over it.
  useEffect(() => {
    if (!graph) return;
    for (const url of urlsForLabels(graph.objects.map((o) => o.label))) {
      useGLTF.preload(url);
    }
  }, [graph]);

  if (!graph) return null;

  const noop = () => {};

  return (
    <group>
      {graph.objects.map((o) => (
        <ObjectBox
          key={o.id}
          obj={o}
          floorY={graph.floor_y}
          hovered={interactive && hovered === o.id}
          selected={interactive && selected === o.id}
          onHover={interactive ? hover : noop}
          onSelect={interactive ? select : noop}
        />
      ))}
    </group>
  );
}
