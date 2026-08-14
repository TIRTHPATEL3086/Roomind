import { AnimatePresence, motion } from "framer-motion";
import { Check, ImagePlus, Loader2, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { useSceneStore } from "../store/sceneStore";
import { useUIStore } from "../store/uiStore";
import { Panel } from "./ui/Panel";

const ROOM_ID = "demo_room";

const STAGE_LABEL: Record<string, string> = {
  queued: "queued",
  prepare: "reading the image",
  understand: "working out what it is",
  generate: "building the 3D model",
  cleanup: "cleaning up the mesh",
  texture: "baking the texture",
  scale: "sizing it for your room",
  export: "placing it",
  preview: "ready",
};

interface Job {
  job_id: string;
  status: string;
  stage: string;
  progress: number;
  label?: string;
  dimensions?: [number, number, number];
  scale_confidence?: number;
  proxy?: boolean;
  thumb_url?: string;
  error?: string;
}

export function ImaginePanel() {
  const [job, setJob] = useState<Job | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  }, []);

  useEffect(() => stop, [stop]);

  async function upload(file: File) {
    const form = new FormData();
    form.append("image", file);
    form.append("room_id", ROOM_ID);
    form.append("prompt", file.name.replace(/\.[^.]+$/, "").replace(/[-_]/g, " "));

    try {
      const { data } = await api.post<{ job_id: string }>("/imagine", form);
      setJob({ job_id: data.job_id, status: "queued", stage: "queued", progress: 0 });
      poll(data.job_id);
    } catch (e) {
      useUIStore.getState().pushAlert({
        level: "error",
        message: `Imagine failed: ${(e as Error).message}`,
      });
    }
  }

  function poll(jobId: string) {
    stop();
    pollRef.current = setInterval(async () => {
      const { data } = await api.get(`/imagine/${jobId}`);
      const frag = data.fragment ?? {};
      setJob({
        job_id: jobId,
        status: data.status,
        stage: data.stage,
        progress: data.progress ?? 0,
        label: frag.label ?? data.label,
        dimensions: frag.dimensions,
        scale_confidence: frag.scale_confidence,
        proxy: data.metrics?.is_proxy,
        thumb_url: `/api/v1/imagine/${jobId}/thumb`,
        error: data.error,
      });

      if (["committed", "failed"].includes(data.status)) {
        stop();
        if (data.status === "committed") {
          await refreshScene();
          useUIStore.getState().pushAlert({
            level: "info",
            message: `Added ${data.object?.id ?? "object"} to the room`,
          });
          setTimeout(() => setJob(null), 2500);
        }
      }
    }, 350);
  }

  async function refreshScene() {
    const { data } = await api.get(`/rooms/${ROOM_ID}`);
    useSceneStore.getState().setGraph(data);
  }

  async function confirm() {
    if (!job) return;
    await api.post(`/imagine/${job.job_id}/confirm`);
    await refreshScene();
    useUIStore.getState().pushAlert({
      level: "info",
      message: `Added the ${job.label?.replace(/_/g, " ")} to the room`,
    });
    setJob(null);
  }

  async function discard() {
    if (!job) return;
    await api.delete(`/imagine/${job.job_id}`);
    setJob(null);
  }

  // Whole-window drop target — dragging an image anywhere onto the 3D world
  // should work, not just onto a small rectangle.
  useEffect(() => {
    const over = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) {
        e.preventDefault();
        setDragging(true);
      }
    };
    const leave = (e: DragEvent) => {
      if (e.relatedTarget === null) setDragging(false);
    };
    const drop = (e: DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const f = e.dataTransfer?.files?.[0];
      if (f?.type.startsWith("image/")) upload(f);
    };
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, []);

  const busy = job && !["preview", "committed", "failed"].includes(job.status);
  const needsConfirm = job?.status === "preview";

  return (
    <>
      <AnimatePresence>
        {dragging && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-none fixed inset-0 z-50 flex items-center
                       justify-center bg-night/70 backdrop-blur-sm"
          >
            <div className="rounded-2xl border-2 border-dashed border-generated
                            px-8 py-6 text-center">
              <Sparkles size={26} className="mx-auto mb-2 text-generated" />
              <p className="font-display text-sm">Drop an image</p>
              <p className="text-[11px] text-ink-muted">
                ARIA will build it in 3D and put it in your room
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <Panel title="Imagine" className="w-64">
        <div className="px-3 py-2">
          {!job && (
            <>
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg
                           border border-dashed border-generated/50 bg-generated/5
                           py-3 text-xs text-generated transition
                           hover:border-generated hover:bg-generated/10"
              >
                <ImagePlus size={14} /> Drop or choose an image
              </button>
              <p className="mt-1.5 text-[10px] leading-snug text-ink-muted">
                Turns a photo into a real object ARIA can navigate to and point at.
              </p>
            </>
          )}

          {job && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                {job.thumb_url && (
                  <img
                    src={job.thumb_url}
                    alt=""
                    className="h-10 w-10 rounded object-contain"
                    onError={(e) => (e.currentTarget.style.visibility = "hidden")}
                  />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1 text-xs">
                    {busy && <Loader2 size={11} className="animate-spin text-generated" />}
                    <span className="truncate">
                      {job.label?.replace(/_/g, " ") ?? "working…"}
                    </span>
                  </div>
                  <div className="text-[10px] text-ink-muted">
                    {STAGE_LABEL[job.stage] ?? job.stage}
                  </div>
                </div>
              </div>

              <div className="h-1 overflow-hidden rounded-full bg-white/10">
                <motion.div
                  className="h-full bg-generated"
                  animate={{ width: `${Math.round(job.progress * 100)}%` }}
                  transition={{ duration: 0.25 }}
                />
              </div>

              {job.dimensions && (
                <div className="font-mono text-[10px] text-ink-muted">
                  {job.dimensions.map((d) => d.toFixed(2)).join(" × ")} m
                  {job.scale_confidence != null &&
                    ` · ${Math.round(job.scale_confidence * 100)}% sure of size`}
                </div>
              )}

              {job.proxy && (
                <p className="rounded bg-amber-500/10 px-2 py-1 text-[10px] text-amber-300">
                  Stand-in at the right size — no GPU available for a full model.
                </p>
              )}

              {job.status === "failed" && (
                <p className="rounded bg-danger/10 px-2 py-1 text-[10px] text-danger">
                  {job.error ?? "Generation failed."}
                </p>
              )}

              {(needsConfirm || job.status === "failed") && (
                <div className="flex gap-1.5">
                  {needsConfirm && (
                    <button
                      type="button"
                      onClick={confirm}
                      className="flex flex-1 items-center justify-center gap-1 rounded-lg
                                 bg-generated/80 py-1.5 text-xs font-semibold text-white
                                 transition hover:bg-generated"
                    >
                      <Check size={12} /> Place it
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={discard}
                    className="rounded-lg border border-white/10 px-2 py-1.5 text-xs
                               text-ink-muted transition hover:text-ink"
                  >
                    <X size={12} />
                  </button>
                </div>
              )}
            </div>
          )}

          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload(f);
              e.target.value = "";
            }}
          />
        </div>
      </Panel>
    </>
  );
}
