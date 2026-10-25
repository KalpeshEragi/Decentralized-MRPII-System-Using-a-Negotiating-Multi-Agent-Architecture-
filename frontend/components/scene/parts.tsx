"use client";
// Low-poly models built from simple shapes (FE-2), in the soft blue-and-white style of the panel.

import { Html } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import type { ReactNode } from "react";

export const COLORS = {
  ground: "#eef2f8", road: "#c9d2df", roadLine: "#ffffff", apron: "#dde4ee", wall: "#f7f9fc", roof: "#2f6fed",
  roofDark: "#2558c4", door: "#3a63c9", pallet: "#c99a62", box: "#d9a86c", blueBox: "#3468e0", truck: "#2f6fed",
  cab: "#2558c4", forklift: "#f2b733", machineIdle: "#b8c3d4", machineBusy: "#15a37f", person: "#ffcf9f", tree: "#5cb86a",
  trunk: "#8b6a4f", fence: "#cfd8e5",
};

type Click = (event: ThreeEvent<MouseEvent>) => void;

export function Block({ position, size, color, onClick, emissive }: {
  position: [number, number, number]; size: [number, number, number]; color: string; onClick?: Click; emissive?: string;
}) {
  return (
    <mesh position={position} castShadow receiveShadow onClick={onClick}
          onPointerOver={onClick ? () => (document.body.style.cursor = "pointer") : undefined}
          onPointerOut={onClick ? () => (document.body.style.cursor = "auto") : undefined}>
      <boxGeometry args={size} />
      <meshStandardMaterial color={color} emissive={emissive ?? "#000000"} emissiveIntensity={emissive ? 0.35 : 0}
                            roughness={0.85} />
    </mesh>
  );
}

/** A warehouse-style building: white walls, blue roof, dock doors on the front (+z) face. */
export function Building({ position, size, doors = [], label, onClick }: {
  position: [number, number, number]; size: [number, number, number]; doors?: number[]; label?: string; onClick?: Click;
}) {
  const [w, h, d] = size;
  const [x, , z] = position;
  return (
    <group position={[x, 0, z]}>
      <Block position={[0, h / 2, 0]} size={[w, h, d]} color={COLORS.wall} onClick={onClick} />
      <Block position={[0, h + 0.25, 0]} size={[w + 0.6, 0.5, d + 0.6]} color={COLORS.roof} onClick={onClick} />
      <Block position={[0, h * 0.62, d / 2 + 0.02]} size={[w, 0.25, 0.1]} color={COLORS.roofDark} />
      {doors.map((dx) => (
        <group key={dx} position={[dx, 0, d / 2]}>
          <Block position={[0, 1.4, 0.05]} size={[2.6, 2.8, 0.15]} color={COLORS.door} />
          <Block position={[0, 1.1, 0.12]} size={[1.6, 1.4, 0.2]} color={COLORS.box} />
        </group>
      ))}
      {label && <Pin position={[0, h + 1.5, 0]} text={label} />}
    </group>
  );
}

export function Pallet({ position, boxColor = COLORS.box, layers = 2 }: {
  position: [number, number, number]; boxColor?: string; layers?: number;
}) {
  return (
    <group position={position}>
      <Block position={[0, 0.1, 0]} size={[1.3, 0.2, 1.3]} color={COLORS.pallet} />
      {Array.from({ length: layers }).map((_, i) => (
        <group key={i}>
          <Block position={[-0.3, 0.45 + i * 0.5, -0.3]} size={[0.6, 0.48, 0.6]} color={boxColor} />
          <Block position={[0.3, 0.45 + i * 0.5, -0.3]} size={[0.6, 0.48, 0.6]} color={boxColor} />
          <Block position={[-0.3, 0.45 + i * 0.5, 0.3]} size={[0.6, 0.48, 0.6]} color={boxColor} />
          <Block position={[0.3, 0.45 + i * 0.5, 0.3]} size={[0.6, 0.48, 0.6]} color={boxColor} />
        </group>
      ))}
    </group>
  );
}

