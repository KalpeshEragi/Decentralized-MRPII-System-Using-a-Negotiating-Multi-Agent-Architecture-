"use client";
// The living factory (FE-1, FE-3). Everything shown is a fact from the observer: pallet stacks follow stock on hand,
// lines glow while an order there has started, trucks and forklifts move only when the matching event arrives
// (MaterialReceived, ShipmentDispatched, MaterialIssuedToProduction, FinishedGoodsStored).

import { MapControls } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Group } from "three";
import type { Live, TimelineItem } from "@/lib/api";
import type { Selection } from "@/components/Overlays";
import type { AgentCode } from "@/lib/insight";
import { Town } from "./buildings/Town";
import { Block, Building, COLORS, Forklift, Machine, Pallet, Person, Pin, Tree, Truck } from "./parts";

type V3 = [number, number, number];
type Mover = { id: string; kind: "inbound" | "outbound" | "kit" | "store"; label: string; started: number };

const DURATION: Record<Mover["kind"], number> = { inbound: 9, outbound: 9, kit: 6, store: 6 };
// Paths across the yard (x, z); trucks drive on the road at z = 20.
const PATHS: Record<Mover["kind"], [number, number][]> = {
  inbound: [[-60, 20], [-16, 20], [-16, 9]],
  outbound: [[29, 9], [29, 20], [60, 20]],
  kit: [[-5, 1], [0, 4], [6, 4], [8, -1]],
  store: [[16, 4], [20, 6], [24, 6], [25, 3]],
};
const MOVING_EVENTS: Record<string, Mover["kind"]> = {
  MaterialReceived: "inbound", ShipmentDispatched: "outbound", MaterialIssuedToProduction: "kit",
  FinishedGoodsStored: "store",
};

export function FactoryScene({ live, items, onSelect, involved, onAgent }: {
  live: Live | null; items: TimelineItem[]; onSelect: (s: Selection) => void;
  involved?: Partial<Record<AgentCode, "origin" | "involved">>; onAgent?: (code: AgentCode) => void;
}) {
  const movers = useMovers(items);
  return (
    <Canvas shadows camera={{ position: [0, 95, 0], fov: 45 }} onPointerMissed={() => onSelect(null)}>
      <color attach="background" args={["#e8eef7"]} />
      <hemisphereLight args={["#ffffff", "#c8d3e3", 0.9]} />
      <directionalLight position={[30, 50, 25]} intensity={1.2} castShadow shadow-mapSize={[4096, 4096]}
                        shadow-camera-left={-170} shadow-camera-right={170} shadow-camera-top={170} shadow-camera-bottom={-170}
                        shadow-camera-far={400} />
      <Ground />
      <Site live={live} items={items} onSelect={onSelect} />
      <Town live={live} involved={involved} onAgent={onAgent} />
      {movers.map((m) => <MovingThing key={m.id} mover={m} />)}
      <MapControls target={[0, 0, -95]} maxPolarAngle={Math.PI / 2.3} minDistance={15} maxDistance={300} enableDamping
                   screenSpacePanning={false} />
    </Canvas>
  );
}

/** New moving things for events that happen while the page is open (history, even if it arrives later, never moves). */
function useMovers(items: TimelineItem[]): Mover[] {
  const [movers, setMovers] = useState<Mover[]>([]);
  const seen = useRef(0);
  const openedAt = useRef(Date.now() - 5000);  // a little slack for clock differences
  useEffect(() => {
    if (items.length < seen.current) seen.current = 0;  // the conversation was reset (a new scenario)
    const fresh = items.slice(seen.current).filter((i) => Date.parse(i.time) > openedAt.current);
    seen.current = items.length;
    const now = performance.now() / 1000;
    const added = fresh.filter((i) => i.source === "event" && MOVING_EVENTS[i.type ?? ""])
      .map((i, n) => ({ id: `${i.time}-${n}`, kind: MOVING_EVENTS[i.type!], started: now + n * 1.5,
                        label: String(i.payload?.quantity ?? i.payload?.kits ?? "") }));
    if (added.length) setMovers((old) => [...old.filter((m) => now - m.started < DURATION[m.kind] + 1), ...added]);
  }, [items]);
  return movers;
}

