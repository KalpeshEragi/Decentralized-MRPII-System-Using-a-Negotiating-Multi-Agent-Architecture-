"use client";
// Polls the backend (FE-6, API-2): the live snapshot and the timeline (through its cursor, keeping the newest MAX_ITEMS
// items). A new poll starts POLL_MS after the previous one finished, so slow answers never pile up.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, Live, TimelineItem } from "./api";

const POLL_MS = 1500;
const MAX_ITEMS = 1500;

export function useLive() {
  const [live, setLive] = useState<Live | null>(null);
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cursor = useRef<string | null>(null);
  const busy = useRef(false);

  const poll = useCallback(async () => {
    if (busy.current) return;  // one poll at a time: the same timeline page is never read twice
    busy.current = true;
    try {
      const [snapshot, page] = await Promise.all([
        api.get<Live>("/observer/live"),
        api.get<{ items: TimelineItem[]; next: string | null }>(
          `/observer/timeline${cursor.current ? `?after=${encodeURIComponent(cursor.current)}` : ""}`,
        ),
      ]);
      setLive(snapshot);
      if (page.items.length) {
        cursor.current = page.next;
        setItems((old) => [...old, ...page.items].slice(-MAX_ITEMS));
      }
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      await poll();
      if (!stopped) timer = setTimeout(loop, POLL_MS);
    };
    loop();
    return () => { stopped = true; clearTimeout(timer); };
  }, [poll]);

  const reset = useCallback(() => {
    cursor.current = null;
    setItems([]);
  }, []);

  return { live, items, error, refresh: poll, reset };
}
