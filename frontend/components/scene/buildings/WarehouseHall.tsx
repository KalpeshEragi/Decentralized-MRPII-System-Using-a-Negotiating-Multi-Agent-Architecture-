"use client";
// Warehouse agent building: a large cutaway hall (roof only along the back, open steel trusses elsewhere) with
// production machines, workbenches, a rack row, forklifts and workers in vests, an overhead crane, a raised control
// room with a live dock board, a dispatch annex with a truck on the right and a receiving door with a truck on the left.
// Local frame: front faces +z, ground at y = 0, footprint about 34 x 32.

import { Html } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { Block, COLORS, Forklift, Machine, Pallet, Person, Pin, Truck } from "../parts";

type V3 = [number, number, number];
type Click = (event: ThreeEvent<MouseEvent>) => void;

const C = {
  wall: "#eef1f5", blue: "#1f4fbf", blueDark: "#173e98", floor: "#d6d8dc", steel: "#4b525c", yellow: "#f2c230",
  upright: "#2350c8", beam: "#e8622a", box: "#d2a56a", bench: "#2a59c9", benchTop: "#c9d4e6", tile: "#cfd4db",
  shutter: "#8d949e", plant: "#4f9a4a", fence: "#2f3640",
};

const W = 30, D = 24, H = 9;

export type DockBoard = { inbound: number; outbound: number };

export function WarehouseHall({ position, rotation = 0, docks, onClick }: {
  position: V3; rotation?: number; docks?: DockBoard; onClick?: Click;
}) {
  const front = D / 2;
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      {/* yard and floor with yellow lane markings */}
      <Block position={[0, 0.04, front + 5]} size={[W + 10, 0.08, 10]} color={C.tile} />
      <Block position={[0, 0.06, 0]} size={[W, 0.12, D]} color={C.floor} onClick={onClick} />
      {[-4, 4].map((z) => <Block key={z} position={[2, 0.13, z]} size={[22, 0.02, 0.15]} color={C.yellow} />)}
      <Block position={[-3, 0.13, 0]} size={[0.15, 0.02, 20]} color={C.yellow} />

      {/* walls: back and right full height; left wall carries the big blue sign; front stays open */}
      <Block position={[0, H / 2, -D / 2]} size={[W, H, 0.4]} color={C.wall} />
      <Block position={[W / 2, H / 2, 0]} size={[0.4, H, D]} color={C.wall} />
      <Block position={[-W / 2, H / 2, 0]} size={[0.4, H, D]} color={C.wall} />
      <Block position={[0, H + 0.5, -D / 2]} size={[W + 0.4, 1, 0.5]} color={C.blue} />
      <Block position={[W / 2, H + 0.5, 0]} size={[0.5, 1, D]} color={C.blue} />
      <Block position={[-W / 2, H + 0.5, 0]} size={[0.5, 1, D]} color={C.blue} />

      {/* roof strip at the back, open steel trusses over the rest */}
      <Block position={[0, H + 0.1, -D / 2 + 3]} size={[W, 0.25, 6]} color="#c3cad3" />
      {[-9, 0, 9].map((x) => <Block key={x} position={[x, H + 0.6, -D / 2 + 2.5]} size={[2.2, 0.9, 1.4]} color="#c7ccd3" />)}
      {[-9, -3, 3, 9].map((z) => <Block key={z} position={[0, H - 0.2, z]} size={[W, 0.35, 0.3]} color={C.steel} />)}
      {[-10, 0, 10].map((x) => (
        <group key={x}>
          <Block position={[x, H - 0.2, 0]} size={[0.3, 0.35, D]} color={C.steel} />
          <Block position={[x, H / 2, 0]} size={[0.45, H, 0.45]} color={C.steel} />
          <Block position={[x, 0.6, 0]} size={[0.55, 1.2, 0.55]} color={C.yellow} />
        </group>
      ))}
      {[-8, 2, 12].map((x) => [-6, 0, 6].map((z) => (
        <Block key={`${x}${z}`} position={[x, H - 0.6, z]} size={[0.6, 0.15, 0.6]} color="#fff" emissive="#fff3d0" />
      )))}
      {/* overhead crane */}
      <Block position={[4, H - 1, -4]} size={[16, 0.5, 0.6]} color={C.yellow} />
      <Block position={[6, H - 1.6, -4]} size={[0.8, 0.7, 0.8]} color="#3a3f47" />

      {/* left: blue sign wall + receiving door */}
      <group position={[-W / 2, 0, front - 4]}>
        <Block position={[0.6, H / 2 + 1, 0]} size={[1.2, H + 2, 8]} color={C.blue} onClick={onClick} />
        <Html transform zIndexRange={[1, 0]} position={[1.25, H * 0.68, 0]} rotation={[0, Math.PI / 2, 0]} scale={1.75} pointerEvents="none">
          <div style={{ color: "#fff", textAlign: "center", fontFamily: "system-ui, sans-serif", userSelect: "none" }}>
            <div style={{ fontSize: 50, filter: "grayscale(1) brightness(4)" }}>🏭</div>
            <div style={{ fontSize: 36, fontWeight: 800, lineHeight: 1 }}>Warehouse</div>
            <div style={{ fontSize: 14, letterSpacing: 6, marginTop: 4 }}>AGENT</div>
          </div>
        </Html>
        <Block position={[-0.25, 1.7, 0]} size={[0.1, 3.4, 3.4]} color={C.shutter} />
        <group position={[-4.2, 0, 0]} rotation={[0, -Math.PI / 2, 0]}><Truck carrying={false} /></group>
      </group>

      {/* production floor: machines (glow when a line is busy), workbenches, rack row, forklifts, workers */}
      {[[-10, -6], [-5, -6], [0, -6], [-10, -1], [-5, -1]].map(([x, z], i) => (
        <Machine key={i} position={[x, 0.12, z]} busy={i % 3 === 0} />
      ))}
      {[[4, -7], [9, -7], [4, -1.5], [9, -1.5]].map(([x, z], i) => <Workbench key={i} position={[x, 0.12, z]} />)}
      <RackRow position={[-11, 0, -D / 2 + 1.4]} />
      {[[-7, 3, 0], [2, 4, Math.PI / 2], [-1, 8, Math.PI]].map(([x, z, r], i) => (
        <group key={i} position={[x, 0.12, z]} rotation={[0, r, 0]}><Forklift carrying={i !== 1} /></group>
      ))}
      {[[-8, -3.5], [-2.5, -3.5], [6.5, -4.5], [3, 1], [-4, 6], [7, 9]].map(([x, z], i) => (
        <Worker key={i} position={[x, 0.12, z]} />
      ))}
      {[[-10, 7], [-8, 7], [-5, 9], [4, 9], [6, 6]].map(([x, z], i) => (
        <Pallet key={i} position={[x, 0.12, z]} layers={i % 2 ? 1 : 2} />
      ))}

      <ControlRoom docks={docks} />
      <DispatchAnnex />

      {/* front fence with garden beds */}
      <Block position={[-3, 0.6, front + 1.5]} size={[12, 1.2, 0.08]} color={C.fence} />
      {[-8, -5, -2, 1].map((x) => (
        <mesh key={x} position={[x, 1.6, front + 2.6]} castShadow><sphereGeometry args={[1, 8, 8]} />
          <meshStandardMaterial color={C.plant} /></mesh>
      ))}
      <Pallet position={[-14, 0.05, front + 5]} />
      <Pallet position={[-12.4, 0.05, front + 5]} layers={1} />

      <Pin position={[0, H + 5, 0]} text="Warehouse" />
    </group>
  );
}

