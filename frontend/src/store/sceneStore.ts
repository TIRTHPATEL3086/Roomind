import { create } from "zustand";

import { useRobotStore } from "./robotStore";
import type { SceneGraph, SceneGraphObject } from "../types";

export const DEFAULT_ROOM_ID = "demo_room";

interface SceneStore {
  graph: SceneGraph | null;
  roomId: string;
  loading: boolean;
  error: string | null;
  hoveredObjectId: string | null;
  selectedObjectId: string | null;

  setGraph: (g: SceneGraph) => void;
  setRoomId: (id: string) => void;
  setLoading: (b: boolean) => void;
  setError: (e: string | null) => void;
  hover: (id: string | null) => void;
  select: (id: string | null) => void;
  objectById: (id: string) => SceneGraphObject | undefined;
}

export const useSceneStore = create<SceneStore>((set, get) => ({
  graph: null,
  roomId: DEFAULT_ROOM_ID,
  loading: false,
  error: null,
  hoveredObjectId: null,
  selectedObjectId: null,

  setGraph: (g) => {
    // Every room has its own dock, and a room swap or a fresh scan moves it.
    // Parking here rather than in a component effect means it happens once,
    // wherever the graph came from — the initial fetch, a room switch, or a
    // scene.updated frame after a reconstruction commits.
    useRobotStore.getState().parkAtDock(g.robot_dock, g.floor_y);
    set({ graph: g, error: null, selectedObjectId: null, hoveredObjectId: null });
  },
  setRoomId: (id) => set({ roomId: id }),
  setLoading: (b) => set({ loading: b }),
  setError: (e) => set({ error: e, loading: false }),
  hover: (id) => set({ hoveredObjectId: id }),
  select: (id) =>
    set((s) => ({ selectedObjectId: s.selectedObjectId === id ? null : id })),
  objectById: (id) => get().graph?.objects.find((o) => o.id === id),
}));
