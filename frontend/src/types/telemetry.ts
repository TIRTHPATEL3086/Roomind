// AUTO-GENERATED FROM contracts/telemetry.schema.json - DO NOT EDIT BY HAND.
// Regenerate with:  py -3.11 contracts/generate_types.py


export interface TelemetryPose {
  x: number;
  y: number;
  z: number;
  yaw: number;
}

export interface TelemetryVel {
  linear?: number;
  angular?: number;
}

export interface TelemetryJoints {
  head_pan?: number;
  head_tilt?: number;
  waist_yaw?: number;
  l_shoulder_pitch?: number;
  l_shoulder_roll?: number;
  l_elbow?: number;
  r_shoulder_pitch?: number;
  r_shoulder_roll?: number;
  r_elbow?: number;
}

export interface TelemetrySensorsImu {
  roll?: number;
  pitch?: number;
  yaw?: number;
  ax?: number;
  ay?: number;
  az?: number;
}

export interface TelemetrySensors {
  ultrasonic_cm?: number[];
  ir?: boolean[];
  imu?: TelemetrySensorsImu;
  encoders?: number[];
}

export interface Telemetry {
  robot_id: string;
  /** unix epoch seconds, float */
  ts: number;
  seq?: number;
  pose: TelemetryPose;
  vel?: TelemetryVel;
  /** current joint angles in degrees (8.3.2). Drives the virtual twin's pose. */
  joints?: TelemetryJoints;
  emotion?: "neutral" | "happy" | "curious" | "confused" | "alert";
  state: "idle" | "driving" | "turning" | "gesturing" | "looking" | "pointing" | "presenting" | "dancing" | "charging" | "error" | "estop";
  battery?: number;
  current_command_id?: string | unknown;
  progress?: number;
  sensors?: TelemetrySensors;
  errors?: string[];
}