function Workbench({ position }: { position: V3 }) {
  return (
    <group position={position}>
      <Block position={[0, 0.9, 0]} size={[3.4, 0.12, 1.2]} color={C.benchTop} />
      {[-1.5, 1.5].map((x) => <Block key={x} position={[x, 0.45, 0]} size={[0.12, 0.9, 1.1]} color={C.bench} />)}
      <Block position={[0, 1.6, -0.5]} size={[3.4, 1.2, 0.08]} color={C.bench} />
      <Block position={[-0.8, 1.15, 0]} size={[0.6, 0.4, 0.5]} color={C.box} />
    </group>
  );
}

function RackRow({ position }: { position: V3 }) {
  const len = 8;
  return (
    <group position={position}>
      {[0, 2, 4, 6, 8].map((x) => [-0.6, 0.6].map((z) => (
        <Block key={`${x}${z}`} position={[x, 2.6, z]} size={[0.15, 5.2, 0.15]} color={C.upright} />
      )))}
      {[1.7, 3.4, 5.1].map((y) => <Block key={y} position={[len / 2, y, 0.6]} size={[len, 0.18, 0.12]} color={C.beam} />)}
      {[0.1, 1.8, 3.5].flatMap((y) => [1, 3, 5, 7].map((x) => (
        <Block key={`${x}${y}`} position={[x, y + 0.6, 0]} size={[1.6, 1.1, 1]} color={C.box} />
      )))}
    </group>
  );
}

