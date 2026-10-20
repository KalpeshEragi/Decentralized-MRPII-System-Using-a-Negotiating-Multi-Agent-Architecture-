"use client";
// Polls the backend (FE-6, API-2): the live snapshot and the timeline (through its cursor, keeping the newest MAX_ITEMS
// items). A new poll starts POLL_MS after the previous one finished, so slow answers never pile up.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, Live, TimelineItem } from "./api";

const POLL_MS = 1500;
const MAX_ITEMS = 1500;
const FULL_PAGE = 200;  // the observer's page size: a full page means more is waiting, so read again at once

export function useLive() {
  const [live, setLive] = useState<Live | null>(null);
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cursor = useRef<string | null>(null);
  const busy = useRef(false);

  /** One poll; returns true when the timeline page was full (more items are waiting). */
  const poll = useCallback(async (): Promise<boolean> => {
    if (busy.current) return false;  // one poll at a time: the same timeline page is never read twice
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
      return page.items.length >= FULL_PAGE;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      return false;
    } finally {
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      const more = await poll();
      if (!stopped) timer = setTimeout(loop, more ? 50 : POLL_MS);
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
