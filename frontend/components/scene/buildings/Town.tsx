"use client";
// The agent town: Planning in the centre, the other five agents' buildings around it, all facing the centre,
// with a ring of roads between them and an avenue south to the factory site.
//
//        Inventory     Purchasing     Warehouse        (north row, z = -140)
//   ════════════════ north road ═════════════════      (z = -112)
//        Sales    ║    Planning    ║    HR             (middle row, z = -85)
//   ════════════════ south road ═════════════════      (z = -62)
//                       ║ avenue to the factory

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Mesh } from "three";
import type { Live } from "@/lib/api";
import type { AgentCode } from "@/lib/insight";
import { Block, COLORS, Pin, Tree } from "../parts";
import { AgentOffice } from "./AgentOffice";
import { InventoryWarehouse } from "./InventoryWarehouse";
import { SalesOffice } from "./SalesOffice";
import { WarehouseHall } from "./WarehouseHall";

const ROW_N = -140, ROW_M = -85, ROAD_N = -112, ROAD_S = -62, ROAD_W = -34, ROAD_E = 34;
const ROAD = 7;

// Where each agent's building stands (centre of its footprint) and how big its highlight ring is.
const SPOTS: Record<AgentCode, { at: [number, number]; r: number }> = {
  PLANNING: { at: [0, ROW_M], r: 15 }, SALES: { at: [-58, ROW_M], r: 13 }, HR: { at: [58, ROW_M], r: 15 },
  INVENTORY: { at: [-62, ROW_N], r: 19 }, PURCHASING: { at: [2, ROW_N], r: 17 }, WAREHOUSE: { at: [62, ROW_N - 4], r: 22 },
};

export function Town({ live, involved = {}, onAgent }: {
  live: Live | null; involved?: Partial<Record<AgentCode, "origin" | "involved">>; onAgent?: (code: AgentCode) => void;
}) {
  const click = (code: AgentCode) => (e: { stopPropagation: () => void }) => { e.stopPropagation(); onAgent?.(code); };
  const stock = live?.stock ?? [];
  const inbound = live?.docks.inbound.filter((d) => d.status !== "RECEIVED").length ?? 0;
  const outbound = live?.docks.outbound.length ?? 0;
  return (
    <group>
      <Roads />
      {(Object.entries(involved) as [AgentCode, "origin" | "involved"][]).map(([code, mark]) => (
        <Beacon key={code} at={SPOTS[code].at} r={SPOTS[code].r} origin={mark === "origin"} />
      ))}
      {/* centre */}
      <AgentOffice position={[0, 0, ROW_M]} onClick={click("PLANNING")} title="Planning" icon="📈"
                   rooms={["Production Planning", "MPS & MRP", "Scenario Simulation", "Capacity & Scheduling"]}
                   sideList={["Master production schedule", "Material requirements", "Capacity planning",
                     "Scheduling", "Replanning"]}
                   tagline="Plan · Coordinate · Deliver" />
      {/* west and east, turned to face the centre */}
      <SalesOffice position={[-58, 0, ROW_M]} rotation={Math.PI / 2} onClick={click("SALES")} />
      <AgentOffice position={[58, 0, ROW_M]} rotation={-Math.PI / 2} onClick={click("HR")} title="HR" icon="👥"
                   rooms={["Workforce Planning", "Skills & Training", "Attendance & Shifts", "Workforce Commitments"]}
                   sideList={["Worker availability", "Skills", "Shifts", "Absences"]}
                   tagline="People · Skills · Shifts" />
      {/* north row, facing south toward the centre */}
      <InventoryWarehouse position={[-62, 0, ROW_N]} onClick={click("INVENTORY")} board={live ? {
        onHand: stock.reduce((n, s) => n + Number(s.on_hand), 0),
        reserved: stock.reduce((n, s) => n + Number(s.reserved), 0),
        empty: stock.filter((s) => Number(s.on_hand) <= 0).length,
      } : undefined} />
      <AgentOffice position={[2, 0, ROW_N]} onClick={click("PURCHASING")} title="Purchasing" icon="🛒" loadingAnnex="Incoming Materials"
                   rooms={["Supplier Management", "Purchase Orders", "Procurement Desk", "Vendor Communication"]}
                   sideList={["Supplier options", "Procurement negotiation", "Delivery scheduling", "Supplier delays"]}
                   tagline="Source · Negotiate · Procure" />
      <WarehouseHall position={[62, 0, ROW_N - 4]} onClick={click("WAREHOUSE")} docks={live ? { inbound, outbound } : undefined} />
    </group>
  );
}

