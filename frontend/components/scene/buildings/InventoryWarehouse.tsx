"use client";
// Inventory agent building: a blue-and-white storage warehouse shown as a cutaway (open front, half roof) so the
// racks of boxes inside are visible. Mezzanine office with a live stock board, forklifts, dock doors and a truck.
// Local frame: front faces +z, ground at y = 0, footprint about 26 x 26.

import { Html } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { Block, COLORS, Forklift, Pallet, Pin, Truck } from "../parts";

type V3 = [number, number, number];
type Click = (event: ThreeEvent<MouseEvent>) => void;

const C = {
  wall: "#eef1f5", blue: "#1f4fbf", blueDark: "#173e98", floor: "#d9d6cf", upright: "#2350c8", beam: "#e8622a",
  box: "#d2a56a", wrapped: "#e4dccd", yellow: "#f2c230", shutter: "#8d949e", frame: "#3a414b", tile: "#cfd4db",
  plant: "#4f9a4a", conveyor: "#2a59c9",
};

const W = 24, D = 18, H = 9; // width, depth, wall height

export type StockBoard = { onHand: number; reserved: number; empty: number };

export function InventoryWarehouse({ position, rotation = 0, board, onClick }: {
  position: V3; rotation?: number; board?: StockBoard; onClick?: Click;
}) {
  const front = D / 2;
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      {/* yard + floor */}
      <Block position={[0, 0.04, front + 4]} size={[W + 4, 0.08, 8]} color={C.tile} />
      <Block position={[0, 0.06, 0]} size={[W, 0.12, D]} color={C.floor} />
      {[-7.5, 4, 9].map((x) => <Block key={x} position={[x, 0.13, front - 3]} size={[0.12, 0.02, 5]} color={C.yellow} />)}

      {/* Walls: full back, left, right; low front wall with dock doors on the right half */}
      <Block position={[0, H / 2, -D / 2]} size={[W, H, 0.4]} color={C.wall} onClick={onClick} />
      <Block position={[-W / 2, H / 2, 0]} size={[0.4, H, D]} color={C.wall} onClick={onClick} />
      <Block position={[W / 2, H / 2, 0]} size={[0.4, H, D]} color={C.wall} onClick={onClick} />
      {[-D / 2 + 3, -1, 3, D / 2 - 0.3].map((z) => (
        <Block key={z} position={[-W / 2 - 0.1, H / 2, z]} size={[0.2, H, 0.5]} color={C.blue} />
      ))}
      <Block position={[-W / 2 - 0.1, H * 0.55, 0]} size={[0.15, 0.3, D]} color={C.blue} />
      {[-6, -3].map((z) => <Block key={z} position={[-W / 2 - 0.15, H - 1.8, z]} size={[0.1, 0.9, 2]} color="#9fc0e6" />)}
      <Block position={[-W / 2 - 0.15, 1.2, 5.5]} size={[0.1, 2.4, 1.2]} color={C.frame} />
      <Block position={[-4, 1, front]} size={[16, 2, 0.4]} color={C.wall} />
      <Block position={[8, 1.9, front]} size={[8, 3.8, 0.4]} color={C.wall} />
      {[6, 10].map((x) => <DockDoor key={x} x={x} z={front} />)}
      <Block position={[-1, 1.2, front + 0.22]} size={[1, 2.2, 0.05]} color={C.frame} />

      {/* Roof over the back half + blue parapet all round, front fascia */}
      <Block position={[0, H + 0.15, -D / 4]} size={[W, 0.3, D / 2]} color="#c3cad3" />
      <Block position={[0, H + 0.6, -D / 2]} size={[W + 0.4, 1.2, 0.4]} color={C.blue} />
      <Block position={[-W / 2, H + 0.6, 0]} size={[0.4, 1.2, D]} color={C.blue} />
      <Block position={[W / 2, H + 0.6, 0]} size={[0.4, 1.2, D]} color={C.blue} />
      <Block position={[0, H - 0.3, front]} size={[W + 0.4, 1.4, 0.4]} color={C.blue} />
      <Block position={[0, H + 0.6, -0.2]} size={[W, 1.2, 0.3]} color={C.blueDark} />
      {[-7, 6].map((x) => <Block key={x} position={[x, H + 0.6, -6]} size={[2.4, 0.9, 1.6]} color="#c7ccd3" />)}
      {[-2, 3].map((x) => <Block key={x} position={[x, H + 0.35, -4]} size={[3, 0.12, 1.2]} color="#9fd0f5" emissive="#9fd0f5" />)}
      {[-6, 0, 6].map((x) => <Block key={x} position={[x, H - 1.2, front + 0.3]} size={[0.5, 0.3, 0.3]} color="#ffffff" emissive="#fff2c8" />)}

      {/* Sign panel over the front */}
      <group position={[1, H + 1.2, front + 0.3]}>
        <Block position={[0, 0, 0]} size={[7, 4, 0.3]} color={C.blueDark} />
        <Html transform zIndexRange={[1, 0]} position={[0, 0, 0.2]} scale={1.88} pointerEvents="none">
          <div style={{ color: "#fff", textAlign: "center", fontFamily: "system-ui, sans-serif", userSelect: "none" }}>
            <div style={{ fontSize: 46 }}>📦</div>
            <div style={{ fontSize: 40, fontWeight: 700, lineHeight: 1 }}>Inventory</div>
            <div style={{ fontSize: 16, letterSpacing: 6, marginTop: 4 }}>AGENT</div>
          </div>
        </Html>
      </group>

      {/* Racks on the left half */}
      {[[-10, "A1"], [-6.5, "A2"], [-3, "B1"], [0.5, "B2"]].map(([x, tag]) => (
        <Rack key={tag as string} x={x as number} tag={tag as string} />
      ))}

      {/* Right half: mezzanine office with the stock board, stairs, conveyor, forklifts */}
      <Mezzanine board={board} />
      <group position={[4.5, 0.12, 4]}>
        <Block position={[0, 0.7, 0]} size={[5, 0.15, 1]} color={C.conveyor} />
        {[-2.2, 0, 2.2].map((x) => <Block key={x} position={[x, 0.35, 0]} size={[0.15, 0.7, 0.9]} color={C.frame} />)}
        <Block position={[-1, 1.05, 0]} size={[0.7, 0.55, 0.7]} color={C.box} />
      </group>
      <group position={[-5, 0, 6]} rotation={[0, Math.PI, 0]}><Forklift carrying /></group>
      <group position={[8, 0, 1]} rotation={[0, -Math.PI / 2, 0]}><Forklift /></group>
      <Pallet position={[3, 0.12, 6.5]} />
      <Pallet position={[-8, 0.12, front + 2]} layers={1} />

      {/* Truck at the right dock, bollards, planters */}
      <group position={[10, 0, front + 4.2]}><Truck carrying={false} /></group>
      {[4.3, 7.7, 11.7].map((x) => <Bollard key={x} position={[x, 0, front + 0.8]} />)}
      {[-10, -6, -2].map((x) => (
        <mesh key={x} position={[x, 0.7, front + 1.5]} castShadow>
          <sphereGeometry args={[0.8, 10, 8]} /><meshStandardMaterial color={C.plant} roughness={1} />
        </mesh>
      ))}

      <Pin position={[0, H + 5, 0]} text="Inventory" />
    </group>
  );
}

