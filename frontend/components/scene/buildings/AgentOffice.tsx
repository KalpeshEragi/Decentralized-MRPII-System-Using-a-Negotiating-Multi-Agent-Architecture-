"use client";
// Two-wing agent office used by Purchasing, Planning and HR: white walls, blue trim, a tall blue sign tower in the
// middle, four glass rooms (two per floor) with labelled teams at desks, a glass entrance with steps, a lit
// monument sign in the front garden and an optional loading annex on the left (Purchasing's incoming materials).
// Local frame: front faces +z, ground at y = 0.

import { Html } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { Block, Forklift, Pallet, Person, Pin, Truck } from "../parts";

type V3 = [number, number, number];
type Click = (event: ThreeEvent<MouseEvent>) => void;

export const OFFICE = {
  wall: "#f2f4f8", blue: "#1f4fbf", blueDark: "#173e98", frame: "#2f353e", glass: "#cfe3f5", room: "#fbf6ec",
  floor: "#e9dfcf", desk: "#e8e1d4", seat: "#2b2f36", screen: "#1d2c4f", monitor: "#4f8df5", tile: "#d4d8de",
  plant: "#4f9a4a", planter: "#c3c8cf", bench: "#b07a45", lamp: "#ffe6b0",
};
const C = OFFICE;

const WING = 8, TOWER = 4.4, D = 11, F = 3.6; // wing width, tower width, depth, floor height
const W = WING * 2 + TOWER;

export type OfficeProps = {
  position: V3; rotation?: number;
  title: string;            // big word on the tower, e.g. "Planning"
  icon: string;             // emoji shown above the title
  rooms: [string, string, string, string]; // upper-left, upper-right, lower-left, lower-right
  sideList?: string[];      // responsibilities painted on the left wall
  tagline?: string;         // monument sign, e.g. "Source · Negotiate · Procure"
  loadingAnnex?: string;    // label of a loading bay on the left (truck + forklift)
  onClick?: Click;
};

export function AgentOffice({ position, rotation = 0, title, icon, rooms, sideList, tagline, loadingAnnex, onClick }: OfficeProps) {
  const xL = -(TOWER / 2 + WING / 2), xR = -xL, z = D / 2;
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      <Grounds tagline={tagline ?? ""} title={title} icon={icon} />

      {/* wings */}
      {[xL, xR].map((x) => (
        <group key={x}>
          <Block position={[x, F, 0]} size={[WING, F * 2, D]} color={C.wall} onClick={onClick} />
          <Block position={[x, F * 2 + 0.4, 0]} size={[WING + 0.4, 0.8, D + 0.4]} color={C.blue} onClick={onClick} />
          <Block position={[x, F, z + 0.2]} size={[WING + 0.1, 0.55, 0.4]} color={C.blue} />
        </group>
      ))}
      <Room position={[xL, F + 0.3, z]} label={rooms[0]} />
      <Room position={[xR, F + 0.3, z]} label={rooms[1]} />
      <Room position={[xL, 0.15, z]} label={rooms[2]} />
      <Room position={[xR, 0.15, z]} label={rooms[3]} />

      {/* rooftop units */}
      {[[xL - 1.5, -2], [xR + 1.2, -2.5]].map(([x, rz]) => (
        <group key={x} position={[x, F * 2 + 0.8, rz]}>
          <Block position={[0, 0.5, 0]} size={[2.6, 1, 1.6]} color="#c7ccd3" />
          <Block position={[0, 0.55, 0.82]} size={[2, 0.6, 0.04]} color="#7d858f" />
        </group>
      ))}

      {/* sign tower + entrance */}
      <Block position={[0, F + 1, 0.4]} size={[TOWER, F * 2 + 2, D + 0.8]} color={C.blue} onClick={onClick} />
      <Block position={[0, F * 2 + 2.05, 0.4]} size={[TOWER + 0.3, 0.2, D + 1.1]} color={C.blueDark} />
      <Html transform zIndexRange={[1, 0]} position={[0, F * 1.45, z + 0.85]} scale={1.5} pointerEvents="none">
        <div style={{ color: "#fff", textAlign: "center", fontFamily: "system-ui, sans-serif", userSelect: "none",
          textShadow: "0 0 10px rgba(255,255,255,0.5)" }}>
          <div style={{ fontSize: 52, lineHeight: 1.1, filter: "grayscale(1) brightness(4)" }}>{icon}</div>
          <div style={{ fontSize: 34, fontWeight: 800, lineHeight: 1.05 }}>{title}</div>
          <div style={{ fontSize: 14, letterSpacing: 6, marginTop: 4 }}>AGENT</div>
        </div>
      </Html>
      {[-1.2, 1.2].map((x) => <Block key={x} position={[x, F * 2 + 1.6, z + 0.9]} size={[0.3, 0.15, 0.3]} color="#fff" emissive={C.lamp} />)}
      <Entrance z={z + 0.8} />

      {sideList && <SideList items={sideList} x={-W / 2} />}
      {loadingAnnex && <LoadingAnnex label={loadingAnnex} x={-W / 2} />}
      <Pin position={[0, F * 2 + 5, 0]} text={title} />
    </group>
  );
}

