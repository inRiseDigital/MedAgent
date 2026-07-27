"use client";
/*
 * Mic toggle for voice dictation (FR-3.2/3.3). Hidden entirely when the browser
 * has no Web Speech support (progressive enhancement — never a dead button).
 * Delivers each final transcript to `onTranscript`.
 */
import { Mic, MicOff } from "lucide-react";

import { useSpeech } from "@/lib/use-speech";

export function VoiceButton({
  onTranscript,
  lang,
  title = "Dictate",
}: {
  onTranscript: (text: string) => void;
  lang?: string;
  title?: string;
}) {
  const { supported, listening, error, start, stop } = useSpeech({ lang, onFinal: onTranscript });
  if (!supported) return null;
  return (
    <button
      type="button"
      onClick={listening ? stop : start}
      aria-pressed={listening}
      aria-label={listening ? "Stop dictation" : title}
      title={error ?? (listening ? "Listening… click to stop" : title)}
      className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border transition ${
        listening
          ? "animate-pulse border-destructive bg-destructive-surface text-destructive"
          : "border-border text-muted-foreground hover:bg-muted"
      }`}
    >
      {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
    </button>
  );
}
