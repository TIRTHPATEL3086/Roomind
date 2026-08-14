/**
 * Camera poses, kept in a GSAP-free module.
 *
 * SceneRoot needs APP_CAMERA to construct the Canvas, and the landing beats
 * need BEATS. If these lived in CameraRig.tsx, importing the constant would
 * drag the whole GSAP bundle into /app — a route that never animates the
 * camera. Constants here, behaviour there.
 */

/**
 * The camera pose the /app dashboard starts at.
 *
 * BEATS[5] MUST equal this exactly. If the last landing beat and the app's
 * initial camera differ by even a little, the hand-off visibly snaps — the one
 * thing that ruins an otherwise seamless transition (spec 13.10).
 */
export const APP_CAMERA = {
  pos: [4, 3.2, 4] as const,
  look: [0, 0.8, 0] as const,
};

/** One pose per landing beat, in world space (spec 13.10). */
export const BEATS = [
  { pos: [6.0, 4.6, 6.0], look: [0, 0.8, 0] }, // S0 hero orbit, wide and high
  { pos: [1.2, 1.5, 2.4], look: [0, 1.0, 0] }, // S1 scan sweep, eye level
  { pos: [4.5, 3.4, -3.2], look: [0, 0.9, 0] }, // S2 understand, pulled back
  { pos: [1.0, 1.2, 1.6], look: [0, 1.1, 0] }, // S3 companion, pushed in
  { pos: [3.2, 1.0, 3.4], look: [0, 0.2, 0] }, // S4 robot, low and tracking
  { pos: [...APP_CAMERA.pos], look: [...APP_CAMERA.look] }, // S5 == /app
] as const;
