// AUTO-GENERATED FROM contracts/command.schema.json - DO NOT EDIT BY HAND.
// Regenerate with:  py -3.11 contracts/generate_types.py


export interface Command {
  id?: string;
  action: "navigate" | "come_here" | "stop" | "follow_me" | "dock" | "turn" | "set_speed" | "look_at" | "point_at" | "wave" | "nod" | "shake_head" | "gesture" | "express" | "dance" | "scan_area" | "remember_spot" | "locate" | "photo" | "report_battery" | "present" | "imagine";
  /** object id or waypoint name */
  target?: string;
  params?: Record<string, unknown>;
  robot_id?: "aria";
  priority?: number;
  /** monotonic per robot */
  seq?: number;
  issued_at?: string;
}
