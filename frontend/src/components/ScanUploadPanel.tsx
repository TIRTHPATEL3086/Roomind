import {
  AlertTriangle,
  ChevronDown,
  FileVideo,
  FolderOpen,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { startScan } from "../api/client";
import { useScanStore } from "../store/scanStore";
import { Panel } from "./ui/Panel";

/**
 * Upload a room capture and turn it into a semantic twin.
 *
 * Two ways in, because a phone capture and a bench test are different jobs:
 *
 *   a VIDEO file   the ordinary path. Drag it on, or pick it.
 *   a SCAN FOLDER  a directory already on the server (frames/, depth/,
 *                  intrinsics.json). This is how a depth-equipped capture
 *                  gets in at all — a browser cannot upload a folder of
 *                  16-bit depth arrays as one file, and the pipeline needs
 *                  the depth to fuse anything.
 *
 * Validation happens HERE as well as on the server. A 600 MB upload that is
 * going to be refused should be refused before it spends four minutes going
 * over the wire, and "unsupported file type" is a much better message than a
 * pipeline that dies twenty seconds into ingest.
 */

const MAX_UPLOAD_MB = 512;
const VIDEO_TYPES = /\.(mp4|mov|m4v|avi|mkv|webm)$/i;

type Quality = "fast" | "medium" | "high";
type Detector = "auto" | "fusion" | "yolo" | "geometric";

export function ScanUploadPanel({ roomId }: { roomId: string }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [scanDir, setScanDir] = useState("");
  const [name, setName] = useState("");
  const [targetRoom, setTargetRoom] = useState(roomId);
  const [quality, setQuality] = useState<Quality>("medium");
  const [detector, setDetector] = useState<Detector>("auto");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const scanActive = useScanStore((s) => s.active);

  const accept = useCallback((f: File) => {
    if (!VIDEO_TYPES.test(f.name)) {
      setError(`${f.name} isn't a video. Use MP4, MOV, M4V, AVI, MKV or WebM.`);
      return;
    }
    if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(
        `${(f.size / 1024 / 1024).toFixed(0)} MB is over the ${MAX_UPLOAD_MB} MB limit. ` +
          `Trim the clip, or point at a scan folder instead.`,
      );
      return;
    }
    setError(null);
    setFile(f);
    setScanDir("");
  }, []);

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) accept(f);
  }

  async function submit() {
    if (!file && !scanDir.trim()) {
      setError("Pick a video, or give the path of a capture folder.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await startScan({
        roomId: targetRoom.trim() || roomId,
        video: file ?? undefined,
        scanDir: scanDir.trim() || undefined,
        name: name.trim() || undefined,
        quality,
        // The server understands "auto"; sending the resolved name would pin
        // a backend that may not be installed on the machine running it.
        detector: detector === "auto" ? undefined : detector,
      });
      useScanStore.getState().start(res.scan_id, targetRoom.trim() || roomId);
      setOpen(false);
      setFile(null);
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: unknown } } }).response
        ?.data?.detail;
      setError(
        typeof msg === "string"
          ? msg
          : ((msg as { message?: string })?.message ?? (e as Error).message),
      );
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={scanActive}
        title="Upload a room capture and rebuild the twin"
        className="rm-glass pointer-events-auto flex items-center gap-1.5 px-2.5 py-1.5
                   text-[11px] text-ink-muted transition hover:text-ink
                   disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Upload size={12} /> scan a room
      </button>
    );
  }

  return (
    <Panel
      title="Scan a room"
      className="pointer-events-auto w-80"
      right={
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-ink-muted transition hover:text-ink"
        >
          <X size={13} />
        </button>
      }
    >
      <div className="space-y-2.5 p-3">
        {/* drop zone */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center gap-1.5 rounded-lg border
                      border-dashed px-3 py-5 text-center transition ${
                        dragging
                          ? "border-aria bg-aria/10"
                          : "border-white/15 bg-black/20 hover:border-white/30"
                      }`}
        >
          {file ? (
            <>
              <FileVideo size={18} className="text-aria" />
              <span className="max-w-full truncate text-[11px] text-ink">
                {file.name}
              </span>
              <span className="font-mono text-[10px] text-ink-muted">
                {(file.size / 1024 / 1024).toFixed(1)} MB
              </span>
            </>
          ) : (
            <>
              <Upload size={18} className="text-ink-muted" />
              <span className="text-[11px] text-ink">
                Drop a room video, or click to pick one
              </span>
              <span className="text-[10px] text-ink-muted">
                MP4 · MOV · MKV · WebM — up to {MAX_UPLOAD_MB} MB
              </span>
            </>
          )}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="video/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) accept(f);
          }}
        />

        {/* server-side capture folder */}
        <label className="block">
          <span className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-ink-muted">
            <FolderOpen size={11} /> or a capture folder on the server
          </span>
          <input
            value={scanDir}
            onChange={(e) => {
              setScanDir(e.target.value);
              if (e.target.value) setFile(null);
            }}
            placeholder="./storage/scans/multi_demo"
            className="w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5
                       font-mono text-[11px] outline-none placeholder:text-ink-muted/50
                       focus:border-aria/60"
          />
          <span className="mt-1 block text-[10px] leading-snug text-ink-muted/80">
            Needs <code>frames/</code>, <code>depth/</code> and{" "}
            <code>intrinsics.json</code>. Without depth the pipeline can't fuse
            a mesh.
          </span>
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className="mb-1 block text-[10px] uppercase tracking-wider text-ink-muted">
              Room id
            </span>
            <input
              value={targetRoom}
              onChange={(e) => setTargetRoom(e.target.value)}
              className="w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5
                         font-mono text-[11px] outline-none focus:border-aria/60"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[10px] uppercase tracking-wider text-ink-muted">
              Name
            </span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Living room"
              className="w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5
                         text-[11px] outline-none placeholder:text-ink-muted/50
                         focus:border-aria/60"
            />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Select
            label="Quality"
            value={quality}
            onChange={(v) => setQuality(v as Quality)}
            options={[
              ["fast", "Fast · 4 cm"],
              ["medium", "Medium · 2 cm"],
              ["high", "High · 1 cm"],
            ]}
          />
          <Select
            label="Detector"
            value={detector}
            onChange={(v) => setDetector(v as Detector)}
            options={[
              ["auto", "Auto"],
              ["fusion", "Fusion · YOLO + 3D"],
              ["yolo", "YOLO only"],
              ["geometric", "Geometry only"],
            ]}
          />
        </div>

        <p className="text-[10px] leading-snug text-ink-muted/80">
          Fusion separates objects in 3D and asks YOLO what each one is. Classes
          COCO doesn't know — lamps, shelves, doors — fall back to a size prior
          and are marked as guessed, not recognised.
        </p>

        {error && (
          <div className="flex gap-1.5 rounded-lg border border-danger/40 bg-danger/10 px-2 py-1.5">
            <AlertTriangle size={12} className="mt-px shrink-0 text-danger" />
            <span className="text-[10px] leading-snug text-danger">{error}</span>
          </div>
        )}

        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || (!file && !scanDir.trim())}
          className="w-full rounded-lg bg-aria/80 py-1.5 text-xs font-semibold text-white
                     transition hover:bg-aria disabled:cursor-not-allowed
                     disabled:opacity-40"
        >
          {busy ? "Uploading…" : "Build the twin"}
        </button>
      </div>
    </Panel>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] uppercase tracking-wider text-ink-muted">
        {label}
      </span>
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full appearance-none rounded-lg border border-white/10 bg-black/30
                     px-2 py-1.5 pr-6 text-[11px] outline-none focus:border-aria/60"
        >
          {options.map(([v, l]) => (
            <option key={v} value={v} className="bg-night text-ink">
              {l}
            </option>
          ))}
        </select>
        <ChevronDown
          size={11}
          className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-ink-muted"
        />
      </div>
    </label>
  );
}