/** Ring roads with dashed centre lines, an avenue to the factory, crossings at the junctions and street trees. */
function Roads() {
  const horizontal = (z: number) => <Road key={`h${z}`} from={[-95, z]} to={[95, z]} />;
  const vertical = (x: number) => <Road key={`v${x}`} from={[x, ROAD_N]} to={[x, ROAD_S]} />;
  return (
    <group>
      {horizontal(ROAD_N)}
      {horizontal(ROAD_S)}
      {vertical(ROAD_W)}
      {vertical(ROAD_E)}
      <Road from={[0, ROAD_S]} to={[0, -16]} />
      {[ROAD_W, 0, ROAD_E].map((x) => [ROAD_N, ROAD_S].map((z) => <Crossing key={`${x}${z}`} x={x} z={z} />))}
      {[-80, -48, -20, 20, 48, 80].map((x) => [ROAD_N - 5, ROAD_S + 5].map((z) => (
        <Tree key={`${x}${z}`} position={[x, 0, z]} />
      )))}
      {[-48, -30].map((z) => [-6, 6].map((x) => <Tree key={`${x}${z}`} position={[x, 0, z]} />))}
    </group>
  );
}

function Road({ from, to }: { from: [number, number]; to: [number, number] }) {
  const [x1, z1] = from, [x2, z2] = to;
  const alongX = z1 === z2;
  const len = alongX ? Math.abs(x2 - x1) : Math.abs(z2 - z1);
  const cx = (x1 + x2) / 2, cz = (z1 + z2) / 2;
  const dashes = Math.floor(len / 8);
  return (
    <group>
      <Block position={[cx, 0.02, cz]} size={alongX ? [len + ROAD, 0.04, ROAD] : [ROAD, 0.04, len]} color={COLORS.road} />
      {[...Array(dashes)].map((_, i) => {
        const t = -len / 2 + 4 + i * 8;
        return (
          <Block key={i} position={alongX ? [cx + t, 0.05, cz] : [cx, 0.05, cz + t]}
                 size={alongX ? [3, 0.02, 0.25] : [0.25, 0.02, 3]} color={COLORS.roadLine} />
        );
      })}
    </group>
  );
}

/** Zebra crossing on all four sides of a junction. */
function Crossing({ x, z }: { x: number; z: number }) {
  const off = ROAD / 2 + 1;
  const stripes = [-2.4, -1.2, 0, 1.2, 2.4];
  return (
    <group>
      {stripes.map((s) => (
        <group key={s}>
          <Block position={[x + s, 0.06, z + off]} size={[0.6, 0.02, 1.8]} color="#ffffff" />
          <Block position={[x + s, 0.06, z - off]} size={[0.6, 0.02, 1.8]} color="#ffffff" />
          <Block position={[x + off, 0.06, z + s]} size={[1.8, 0.02, 0.6]} color="#ffffff" />
          <Block position={[x - off, 0.06, z + s]} size={[1.8, 0.02, 0.6]} color="#ffffff" />
        </group>
      ))}
    </group>
  );
}

/** A pulsing ring on the ground around a building that took part in the latest disruption, with a short label. */
function Beacon({ at, r, origin }: { at: [number, number]; r: number; origin: boolean }) {
  const ring = useRef<Mesh>(null);
  useFrame(({ clock }) => {
    if (ring.current) ring.current.scale.setScalar(1 + 0.06 * Math.sin(clock.elapsedTime * 3));
  });
  const color = origin ? "#d64545" : "#d98a1b";
  return (
    <group position={[at[0], 0.15, at[1]]}>
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[r, r + 1.2, 48]} />
        <meshBasicMaterial color={color} transparent opacity={0.85} />
      </mesh>
      <Pin position={[0, 16, 0]} small tone={origin ? "red" : "amber"} text={origin ? "⚡ disruption source" : "⚡ responding"} />
    </group>
  );
}
