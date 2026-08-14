// AUTO-GENERATED FROM contracts/scene_graph.schema.json - DO NOT EDIT BY HAND.
// Regenerate with:  py -3.11 contracts/generate_types.py


export interface SceneGraphBounds {
  min: [number, number, number];
  max: [number, number, number];
}

export interface SceneGraphMesh {
  url?: string;
  format?: "glb" | "gltf";
  draco?: boolean;
  tri_count?: number;
  size_bytes?: number;
}

export interface SceneGraphNavmesh {
  url?: string;
  /** metres per cell, e.g. 0.05 */
  resolution?: number;
  origin?: [number, number];
  width?: number;
  height?: number;
}

export interface SceneGraphObjectAttributesColor {
  /** e.g. red, black, grey. 'unknown' when measured but not nameable. */
  value: string;
  hex?: string;
  confidence: number;
}

export interface SceneGraphRelation {
  /** left/right/front/behind are measured in the ROOM frame of spec 8.1 (facing +Z, right is +X). Egocentric left/right is resolved at query time from ARIA's live pose and is deliberately NOT baked in here. */
  rel: "near" | "far" | "beside" | "next_to" | "left_of" | "right_of" | "in_front_of" | "behind" | "on" | "under";
  to: string;
  /** gap between the two oriented boxes, not between their centres. Zero means they touch. */
  distance_m?: number;
}

export interface SceneGraphObjectAttributes {
  /** canonical semantic category. `label` is the display name and `class` is what the resolver matches on; they are equal unless a detector emitted a compound label. */
  class?: string;
  /** the NN in the id. 'chair number 3' resolves through this. */
  instance_index?: number;
  /** HOW the class was decided. 'size_prior' is a guess from dimensions, not recognition - never present it as one. */
  label_source?: "yolo" | "size_prior" | "fixture" | "generated" | "manual";
  /** confidence in the CLASS specifically, separate from the object-level detection confidence */
  label_confidence?: number;
  detector?: "yolo" | "geometric" | "fusion" | "none";
  /** how many independent views agreed this object exists */
  votes?: number;
  /** below the confidence threshold - the resolver must confirm before navigating to it */
  uncertain?: boolean;
  /** colour NAME derived from the measured pixels. Absent when no colour was measured - never guessed. */
  color?: SceneGraphObjectAttributesColor;
  /** volume relative to the other instances of the SAME class in this room. Absent when the class has only one instance, because 'the large chair' means nothing then. */
  size_class?: "small" | "medium" | "large";
  /** this object's outgoing spatial relations, nearest first */
  relations?: SceneGraphRelation[];
}

export interface SceneGraphObject {
  id: string;
  label: string;
  position: [number, number, number];
  dimensions: [number, number, number];
  rotation_y?: number;
  color?: string;
  confidence?: number;
  is_obstacle?: boolean;
  is_climbable?: boolean;
  /** top Y - a usable flat surface to place things on */
  surface_height?: number;
  source?: "detected" | "generated" | "manual";
  /** per-object .glb - set for source=generated (10B) */
  mesh_url?: string;
  /** thumbnail of the source image, generated objects only */
  origin_image?: string;
  /** how sure we are of the metric size - LOW means ask the user (10B.5) */
  scale_confidence?: number;
  /** Instance-level facts used to tell two objects of the same class apart. Deliberately open: unknown keys are allowed, but every key named here has a fixed meaning. */
  attributes?: SceneGraphObjectAttributes;
}

export interface SceneGraphRoomRelation {
  from: string;
  rel: "near" | "far" | "beside" | "next_to" | "left_of" | "right_of" | "in_front_of" | "behind" | "on" | "under";
  to: string;
  distance_m?: number;
}

export interface SceneGraphWaypoint {
  name: string;
  position: [number, number, number];
}

export interface SceneGraph {
  room_id: string;
  version: "1.0";
  name?: string;
  units: "meters";
  up_axis?: "Y";
  created_at?: string;
  bounds: SceneGraphBounds;
  floor_y: number;
  mesh?: SceneGraphMesh;
  navmesh?: SceneGraphNavmesh;
  robot_dock: [number, number, number];
  objects: SceneGraphObject[];
  /** Whole-room spatial relation layer, derived from geometry (spec 8.1 frame). Deterministic: the resolver filters on this rather than asking a model where things are. */
  relations?: SceneGraphRoomRelation[];
  waypoints?: SceneGraphWaypoint[];
}
