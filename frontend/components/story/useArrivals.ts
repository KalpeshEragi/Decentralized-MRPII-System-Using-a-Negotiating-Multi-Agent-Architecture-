"use client";
// Which timeline lines arrived in the last few seconds (for the one-shot animations). Lines already there when the
// view opens count as old, so opening a story never replays everything at once.

import { useEffect, useRef, useState } from "react";
import type { TimelineItem } from "@/lib/api";

const SHOW_MS = 2500;
export type Arrived = { key: string; item: TimelineItem };

export function useArrivals(items: TimelineItem[]): Arrived[] {
  const seen = useRef<Map<string, number> | null>(null);
  const [now, setNow] = useState(() => Date.now());

  if (seen.current === null) {
    seen.current = new Map(items.map((item) => [keyOf(item), 0]));
  }
  for (const item of items) {
    const key = keyOf(item);
    if (!seen.current.has(key)) seen.current.set(key, Date.now());
  }

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 400);
    return () => clearInterval(timer);
  }, []);

  return items.filter((item) => now - (seen.current!.get(keyOf(item)) ?? 0) < SHOW_MS)
    .map((item) => ({ key: keyOf(item), item }));
}

function keyOf(item: TimelineItem): string {
  return `${item.time}|${item.source}|${item.type}|${item.session_id ?? item.from ?? ""}|${item.publisher ?? ""}`;
}