export function Truck({ color = COLORS.truck, label, carrying = true }: { color?: string; label?: string; carrying?: boolean }) {
  return (
    <group>
      <Block position={[0, 1.6, 0]} size={[2.2, 2.4, 5]} color="#ffffff" />
      <Block position={[1.12, 1.6, 0]} size={[0.02, 1.2, 3.4]} color={color} />
      <Block position={[0, 1.2, 3.2]} size={[2.2, 1.8, 1.4]} color={color} />
      <Block position={[0, 1.7, 3.85]} size={[1.9, 0.7, 0.05]} color="#9cc0ff" />
      {[[-1.1, 1.8], [1.1, 1.8], [-1.1, -1.6], [1.1, -1.6], [-1.1, 3.2], [1.1, 3.2]].map(([wx, wz], i) => (
        <mesh key={i} position={[wx, 0.45, wz]} rotation={[0, 0, Math.PI / 2]} castShadow>
          <cylinderGeometry args={[0.45, 0.45, 0.4, 16]} />
          <meshStandardMaterial color="#2b2f38" />
        </mesh>
      ))}
      {carrying && <Pallet position={[0, 3.0, -1]} layers={1} />}
      {label && <Pin position={[0, 5, 0]} text={label} small />}
    </group>
  );
}

export function Forklift({ carrying }: { carrying?: boolean }) {
  return (
    <group>
      <Block position={[0, 0.6, 0]} size={[1.1, 0.8, 1.6]} color={COLORS.forklift} />
      <Block position={[0, 1.5, -0.3]} size={[1, 0.1, 1]} color="#33363d" />
      <Block position={[-0.45, 1.05, -0.3]} size={[0.08, 1.0, 0.08]} color="#33363d" />
      <Block position={[0.45, 1.05, -0.3]} size={[0.08, 1.0, 0.08]} color="#33363d" />
      <Block position={[0, 1.2, 0.95]} size={[0.9, 1.6, 0.12]} color="#5a5f69" />
      <Block position={[0, 0.25, 1.4]} size={[0.9, 0.06, 0.8]} color="#5a5f69" />
      <mesh position={[0, 1.05, 0.1]} castShadow><sphereGeometry args={[0.22, 12, 12]} />
        <meshStandardMaterial color={COLORS.person} /></mesh>
      {carrying && <Pallet position={[0, 0.3, 1.5]} layers={1} />}
    </group>
  );
}

export function Machine({ position, busy, onClick }: { position: [number, number, number]; busy: boolean; onClick?: Click }) {
  return (
    <group position={position}>
      <Block position={[0, 0.8, 0]} size={[3, 1.6, 2]} color={busy ? "#dff5ee" : "#e8edf4"} onClick={onClick} />
      <Block position={[0, 1.7, 0]} size={[2.4, 0.2, 1.4]} color={busy ? COLORS.machineBusy : COLORS.machineIdle}
             emissive={busy ? COLORS.machineBusy : undefined} onClick={onClick} />
      <Block position={[1.6, 0.5, 0]} size={[0.3, 1, 1.6]} color="#9aa7bb" />
    </group>
  );
}

export function Person({ position, working, absent }: {
  position: [number, number, number]; working: boolean; absent?: boolean;
}) {
  return (
    <group position={position}>
      <mesh position={[0, 0.6, 0]} castShadow><capsuleGeometry args={[0.22, 0.6, 4, 8]} />
        <meshStandardMaterial color={absent ? "#d64545" : working ? "#2f6fed" : "#9aa7bb"} transparent={absent}
                              opacity={absent ? 0.45 : 1} /></mesh>
      <mesh position={[0, 1.25, 0]} castShadow><sphereGeometry args={[0.2, 12, 12]} />
        <meshStandardMaterial color={COLORS.person} /></mesh>
    </group>
  );
}

export function Tree({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <Block position={[0, 0.5, 0]} size={[0.25, 1, 0.25]} color={COLORS.trunk} />
      <mesh position={[0, 1.6, 0]} castShadow><sphereGeometry args={[0.9, 10, 10]} />
        <meshStandardMaterial color={COLORS.tree} roughness={1} /></mesh>
    </group>
  );
}

/** A blue map pin with a small label, like the reference screenshots. */
export function Pin({ position, text, small, tone = "blue" }: {
  position: [number, number, number]; text: ReactNode; small?: boolean; tone?: "blue" | "green" | "amber" | "red";
}) {
  const color = { blue: "#2f6fed", green: "#15a37f", amber: "#d98a1b", red: "#d64545" }[tone];
  return (
    <Html position={position} center distanceFactor={small ? 60 : 70} zIndexRange={[2, 0]}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", pointerEvents: "none" }}>
        <div style={{ background: "#fff", border: `1px solid ${color}33`, color: "#1b2433", borderRadius: 8,
          padding: small ? "2px 6px" : "3px 8px", fontSize: small ? 11 : 12, fontWeight: 600, whiteSpace: "nowrap",
          boxShadow: "0 2px 8px rgba(31,52,88,0.15)" }}>{text}</div>
        <div style={{ width: 10, height: 10, background: color, borderRadius: "50% 50% 50% 0", transform: "rotate(-45deg)",
          marginTop: 2 }} />
      </div>
    </Html>
  );
}
