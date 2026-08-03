"use client";
/*
 * Telehealth room — a real WebRTC video call embedded via Jitsi (iframe, no
 * external script so no CSP/script concerns). Doctor and patient join the same
 * deterministic room and meet live (camera, mic, screen-share, chat all handled
 * by Jitsi). Production hardening: bind this to a JWT-gated, self-hosted room via
 * the telemedicine.py single-use token lifecycle (see docs/PRODUCTION-BLUEPRINT §5).
 */
import { X } from "lucide-react";

const DOMAIN = "meet.jit.si";

export function VideoRoom({ room, displayName, onClose }: { room: string; displayName: string; onClose: () => void }) {
  const hash = [
    "config.prejoinPageEnabled=false",
    "config.disableDeepLinking=true",
    "config.startWithAudioMuted=false",
    `userInfo.displayName=${encodeURIComponent(JSON.stringify(displayName))}`,
  ].join("&");
  const src = `https://${DOMAIN}/${encodeURIComponent(room)}#${hash}`;
  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-black">
      <div className="flex items-center justify-between px-4 py-2 text-white">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-red-500" /> Secure video visit
        </span>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-sm font-semibold text-white hover:bg-white/20"
        >
          <X className="h-4 w-4" /> Leave
        </button>
      </div>
      <iframe
        title="Video visit"
        src={src}
        allow="camera; microphone; fullscreen; display-capture; autoplay; clipboard-write"
        className="w-full flex-1 border-0"
      />
    </div>
  );
}
