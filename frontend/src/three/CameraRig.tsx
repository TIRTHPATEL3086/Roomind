import { useFrame, useThree } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";

import { useElement } from "../hooks/useElement";
import { gsap, ScrollTrigger, useGSAP } from "../motion/gsap";
import { CAMERA_SCRUB, EASE } from "../motion/motionTokens";
import { motionDisabled } from "../motion/reducedMotion";
import { APP_CAMERA, BEATS } from "./cameraPose";

export { APP_CAMERA, BEATS };

/**
 * Scrubs the camera along the beats as the page scrolls.
 *
 * Three rules here are load-bearing:
 *
 *  1. Tween the POSITION VECTOR and a LOOK-AT TARGET, never `rotation`. Euler
 *     interpolation gimbal-flips mid-flight and looks catastrophic on a
 *     projector.
 *  2. `scrub` is a number, not `true` — the camera needs inertia to read as a
 *     camera rather than a scrollbar.
 *  3. Scrubbed tweens use a LINEAR ease. Anything else fights the user's wheel.
 */
export function CameraRig({ active }: { active: boolean }) {
  const { camera } = useThree();
  const look = useRef(new THREE.Vector3(...APP_CAMERA.look));
  const applied = useRef(false);

  // The element this scrubs against is rendered by a DIFFERENT lazy chunk, and
  // this one is smaller so it loads first. Waiting for the element — and
  // depending on it below — is what stops the rig building a ScrollTrigger
  // against nothing and never trying again.
  const trigger = useElement<HTMLElement>("#landing-cinematic");

  useGSAP(
    () => {
      if (!active || !trigger) return;

      // Reduced motion: no scrub, no flight. Sit at the hero pose so the page
      // still reads as a 3D scene, and let the DOM cross-fade carry the story.
      if (motionDisabled()) {
        const b = BEATS[0];
        camera.position.set(...(b.pos as unknown as [number, number, number]));
        look.current.set(...(b.look as unknown as [number, number, number]));
        applied.current = true;
        return;
      }

      const first = BEATS[0];
      camera.position.set(...(first.pos as unknown as [number, number, number]));
      look.current.set(...(first.look as unknown as [number, number, number]));
      applied.current = true;

      const tl = gsap.timeline({
        defaults: { ease: EASE.linear }, // scrubbed => linear, always
        scrollTrigger: {
          // The resolved ELEMENT, not a selector string: a selector that
          // matches nothing gives a silently dead trigger, whereas this cannot
          // run until useElement has actually found it.
          //
          // Scoped to the CINEMATIC region, not the whole page. The landing
          // continues into long-form content below the beats; triggering on
          // #landing-scroll would spread the six-beat flight across the entire
          // document, so the camera would still be creeping while the reader
          // is three sections into the hardware spec.
          trigger,
          start: "top top",
          end: "bottom bottom",
          scrub: CAMERA_SCRUB,
          invalidateOnRefresh: true,
        },
      });

      BEATS.slice(1).forEach((b) => {
        tl.to(camera.position, { x: b.pos[0], y: b.pos[1], z: b.pos[2] }).to(
          look.current,
          { x: b.look[0], y: b.look[1], z: b.look[2] },
          "<",
        );
      });

      ScrollTrigger.refresh();

      // Same ?probe=1 hook SceneRoot uses. ScrollTrigger lives in the
      // landing-only chunk, so this is the only place it can be exposed from,
      // and a scroll bug is exactly when you need to read start/end/progress.
      if (new URLSearchParams(location.search).has("probe")) {
        (window as unknown as Record<string, unknown>).__rmST = ScrollTrigger;
      }
    },
    { dependencies: [active, trigger], scope: undefined },
  );

  // Applied every frame, outside the tween. Doing lookAt inside an onUpdate
  // means it only runs while the tween is active, and the camera drifts the
  // moment the user stops scrolling.
  useFrame(() => {
    if (active && applied.current) camera.lookAt(look.current);
  });

  return null;
}

/**
 * Snap the camera to the /app pose without a tween.
 *
 * Used when the landing is skipped: there is no scroll position to derive a
 * pose from, so we place the camera exactly where OrbitControls expects it.
 */
export function useSnapToAppCamera() {
  const { camera } = useThree();
  return () => {
    camera.position.set(...(APP_CAMERA.pos as unknown as [number, number, number]));
    camera.lookAt(new THREE.Vector3(...APP_CAMERA.look));
  };
}
