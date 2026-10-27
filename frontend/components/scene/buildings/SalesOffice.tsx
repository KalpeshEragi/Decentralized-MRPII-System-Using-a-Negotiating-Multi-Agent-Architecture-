"use client";
// Sales agent building: a two-storey office with white walls, blue trim, glass fronts with desks inside,
// a handshake sign over the entrance canopy, rooftop HVAC units and a tiled front plaza.
// Local frame: front faces +z, ground at y = 0, footprint about 22 x 18.

import { Html } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { Block, Pin } from "../parts";

type V3 = [number, number, number];
type Click = (event: ThreeEvent<MouseEvent>) => void;

const C = {
  wall: "#f4f6f9", blue: "#1f4fd8", grey: "#9aa3ae", darkGrey: "#4a525c", frame: "#3a414b", tile: "#d9dde3",
  tileDark: "#c4c9d1", asphalt: "#5b6068", floor: "#ede7dc", desk: "#d8b98c", seat: "#2b2f36", screen: "#2f6fed",
  plant: "#4f9a4a", planter: "#b9bec6", bench: "#b07a45",
};

const W = 16, D = 11, F = 3.4; // building width, depth, floor height

export function SalesOffice({ position, rotation = 0, label = "Sales", onClick }: {
  position: V3; rotation?: number; label?: string; onClick?: Click;
}) {
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      <Plaza />
      {/* Body and trim */}
      <Block position={[0, F, 0]} size={[W, F * 2, D]} color={C.wall} onClick={onClick} />
      <Block position={[0, F * 2 + 0.35, 0]} size={[W + 0.5, 0.7, D + 0.5]} color={C.blue} onClick={onClick} />
      <Block position={[0, F * 2 + 0.72, 0]} size={[W - 0.3, 0.05, D - 0.3]} color="#dfe3e8" />
      <Block position={[0, F, D / 2 + 0.06]} size={[W + 0.1, 0.25, 0.15]} color={C.blue} />
      <Block position={[-W / 2 - 0.06, F, 0]} size={[0.15, 0.25, D]} color={C.blue} />
      {[-W / 2 + 0.6, W / 2 - 0.6].map((x) => (
        <Block key={x} position={[x, F, D / 2 + 0.08]} size={[1.2, F * 2, 0.15]} color={C.blue} />
      ))}
      <Block position={[-W / 2 - 0.08, F, D / 2 - 2.2]} size={[0.15, F * 2, 1.2]} color={C.blue} />

      {/* Front glass: upper floor left + right, ground floor left + right, entrance in the middle */}
      <Storefront x={-4.4} y={F + 0.6} width={5.6} />
      <Storefront x={4.4} y={F + 0.6} width={5.6} />
      <Storefront x={-4.4} y={0.15} width={5.6} reception />
      <Storefront x={4.4} y={0.15} width={5.6} />
      <Entrance />

      {/* Side windows (left face) */}
      {[-2.5, 0.2, 2.9].map((z) => (
        <group key={z}>
          <Glass position={[-W / 2 - 0.05, F + 1.7, z - 1]} size={[0.1, 1.6, 0.9]} />
          {z < 2 && <Glass position={[-W / 2 - 0.05, 1.6, z - 1]} size={[0.1, 1.6, 0.9]} />}
        </group>
      ))}
      <Block position={[-W / 2 - 0.05, 1.1, 3.1]} size={[0.1, 2.2, 1.1]} color={C.grey} />

      {/* Wall lamps */}
      {[-W / 2 + 1.5, W / 2 - 1.5].map((x) => (
        <Block key={x} position={[x, F + 2.2, D / 2 + 0.15]} size={[0.25, 0.45, 0.2]} color={C.darkGrey}
               emissive="#ffd9a0" />
      ))}

      <Rooftop />
      <Pin position={[0, F * 2 + 4, 0]} text={label} />
    </group>
  );
}

/** Blue sign panel with the handshake icon, above the canopy. */
function Sign() {
  return (
    <group position={[0, F + 1.7, D / 2 + 0.12]}>
      <Block position={[0, 0, 0]} size={[3, F * 1.05, 0.2]} color={C.blue} />
      {[-0.6, 0.6].map((x) => (
        <Block key={x} position={[x, 1.45, 0.15]} size={[0.8, 0.08, 0.1]} color="#ffffff" emissive="#ffffff" />
      ))}
      <Html transform zIndexRange={[1, 0]} position={[0, 0, 0.12]} scale={1.5} occlude={false} pointerEvents="none">
        <div style={{ fontSize: 48, color: "#fff", filter: "grayscale(1) brightness(3)", userSelect: "none" }}>🤝</div>
      </Html>
    </group>
  );
}

/** Entrance: canopy on two posts, glass double doors, door mat. */
function Entrance() {
  const z = D / 2;
  return (
    <group>
      <Sign />
      <Block position={[0, F / 2 - 0.05, z + 0.02]} size={[3, F - 0.1, 0.1]} color={C.wall} />
      <Glass position={[0, 1.3, z + 0.1]} size={[2.6, 2.6, 0.08]} framed />
      <Block position={[0, 1.3, z + 0.16]} size={[0.06, 2.6, 0.05]} color={C.frame} />
      {/* canopy */}
      <Block position={[0.6, F - 0.3, z + 1.6]} size={[5.4, 0.45, 3.2]} color={C.blue} />
      <Block position={[0.6, F - 0.05, z + 1.6]} size={[5.1, 0.06, 2.9]} color="#e4e8ee" />
      {[-1.6, 2.8].map((x) => <Block key={x} position={[x, (F - 0.5) / 2, z + 2.9]} size={[0.35, F - 0.5, 0.35]} color={C.grey} />)}
      <Block position={[0, 0.03, z + 1.6]} size={[2.4, 0.04, 1.3]} color={C.darkGrey} />
    </group>
  );
}