function MovingThing({ mover }: { mover: Mover }) {
  const ref = useRef<Group>(null);
  const path = PATHS[mover.kind];
  useFrame(() => {
    if (!ref.current) return;
    const t = Math.min(1, Math.max(0, (performance.now() / 1000 - mover.started) / DURATION[mover.kind]));
    ref.current.visible = t > 0 && t < 1;
    const segments = path.length - 1;
    const at = t * segments, i = Math.min(segments - 1, Math.floor(at)), f = at - i;
    const [x1, z1] = path[i], [x2, z2] = path[i + 1];
    ref.current.position.set(x1 + (x2 - x1) * f, 0, z1 + (z2 - z1) * f);
    ref.current.rotation.y = Math.atan2(x2 - x1, z2 - z1);
  });
  const truck = mover.kind === "inbound" || mover.kind === "outbound";
  return (
    <group ref={ref} visible={false}>
      {truck
        ? <Truck color={mover.kind === "inbound" ? "#15a37f" : COLORS.truck}
                 label={`${mover.kind === "inbound" ? "Delivery" : "Shipment"} ${mover.label}`} />
        : <Forklift carrying />}
    </group>
  );
}

function Ground() {
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, -55]} receiveShadow><planeGeometry args={[280, 270]} />
        <meshStandardMaterial color={COLORS.ground} /></mesh>
      <Block position={[0, 0.02, 20]} size={[200, 0.04, 7]} color={COLORS.road} />
      {Array.from({ length: 20 }).map((_, i) => (
        <Block key={i} position={[-95 + i * 10, 0.05, 20]} size={[4, 0.02, 0.25]} color={COLORS.roadLine} />
      ))}
      <Block position={[2, 0.03, 8]} size={[70, 0.03, 9]} color={COLORS.apron} />
      {[-40, -34, 40, 46, -20, 12, 34].map((x, i) => <Tree key={i} position={[x, 0, i % 2 ? 27 : -20]} />)}
    </group>
  );
}

/** The latest supplier delay whose new date is still ahead: shown as a red pin over the receiving dock. */
function supplierDelay(items: TimelineItem[], live: Live | null, names: Record<string, string>): string | null {
  const delay = [...items].reverse().find((i) => i.source === "event" && i.type === "SupplierDeliveryDelayed");
  const until = String(delay?.payload?.new_date ?? "");
  if (!delay || !live || until < live.clock.day) return null;
  return `⚠ ${names[String(delay.payload?.item_id)] ?? "Delivery"} late → ${until}`;
}

function Site({ live, items, onSelect }: { live: Live | null; items: TimelineItem[]; onSelect: (s: Selection) => void }) {
  const stock = live?.stock ?? [];
  const finished = stock.filter((s) => s.type === "FINISHED_PRODUCT");
  const materials = stock.filter((s) => s.type !== "FINISHED_PRODUCT");
  const line = (code: string) => live?.lines.find((l) => l.work_center === code);
  const busy = (code: string) => (line(code)?.orders_today ?? []).some((o) => o.status === "STARTED");
  const planned = (code: string) => (line(code)?.orders_today ?? []).length > 0;
  const progress = (code: string) => (line(code)?.orders_today ?? []).filter((o) => o.status === "STARTED")
    .map((o) => `${Number(o.quantity_completed)}/${Number(o.quantity)}`).join(", ");
  const inbound = live?.docks.inbound.filter((d) => d.status !== "RECEIVED").length ?? 0;
  const outbound = live?.docks.outbound.length ?? 0;
  const delay = supplierDelay(items, live, Object.fromEntries(stock.map((s) => [s.item_id, s.sku])));
  const crew = (skill: string) => (live?.workers ?? []).filter((w) => w.primary_skill === skill);

  return (
    <group>
      {/* Materials warehouse (receiving dock in front) */}
      <Building position={[-14, 0, -5]} size={[20, 8, 14]} doors={[-6, -2, 2]} label="Materials warehouse"
                onClick={(e) => { e.stopPropagation(); onSelect({ kind: "zone", id: "MATERIALS" }); }} />
      <DockMarker position={[-16, 0, 4.5]} text={`Receiving${inbound ? ` · ${inbound} expected` : ""}`}
                  onClick={() => onSelect({ kind: "dock", id: "inbound" })} />
      {delay && <Pin position={[-16, 5, 6.5]} tone="red" text={delay} />}
      {/* Production hall: open sides so the lines are visible */}
      <group>
        <Block position={[8, 0.06, -4]} size={[20, 0.12, 14]} color="#f3f6fa" />
        <Block position={[8, 2, -11]} size={[20, 4, 0.3]} color={COLORS.wall} />
        <Block position={[-2, 1, -4]} size={[0.3, 2, 14]} color={COLORS.wall} />
        <Block position={[18, 1, -4]} size={[0.3, 2, 14]} color={COLORS.wall} />
        <Pin position={[8, 6, -4]} text="Production hall" />
        <LineRow code="SMT" z={-7.5} busy={busy("SMT")} planned={planned("SMT")} crew={crew("SMT")} onSelect={onSelect}
                 progress={progress("SMT")} />
        <LineRow code="ASM" z={-0.5} busy={busy("ASM")} planned={planned("ASM")} crew={crew("ASSEMBLY")}
                 progress={progress("ASM")}
                 onSelect={onSelect} />
      </group>
      {/* Finished goods warehouse (shipping dock in front) */}
      <Building position={[29, 0, -5]} size={[12, 7, 14]} doors={[-2, 2]} label="Finished goods"
                onClick={(e) => { e.stopPropagation(); onSelect({ kind: "zone", id: "FINISHED_GOODS" }); }} />
      <DockMarker position={[29, 0, 4.5]} text={`Shipping${outbound ? ` · ${outbound} due` : ""}`}
                  onClick={() => onSelect({ kind: "dock", id: "outbound" })} />
      {/* Stock yards: one stack per item, sized by stock on hand */}
      <StockYard items={materials} origin={[-36, -12]} perPallet={100} onSelect={onSelect} />
      <StockYard items={finished} origin={[38, -10]} perPallet={20} color={COLORS.blueBox} onSelect={onSelect} />
      {/* Parked forklifts */}
      <group position={[-3, 0, 7]}><Forklift /></group>
      <group position={[22, 0, 7]} rotation={[0, Math.PI, 0]}><Forklift /></group>
    </group>
  );
}