/** A glass room with a lit back wall, a dark wall screen, desks with monitors and people working. */
function Room({ position, label }: { position: V3; label: string }) {
  const w = WING - 0.6, h = F - 0.9;
  return (
    <group position={position}>
      <Block position={[0, 0.05, -1.4]} size={[w, 0.1, 2.8]} color={C.floor} />
      <Block position={[0, h / 2, -2.8]} size={[w, h, 0.1]} color={C.room} emissive="#fff1d6" />
      <Block position={[1.2, h * 0.62, -2.72]} size={[2.6, 1.1, 0.06]} color={C.screen} emissive="#24407a" />
      {[-0.4, 0, 0.4].map((dy, i) => (
        <Block key={i} position={[1.2, h * 0.62 + dy, -2.67]} size={[2.2, 0.06, 0.02]} color="#6fa8ff" emissive="#6fa8ff" />
      ))}
      {[-2.4, -0.4, 1.6].map((dx) => (
        <group key={dx} position={[dx, 0.1, -1]}>
          <Block position={[0, 0.72, 0]} size={[1.5, 0.08, 0.7]} color={C.desk} />
          <Block position={[0, 1.02, -0.2]} size={[0.45, 0.32, 0.04]} color={C.monitor} emissive={C.monitor} />
          <Block position={[0, 0.4, 0.55]} size={[0.45, 0.55, 0.45]} color={C.seat} />
          <Person position={[0.1, 0, 0.7]} working />
        </group>
      ))}
      <mesh position={[3, 0.6, -2.3]} castShadow><sphereGeometry args={[0.4, 8, 8]} />
        <meshStandardMaterial color={C.plant} /></mesh>
      {/* glass + frame */}
      <mesh position={[0, h / 2 + 0.1, 0.05]}>
        <boxGeometry args={[w, h, 0.06]} /><meshStandardMaterial color={C.glass} transparent opacity={0.22} />
      </mesh>
      {[-w / 2, 0, w / 2].map((x) => <Block key={x} position={[x, h / 2 + 0.1, 0.1]} size={[0.1, h, 0.08]} color={C.frame} />)}
      <Block position={[0, 0.1, 0.1]} size={[w, 0.1, 0.1]} color={C.frame} />
      <Block position={[0, h + 0.1, 0.1]} size={[w, 0.1, 0.1]} color={C.frame} />
      <Html transform zIndexRange={[1, 0]} position={[-w / 2 + 2.1, h - 0.3, -2.7]} scale={0.95} pointerEvents="none">
        <div style={{ color: "#173e98", fontWeight: 700, fontSize: 26, whiteSpace: "nowrap", userSelect: "none",
          fontFamily: "system-ui, sans-serif" }}>{label}</div>
      </Html>
    </group>
  );
}

/** Glass double doors under a canopy, a reception desk behind, steps in front. */
function Entrance({ z }: { z: number }) {
  return (
    <group position={[0, 0, z]}>
      <Block position={[0, F - 0.25, 0.9]} size={[TOWER + 1.2, 0.35, 2]} color={C.blueDark} />
      {[-1, 1].map((x) => <Block key={x} position={[x, F - 0.45, 1.4]} size={[0.25, 0.08, 0.25]} color="#fff" emissive={C.lamp} />)}
      <Block position={[0, 1.6, -0.6]} size={[TOWER - 0.6, 3, 0.1]} color={C.room} emissive="#ffe9c4" />
      <Block position={[0, 0.55, -0.3]} size={[2, 0.9, 0.5]} color="#ffffff" />
      <mesh position={[0, 1.55, 0.02]}>
        <boxGeometry args={[TOWER - 0.6, 3, 0.06]} /><meshStandardMaterial color={C.glass} transparent opacity={0.25} />
      </mesh>
      {[-(TOWER - 0.6) / 2, -0.6, 0.6, (TOWER - 0.6) / 2].map((x) => (
        <Block key={x} position={[x, 1.55, 0.06]} size={[0.1, 3, 0.08]} color={C.frame} />
      ))}
      {[0, 1, 2].map((i) => (
        <Block key={i} position={[0, 0.18 - i * 0.06, 0.7 + i * 0.6]} size={[TOWER + 2 - i * 0.4, 0.36 - i * 0.12, 0.6]} color={C.tile} />
      ))}
      <Block position={[0, 0.38, 0.6]} size={[2, 0.02, 0.8]} color="#3e434b" />
    </group>
  );
}