/** One pallet rack running front-to-back: blue uprights, orange beams, three levels of boxes, an aisle tag. */
function Rack({ x, tag }: { x: number; tag: string }) {
  const len = 12, z0 = -D / 2 + 1.2, levels = [0.15, 2.3, 4.45, 6.6];
  const bays = 4;
  return (
    <group position={[x, 0, z0 + len / 2]}>
      {[...Array(bays + 1)].flatMap((_, i) => [-0.75, 0.75].map((dx) => (
        <Block key={`${i}${dx}`} position={[dx, 4.2, -len / 2 + (i * len) / bays]} size={[0.15, 8.4, 0.15]} color={C.upright} />
      )))}
      {levels.slice(1).map((y) => [-0.75, 0.75].map((dx) => (
        <Block key={`${y}${dx}`} position={[dx, y - 0.1, 0]} size={[0.12, 0.2, len]} color={C.beam} />
      )))}
      {levels.flatMap((y, li) => [...Array(bays)].map((_, b) => {
        const filled = (li + b + tag.charCodeAt(1)) % 5 !== 0; // a few gaps so it looks used
        const color = (li + b) % 3 === 0 ? C.wrapped : C.box;
        return filled ? (
          <group key={`${li}-${b}`} position={[0, y, -len / 2 + (b + 0.5) * (len / bays)]}>
            <Block position={[0, 0.08, 0]} size={[1.3, 0.16, 2.6]} color={COLORS.pallet} />
            <Block position={[0, 0.85, -0.6]} size={[1.2, 1.4, 1.1]} color={color} />
            <Block position={[0, 0.7, 0.6]} size={[1.2, 1.1, 1.1]} color={C.box} />
          </group>
        ) : null;
      }))}
      <Html transform zIndexRange={[1, 0]} position={[0, 7.6, len / 2 + 0.2]} scale={1.25} pointerEvents="none">
        <div style={{ background: "#1f4fbf", color: "#fff", fontWeight: 800, fontSize: 40, padding: "2px 12px",
          borderRadius: 6, border: "3px solid #fff", fontFamily: "system-ui, sans-serif", userSelect: "none" }}>{tag}</div>
      </Html>
    </group>
  );
}