function LineRow({ code, z, busy, planned, crew, onSelect, progress }: {
  code: string; z: number; busy: boolean; planned: boolean; crew: Live["workers"]; onSelect: (s: Selection) => void;
  progress?: string;  // "25/60" while batches come off the line (SIM-2)
}) {
  const select = () => onSelect({ kind: "line", id: code });
  return (
    <group>
      {[2, 8, 14].map((x) => (
        <Machine key={x} position={[x, 0, z]} busy={busy} onClick={(e) => { e.stopPropagation(); select(); }} />
      ))}
      {/* The line's workers (HR's records); an absent worker is a faded red figure with a red pin */}
      {crew.map((w, i) => {
        const x = 3.5 + i * 3.5;
        return (
          <group key={w.code}>
            <Person position={[x, 0, z + 1.8]} working={busy && !w.absent} absent={w.absent} />
            {w.absent && <Pin position={[x, 2.4, z + 1.8]} small tone="red" text={`${w.name} absent`} />}
          </group>
        );
      })}
      <Pin position={[-0.5, 3.4, z]} small tone={busy ? "green" : planned ? "blue" : "amber"}
           text={`${code === "SMT" ? "SMT line" : "Assembly"} · ${busy ? `running${progress ? ` ${progress}` : ""}`
             : planned ? "planned today" : "idle"}`} />
    </group>
  );
}

function StockYard({ items, origin, perPallet, color, onSelect }: {
  items: Live["stock"]; origin: [number, number]; perPallet: number; color?: string; onSelect: (s: Selection) => void;
}) {
  return (
    <group>
      {items.map((item, row) => {
        const pallets = Math.min(8, Math.ceil(Number(item.on_hand) / perPallet));
        const base: V3 = [origin[0], 0, origin[1] + row * 4.2];
        return (
          <group key={item.item_id} onClick={(e) => { e.stopPropagation(); onSelect({ kind: "item", id: item.item_id }); }}>
            <Block position={[base[0] + 3, 0.04, base[2]]} size={[8.6, 0.06, 3.4]} color="#e1e8f2" />
            {Array.from({ length: pallets }).map((_, i) => (
              <Pallet key={i} position={[base[0] + (i % 4) * 1.8, (Math.floor(i / 4)) * 1.25, base[2]]} boxColor={color} />
            ))}
            <Pin position={[base[0] + 3, 3.4, base[2]]} small tone={Number(item.on_hand) > 0 ? "blue" : "red"}
                 text={`${item.sku} · ${Number(item.on_hand).toLocaleString()}`} />
          </group>
        );
      })}
    </group>
  );
}

function DockMarker({ position, text, onClick }: { position: V3; text: string; onClick: () => void }) {
  const stripes = useMemo(() => [-3, -1, 1, 3], []);
  return (
    <group position={position} onClick={(e) => { e.stopPropagation(); onClick(); }}>
      {stripes.map((x) => <Block key={x} position={[x, 0.06, 2]} size={[0.15, 0.04, 4]} color="#f2c94c" />)}
      <Pin position={[0, 2.2, 2]} small text={text} />
    </group>
  );
}
