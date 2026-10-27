---
status: accepted
date: 2026-10-27
---

# City models: code-built style kits for buildings, model packs for the rest

The control panel is redesigned as a city in the exact style of the reference video (FE-7), with models of the video's quality or better and detail everywhere. FE-2 ("models built in code from simple shapes; no downloaded model packs") cannot reach that for vehicles, people and trees.

We decided:
- **Buildings are built in code** from blocks, with one **style kit per building type** (warehouse, factory, agent office, Town Square, houses, supplier depot), shaped after the video's buildings. Code keeps live-data parts (dock doors, stock, line lights) easy to drive, one consistent style, a tiny download and reviewable diffs.
- **Vehicles, people, trees and street props come from free CC0 model packs** (no licence or attribution duties), recoloured to the video's palette.

Supersedes FE-2.

## Considered options

- **Everything in code:** cannot match the video's trucks, forklifts, people and trees.
- **Custom models for every building (Blender or a 3D artist):** closest to the video, but needs modelling skill or money, slows every change, needs a naming contract for live-data parts and adds large binary files. Kept as a later upgrade: a building can be swapped for a custom model without touching the rest, if the first finished district still looks clearly below the video.
- **AI-generated models:** fast, but inconsistent style and heavy, messy meshes.