/** A framed glass strip with a lit room behind it (desks, chairs, screens; a reception counter if asked). */
function Storefront({ x, y, width, reception }: { x: number; y: number; width: number; reception?: boolean }) {
  const h = F - 0.9, z = D / 2;
  const panes = 4;
  return (
    <group position={[x, y, 0]}>
      {/* room behind the glass */}
      <Block position={[0, 0.05, z - 1.3]} size={[width, 0.1, 2.4]} color={C.floor} />
      <Block position={[0, h / 2, z - 2.5]} size={[width, h, 0.1]} color="#fbfaf7" emissive="#fff4e0" />
      {reception ? (
        <group>
          <Block position={[-0.6, 0.55, z - 1.2]} size={[2.2, 1, 0.7]} color="#ffffff" />
          <Block position={[-0.6, 0.12, z - 0.84]} size={[2.2, 0.08, 0.02]} color={C.blue} />
          <Block position={[-0.6, 1.25, z - 1.6]} size={[0.5, 0.35, 0.05]} color={C.screen} emissive={C.screen} />
          <Plant position={[-2.2, 0, z - 0.8]} size={0.45} />
        </group>
      ) : (
        [-1.6, 0.4, 2].filter((dx) => Math.abs(dx) < width / 2).map((dx) => (
          <group key={dx} position={[dx, 0, z - 1.4]}>
            <Block position={[0, 0.75, 0]} size={[1.4, 0.08, 0.7]} color={C.desk} />
            <Block position={[0, 1.05, -0.2]} size={[0.5, 0.35, 0.04]} color={C.screen} emissive={C.screen} />
            <Block position={[0, 0.45, 0.6]} size={[0.45, 0.6, 0.45]} color={C.seat} />
          </group>
        ))
      )}
      {/* glass + frame */}
      <Glass position={[0, h / 2 + 0.1, z + 0.1]} size={[width, h, 0.06]} />
      {[...Array(panes + 1)].map((_, i) => (
        <Block key={i} position={[-width / 2 + (i * width) / panes, h / 2 + 0.1, z + 0.14]} size={[0.08, h, 0.06]}
               color={C.frame} />
      ))}
      <Block position={[0, 0.1, z + 0.14]} size={[width, 0.1, 0.08]} color={C.frame} />
      <Block position={[0, h + 0.1, z + 0.14]} size={[width, 0.1, 0.08]} color={C.frame} />
    </group>
  );
}

function Glass({ position, size, framed }: { position: V3; size: V3; framed?: boolean }) {
  return (
    <group position={position}>
      <mesh>
        <boxGeometry args={size} />
        <meshStandardMaterial color="#cfe3f5" transparent opacity={0.28} roughness={0.05} metalness={0.2} />
      </mesh>
      {framed && <Block position={[0, size[1] / 2, 0]} size={[size[0], 0.08, size[2] + 0.04]} color={C.frame} />}
    </group>
  );
}

/** Rooftop HVAC units. */
function Rooftop() {
  const top = F * 2 + 0.75;
  return (
    <group position={[-3.5, top, -2.2]}>
      <Block position={[0, 0.6, 0]} size={[3, 1.2, 1.8]} color="#c7ccd3" />
      {[-0.8, -0.3, 0.2, 0.7].map((x) => <Block key={x} position={[x, 0.7, 0.92]} size={[0.3, 0.7, 0.04]} color="#7d858f" />)}
      <Block position={[-2.6, 0.4, 0.2]} size={[1.2, 0.8, 1]} color="#c7ccd3" />
      <Block position={[2, 0.25, 0.6]} size={[0.7, 0.5, 0.6]} color="#b4bac2" />
    </group>
  );
}

/** Tiled front plaza with planters, bench, hedge and a dark parking strip. */
function Plaza() {
  const z = D / 2;
  return (
    <group>
      <Block position={[0, 0.06, z + 3.3]} size={[W + 2, 0.12, 6.6]} color={C.tile} />
      <Block position={[-W / 2 - 1.3, 0.06, 0]} size={[2.6, 0.12, D + 2]} color={C.tile} />
      <Block position={[4, 0.1, z + 5.2]} size={[9, 0.06, 2.6]} color={C.asphalt} />
      {[-7.4, -5.2, 2.6, 7.4].map((x, i) => (
        <group key={x}>
          <Block position={[x, 0.45, i === 0 ? z + 4.8 : z + 1]} size={[1.1, 0.7, 1.1]} color={C.planter} />
          <Plant position={[x, 0.8, i === 0 ? z + 4.8 : z + 1]} size={0.6} />
        </group>
      ))}
      {/* bench */}
      <group position={[-4.5, 0, z + 3.6]}>
        <Block position={[0, 0.55, 0]} size={[2.2, 0.12, 0.6]} color={C.bench} />
        {[-0.95, 0.95].map((x) => <Block key={x} position={[x, 0.27, 0]} size={[0.08, 0.55, 0.55]} color={C.seat} />)}
      </group>
      {/* hedge along the left wall */}
      <Block position={[-W / 2 - 1.3, 0.3, -1]} size={[1, 0.4, 6]} color={C.planter} />
      {[-3.4, -2.2, -1, 0.2, 1.4].map((z2) => <Plant key={z2} position={[-W / 2 - 1.3, 0.5, z2]} size={0.5} />)}
    </group>
  );
}

function Plant({ position, size }: { position: V3; size: number }) {
  return (
    <mesh position={[position[0], position[1] + size * 0.7, position[2]]} castShadow>
      <sphereGeometry args={[size, 10, 8]} />
      <meshStandardMaterial color={C.plant} roughness={1} />
    </mesh>
  );
}
