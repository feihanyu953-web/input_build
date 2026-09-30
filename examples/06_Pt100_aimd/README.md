# V6: Pt(100) Surface AIMD

## System
- Pt(100) 6x6 slab + solvated NH3/NaOH (109 atoms)
- Elements: Pt, O, H, Na, N
- Slab with vacuum (~18 A along z)

## Task
AIMD NVT at 330 K using Langevin thermostat (MDALGO=3)

## Input Files
- `INCAR`  — AIMD parameters (NSW=5000, POTIM=1.0 fs, LWAVE/LCHARG=.FALSE.)
- `KPOINTS` — Gamma-centered 4x4x1 mesh (k-spacing ~0.25 A^-1)
- `POSCAR` — 109-atom solvated Pt slab

## Key Settings
- `LREAL = Auto` (large slab >100 atoms)
- `LANGEVIN_GAMMA = 1.0 5.0 10.0 5.0 5.0` for Pt O H Na N
- `ISYM = 0` (required for MD)
- No huge I/O: `LWAVE = .FALSE.`, `LCHARG = .FALSE.`

## Notes
- 5 ps total at 1 fs/step; extend NSW as needed
- Validate first 100 steps: ion displacement should be < 0.1 A
- POTCAR order must match POSCAR element order for LANGEVIN_GAMMA