/** Raised glass office at the back right, with stairs and the live stock board on its front edge. */
function Mezzanine({ board }: { board?: StockBoard }) {
  const y = 4, x = 6.5, w = 10, d = 6, z = -D / 2 + d / 2 + 0.2;
  const tiles = [
    ["Stock on hand", board ? board.onHand.toLocaleString() : "–"],
    ["Reserved", board ? board.reserved.toLocaleString() : "–"],
    ["Items at zero", board ? String(board.empty) : "–"],
  ];
  return (
    <group position={[x, 0, z]}>
      {[-w / 2 + 0.3, w / 2 - 0.3].map((px) => <Block key={px} position={[px, y / 2, d / 2 - 0.3]} size={[0.4, y, 0.4]} color="#aab2bd" />)}
      <Block position={[0, y, 0]} size={[w, 0.35, d]} color="#c9ced6" />
      <Block position={[0, y + 1.6, -d / 2 + 0.3]} size={[w, 3, 0.1]} color="#f8f6f1" emissive="#fff4e0" />
      {[-2.5, 0.5, 3].map((dx) => (
        <group key={dx} position={[dx, y + 0.2, -1]}>
          <Block position={[0, 0.75, 0]} size={[1.6, 0.08, 0.8]} color="#e9e4da" />
          <Block position={[0, 1.1, -0.25]} size={[0.6, 0.4, 0.05]} color="#2f6fed" emissive="#2f6fed" />
        </group>
      ))}
      <mesh position={[0, y + 1.6, d / 2 - 0.4]}>
        <boxGeometry args={[w, 3, 0.06]} />
        <meshStandardMaterial color="#cfe3f5" transparent opacity={0.3} />
      </mesh>
      <Block position={[0, y + 3.15, d / 2 - 0.4]} size={[w, 0.12, 0.1]} color={C.frame} />
      {/* stairs on the left side */}
      {[...Array(8)].map((_, i) => (
        <Block key={i} position={[-w / 2 - 0.8, 0.25 + i * 0.5, d / 2 + 1.5 - i * 0.55]} size={[1.4, 0.12, 0.55]} color={C.yellow} />
      ))}
      <Html transform zIndexRange={[1, 0]} position={[0, y - 1.1, d / 2 + 0.05]} scale={1.38} pointerEvents="none">
        <div style={{ display: "flex", gap: 6, fontFamily: "system-ui, sans-serif", userSelect: "none" }}>
          {tiles.map(([k, v]) => (
            <div key={k} style={{ background: "#173e98", color: "#fff", borderRadius: 6, padding: "6px 12px", minWidth: 96 }}>
              <div style={{ fontSize: 13, opacity: 0.85 }}>{k}</div>
              <div style={{ fontSize: 28, fontWeight: 700 }}>{v}</div>
            </div>
          ))}
        </div>
      </Html>
    </group>
  );
}

function DockDoor({ x, z }: { x: number; z: number }) {
  return (
    <group position={[x, 0, z + 0.22]}>
      <Block position={[0, 1.6, 0]} size={[3, 3.2, 0.08]} color={C.shutter} />
      {[0.5, 1.1, 1.7, 2.3, 2.9].map((y) => <Block key={y} position={[0, y, 0.05]} size={[3, 0.05, 0.02]} color="#757c86" />)}
      <Block position={[0, 3.55, 0.35]} size={[3.6, 0.35, 0.8]} color="#3c4450" />
      <Block position={[0, 0.06, 0.6]} size={[3, 0.04, 1]} color={C.yellow} />
    </group>
  );
}

function Bollard({ position }: { position: V3 }) {
  return (
    <group position={position}>
      <Block position={[0, 0.5, 0]} size={[0.3, 1, 0.3]} color={C.yellow} />
      <Block position={[0, 0.55, 0]} size={[0.32, 0.25, 0.32]} color="#22252b" />
    </group>
  );
}