/** A person in a hi-vis vest and helmet. */
function Worker({ position }: { position: V3 }) {
  return (
    <group position={position}>
      <Person position={[0, 0, 0]} working />
      <Block position={[0, 0.85, 0]} size={[0.48, 0.45, 0.48]} color="#d8e83a" />
      <Block position={[0, 1.45, 0]} size={[0.42, 0.14, 0.42]} color={C.yellow} />
    </group>
  );
}

/** Raised glass control room at the front right with stairs and the live dock board. */
function ControlRoom({ docks }: { docks?: DockBoard }) {
  const y = 3.6, w = 10, d = 6;
  return (
    <group position={[W / 2 - w / 2 - 0.3, 0, 4]}>
      <Block position={[0, y / 2, 0]} size={[w, y, d]} color={C.wall} />
      <Block position={[0, y / 2, d / 2 + 0.02]} size={[w - 1, y - 1, 0.05]} color="#bcd6f2" emissive="#fff1d6" />
      <Block position={[0, y + 0.2, 0]} size={[w + 0.3, 0.4, d + 0.3]} color={C.blue} />
      <Block position={[0, y + 1.6, -d / 2 + 0.2]} size={[w, 2.6, 0.1]} color="#f8f6f1" emissive="#fff4e0" />
      {[-3, -0.5, 2].map((dx) => (
        <group key={dx} position={[dx, y + 0.4, 0]}>
          <Block position={[0, 0.72, 0]} size={[1.8, 0.08, 0.8]} color="#ffffff" />
          <Block position={[0, 1.05, -0.25]} size={[0.5, 0.35, 0.04]} color="#4f8df5" emissive="#4f8df5" />
          <Person position={[0, 0, 0.8]} working />
        </group>
      ))}
      <mesh position={[0, y + 1.6, d / 2]}><boxGeometry args={[w, 2.6, 0.06]} />
        <meshStandardMaterial color="#cfe3f5" transparent opacity={0.25} /></mesh>
      <Block position={[0, y + 2.95, d / 2]} size={[w + 0.3, 0.35, 0.2]} color={C.blue} />
      {[...Array(7)].map((_, i) => (
        <Block key={i} position={[-w / 2 - 0.8, 0.3 + i * 0.55, -d / 2 + 0.6 + i * 0.6]} size={[1.2, 0.12, 0.6]} color={C.yellow} />
      ))}
      <Html transform zIndexRange={[1, 0]} position={[0, y + 0.2, d / 2 + 0.2]} scale={0.95} pointerEvents="none">
        <div style={{ color: "#fff", fontWeight: 700, fontSize: 26, fontFamily: "system-ui, sans-serif", userSelect: "none" }}>
          Control Room
        </div>
      </Html>
      <Html transform zIndexRange={[1, 0]} position={[0, y + 1.9, -d / 2 + 0.3]} scale={1.12} pointerEvents="none">
        <div style={{ display: "flex", gap: 6, fontFamily: "system-ui, sans-serif", userSelect: "none" }}>
          {[["Inbound", docks?.inbound], ["Outbound", docks?.outbound]].map(([k, v]) => (
            <div key={k as string} style={{ background: "#173e98", color: "#fff", borderRadius: 6, padding: "6px 14px" }}>
              <div style={{ fontSize: 13, opacity: 0.85 }}>{k}</div>
              <div style={{ fontSize: 28, fontWeight: 700 }}>{v ?? "–"}</div>
            </div>
          ))}
        </div>
      </Html>
    </group>
  );
}

/** Low dispatch building outside the front right corner, with shutters and a truck at the dock. */
function DispatchAnnex() {
  const w = 10, d = 6, h = 3.8;
  return (
    <group position={[W / 2 - w / 2 + 1, 0, D / 2 + d / 2 - 0.5]}>
      <Block position={[0, h / 2, 0]} size={[w, h, d]} color="#dde2e8" />
      <Block position={[0, h + 0.15, 0]} size={[w + 0.3, 0.3, d + 0.3]} color="#9aa3ae" />
      <Block position={[0, h - 0.2, 0]} size={[w + 0.35, 0.4, d + 0.35]} color={C.blue} />
      {[-2.5, 1].map((x) => <Block key={x} position={[x + 2.5, 1.5, d / 2 + 0.03]} size={[2.6, 3, 0.06]} color={C.shutter} />)}
      <group position={[4, 0, d / 2 + 4]}><Truck carrying={false} /></group>
      <Pallet position={[-1, 0.05, d / 2 + 1.5]} />
      <Block position={[1.5, 0.06, d / 2 + 2]} size={[3, 0.05, 0.12]} color={C.yellow} />
      <Worker position={[-2.5, 0.05, d / 2 + 1.5]} />
      <Block position={[0, 0.05, d / 2 + 3]} size={[w, 0.05, 6]} color={COLORS.apron} />
    </group>
  );
}
