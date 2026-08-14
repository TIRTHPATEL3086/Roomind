import { useGLTF } from "@react-three/drei";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

import type { FitMode } from "./registry";

/**
 * Fit a downloaded model into a scene-graph box.
 *
 * A model off an asset site is authored at whatever scale and orientation its
 * author felt like. Kenney's furniture kit is internally consistent but not
 * metric — its sofa is 0.98 m long where our scene graph says 1.90 m — so
 * nothing can be dropped in at scale 1 and every model has to be measured and
 * fitted at runtime.
 *
 * Three corrections, in order:
 *
 *  1. AXIS MATCH. The box knows which way the object faces (rotation_y); the
 *     model has its own idea. A TV modelled 0.68 wide x 0.13 deep dropped into
 *     a slot that is 0.08 wide x 1.15 deep would be turned through 90 degrees
 *     and read as a monolith. Comparing footprint aspect ratios in log space
 *     decides whether to add a quarter turn.
 *  2. SCALE. See FitMode.
 *  3. RECENTRE. The scene graph's position is the CENTRE of the box; these
 *     models have their origin at the base. Without the offset every object
 *     floats half its own height above the floor.
 */
export interface Fit {
  scale: [number, number, number];
  offset: [number, number, number];
  yaw: number;
}

export function computeFit(
  box: THREE.Box3,
  dims: [number, number, number],
  mode: FitMode = "stretch",
  yawOffset = 0,
): Fit {
  const size = new THREE.Vector3();
  box.getSize(size);
  const [w, h, d] = dims;

  // Guard against a degenerate axis (a rug is 1 cm tall; a plane is 0).
  const mx = Math.max(size.x, 1e-4);
  const my = Math.max(size.y, 1e-4);
  const mz = Math.max(size.z, 1e-4);

  // 1. Does the model's footprint sit better turned a quarter turn?
  const target = Math.log(Math.max(w, 1e-4) / Math.max(d, 1e-4));
  const asIs = Math.abs(Math.log(mx / mz) - target);
  const turned = Math.abs(Math.log(mz / mx) - target);
  const quarter = turned < asIs;

  // Effective model footprint after the optional quarter turn.
  const fx = quarter ? mz : mx;
  const fz = quarter ? mx : mz;

  let sx: number, sy: number, sz: number;
  if (mode === "contain") {
    // Uniform, largest that still fits inside the box. Keeps the silhouette
    // honest at the cost of not filling the volume.
    const s = Math.min(w / fx, h / my, d / fz);
    sx = sy = sz = s;
  } else {
    sx = w / fx;
    sy = h / my;
    sz = d / fz;
  }

  // Scale is applied in the model's own frame, so swap back if we turned it.
  const scale: [number, number, number] = quarter ? [sz, sy, sx] : [sx, sy, sz];

  // 3. Move the model's scaled bounding-box centre onto the group origin.
  const centre = new THREE.Vector3();
  box.getCenter(centre);
  const local = new THREE.Vector3(
    -centre.x * scale[0],
    -centre.y * scale[1],
    -centre.z * scale[2],
  );
  // The offset is expressed in the parent's frame, so it has to be rotated by
  // the same quarter turn the mesh gets.
  const yaw = (quarter ? Math.PI / 2 : 0) + yawOffset;
  const rotated = local.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw);

  return { scale, offset: [rotated.x, rotated.y, rotated.z], yaw };
}

/**
 * How much of the model's internal light/dark variation to keep, 0..1.
 * A sofa's cushions should still read lighter than its frame.
 */
const TINT_VARIATION = 0.55;

function recolour(root: THREE.Object3D, hex: string): THREE.Material[] {
  const target = { h: 0, s: 0, l: 0 };
  new THREE.Color(hex).getHSL(target);

  const meshes: THREE.Mesh[] = [];
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (m.isMesh && m.material) meshes.push(m);
  });

  // Pass 1: the model's own mean lightness.
  //
  // The object must end up AT the target lightness, carrying the model's
  // variation ABOUT it — not lerped part-way toward it from wherever the
  // asset happened to sit. Lerping absolute lightness fails hardest exactly
  // where it matters: a #111827 television against Kenney's pale plastic came
  // out mid-blue, because half-way between "almost black" and "almost white"
  // is neither.
  const lums: number[] = [];
  for (const mesh of meshes) {
    for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      const own = { h: 0, s: 0, l: 0 };
      (m as THREE.MeshStandardMaterial).color?.getHSL(own);
      lums.push(own.l);
    }
  }
  const mean = lums.length ? lums.reduce((a, b) => a + b, 0) / lums.length : 0.5;

  // Pass 2: re-hue, anchoring lightness on the target.
  const created: THREE.Material[] = [];
  for (const mesh of meshes) {
    const src = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    const next = src.map((m) => {
      // Clone: useGLTF caches one material graph per URL, so writing to the
      // original would recolour every other object using that model — and the
      // change would survive in the cache after this component unmounts.
      const c = m.clone() as THREE.MeshStandardMaterial;
      const own = { h: 0, s: 0, l: 0 };
      c.color?.getHSL(own);
      const l = THREE.MathUtils.clamp(
        target.l + (own.l - mean) * TINT_VARIATION,
        0.02,
        0.97,
      );
      c.color?.setHSL(target.h, target.s, l);
      created.push(c);
      return c;
    });
    mesh.material = Array.isArray(mesh.material) ? next : next[0];
  }

  return created;
}

export function FurnitureModel({
  url,
  dims,
  fit = "stretch",
  yawOffset = 0,
  tint,
}: {
  url: string;
  dims: [number, number, number];
  fit?: FitMode;
  yawOffset?: number;
  /** Scene-graph colour: the fixture's palette, or a scanned object's real
   *  median pixel colour. Omit to keep the model's own materials. */
  tint?: string;
}) {
  const { scene } = useGLTF(url);

  const f = useMemo(() => {
    const box = new THREE.Box3().setFromObject(scene);
    return computeFit(box, dims, fit, yawOffset);
  }, [scene, dims, fit, yawOffset]);

  // Clone the object graph, never render the cached scene directly: useGLTF
  // keeps ONE scene per URL, so two chairs sharing it means the second steals
  // the first's transform and they collapse into a single chair.
  const object = useMemo(() => {
    const root = scene.clone(true);   // shares geometry, which is what we want
    const mats = tint ? recolour(root, tint) : [];
    root.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.isMesh) {
        m.castShadow = true;
        m.receiveShadow = true;
      }
    });
    return { root, mats };
  }, [scene, tint]);

  // Only the materials WE created get disposed. Geometry and the original
  // materials belong to the GLTF cache and are shared with every other
  // instance; disposing those would blank the model everywhere else.
  useEffect(() => () => object.mats.forEach((m) => m.dispose()), [object]);

  return (
    <group position={f.offset} rotation={[0, f.yaw, 0]} scale={f.scale}>
      <primitive object={object.root} />
    </group>
  );
}