/** Paved forecourt, garden beds, lamp posts, bench, and the lit monument sign. */
function Grounds({ tagline, title, icon }: { tagline: string; title: string; icon: string }) {
  const z = D / 2;
  return (
    <group>
      <Block position={[0, 0.05, z + 3.2]} size={[W + 2, 0.1, 6.4]} color={C.tile} />
      {[-7, 7].map((x) => (
        <group key={x} position={[x, 0, z + 1.4]}>
          <Block position={[0, 0.25, 0]} size={[5.5, 0.5, 1.4]} color={C.planter} />
          {[-2, -0.7, 0.6, 1.9].map((dx) => (
            <mesh key={dx} position={[dx, 0.85, 0]} castShadow><sphereGeometry args={[0.55, 8, 8]} />
              <meshStandardMaterial color={C.plant} roughness={1} /></mesh>
          ))}
        </group>
      ))}
      <group position={[-5, 0, z + 4]}>
        <Block position={[0, 0.55, 0]} size={[2.2, 0.12, 0.6]} color={C.bench} />
        {[-0.95, 0.95].map((x) => <Block key={x} position={[x, 0.27, 0]} size={[0.08, 0.55, 0.55]} color={C.seat} />)}
      </group>
      {[-10, -3, 3, 10].map((x) => (
        <group key={x} position={[x, 0, z + 6]}>
          <Block position={[0, 0.6, 0]} size={[0.18, 1.2, 0.18]} color="#2b2f36" />
          <Block position={[0, 1.3, 0]} size={[0.3, 0.3, 0.3]} color="#fff" emissive={C.lamp} />
        </group>
      ))}
      {/* monument sign */}
      <group position={[6, 0, z + 5]}>
        <Block position={[0, 0.9, 0]} size={[5.5, 1.8, 0.6]} color="#e6e8ec" />
        <Html transform zIndexRange={[1, 0]} position={[0, 0.95, 0.32]} scale={0.8} pointerEvents="none">
          <div style={{ color: "#173e98", textAlign: "center", fontFamily: "system-ui, sans-serif", userSelect: "none" }}>
            <div style={{ fontSize: 30, fontWeight: 800, whiteSpace: "nowrap" }}>{icon} {title.toUpperCase()} AGENT</div>
            {tagline && <div style={{ fontSize: 16, letterSpacing: 2, color: "#2b2f36" }}>{tagline.toUpperCase()}</div>}
          </div>
        </Html>
      </group>
    </group>
  );
}

/** Responsibilities written on the left wall, like the reference images. */
function SideList({ items, x }: { items: string[]; x: number }) {
  return (
    <Html transform zIndexRange={[1, 0]} position={[x - 0.05, F, 0]} rotation={[0, -Math.PI / 2, 0]} scale={1.0} pointerEvents="none">
      <div style={{ color: "#173e98", fontFamily: "system-ui, sans-serif", fontWeight: 600, fontSize: 22,
        lineHeight: 1.9, userSelect: "none", whiteSpace: "nowrap" }}>
        {items.map((t) => <div key={t}>▪ {t}</div>)}
      </div>
    </Html>
  );
}

/** Low annex on the left with a roller door, a truck being unloaded and a forklift. */
function LoadingAnnex({ label, x }: { label: string; x: number }) {
  const w = 7, h = 4.2;
  return (
    <group position={[x - w / 2, 0, 0.5]}>
      <Block position={[0, h / 2, -1]} size={[w, h, D - 1]} color={C.wall} />
      <Block position={[0, h + 0.2, -1]} size={[w + 0.3, 0.4, D - 0.7]} color={C.blue} />
      <Block position={[0, 1.5, D / 2 - 1.45]} size={[4.5, 3, 0.1]} color="#4a4f57" />
      <Block position={[0, 3.2, D / 2 - 1.1]} size={[5, 0.3, 0.8]} color="#3c4450" />
      <Pallet position={[-1, 0, D / 2 - 2.6]} />
      <Pallet position={[1.2, 0, D / 2 - 2.6]} />
      <group position={[-0.8, 0, D / 2 + 3.6]}><Truck /></group>
      <group position={[2.6, 0, D / 2 + 1.2]} rotation={[0, -Math.PI / 2, 0]}><Forklift carrying /></group>
      <Block position={[0, 0.06, D / 2 + 2.5]} size={[w + 1, 0.06, 6]} color={C.tile} />
      <Html transform zIndexRange={[1, 0]} position={[0, h - 0.6, D / 2 - 1.4]} scale={0.88} pointerEvents="none">
        <div style={{ color: "#173e98", fontWeight: 700, fontSize: 24, whiteSpace: "nowrap", userSelect: "none",
          fontFamily: "system-ui, sans-serif" }}>🚚 {label}</div>
      </Html>
    </group>
  );
}
