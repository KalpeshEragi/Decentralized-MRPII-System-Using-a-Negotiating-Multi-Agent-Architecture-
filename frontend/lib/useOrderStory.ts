"use client";
// One order's story (GET /observer/orders/{ref}), re-read whenever the timeline grows: new lines may belong to it.

import { useEffect, useState } from "react";
import { api, OrderStory } from "./api";

export function useOrderStory(demandId: string | null, version: number): OrderStory | null {
  const [story, setStory] = useState<OrderStory | null>(null);
  useEffect(() => { setStory(null); }, [demandId]);
  useEffect(() => {
    if (!demandId) return;
    let stale = false;
    api.get<OrderStory>(`/observer/orders/${demandId}`).then((s) => { if (!stale) setStory(s); }).catch(() => {});
    return () => { stale = true; };
  }, [demandId, version]);
  return story;
}
