import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";

import { listRooms } from "../api/client";
import { useSceneStore } from "../store/sceneStore";

interface RoomRow {
  id: string;
  name: string;
  object_count: number;
}

/**
 * Pick which room ARIA is standing in.
 *
 * It exists because instance resolution cannot be shown in a room with one of
 * everything. The shipped `multi_demo` room holds three chairs, two tables and
 * two TVs, so "the red chair" and "the TV near the table" have something to
 * choose between — and it is reachable in one click rather than behind a
 * 27-second rescan.
 *
 * Hidden entirely when there is only one room, since a chooser with one option
 * is just clutter.
 */
export function RoomSwitcher() {
  const roomId = useSceneStore((s) => s.roomId);
  const setRoomId = useSceneStore((s) => s.setRoomId);
  const [rooms, setRooms] = useState<RoomRow[]>([]);

  useEffect(() => {
    listRooms()
      .then(setRooms)
      .catch(() => setRooms([]));
    // Re-listed on room change so a room created by a fresh scan appears
    // without a page reload.
  }, [roomId]);

  if (rooms.length < 2) return null;

  return (
    <div className="relative">
      <select
        value={roomId}
        onChange={(e) => setRoomId(e.target.value)}
        title="Switch room"
        className="appearance-none rounded-md border border-white/10 bg-black/30 py-1
                   pl-2 pr-6 text-[11px] text-ink outline-none transition
                   hover:border-white/25 focus:border-aria/60"
      >
        {rooms.map((r) => (
          <option key={r.id} value={r.id} className="bg-night text-ink">
            {r.name} · {r.object_count}
          </option>
        ))}
      </select>
      <ChevronDown
        size={11}
        className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-ink-muted"
      />
    </div>
  );
}
