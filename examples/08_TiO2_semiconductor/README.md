# V8: TiO2 Rutile Semiconductor SCF

## System
- Rutile TiO2, tetragonal cell (6 atoms: 2 Ti + 4 O)
- Wide-gap oxide semiconductor, non-magnetic

## Task
Static SCF with tetrahedron method for accurate DOS/bandgap

## Input Files
- `INCAR`  — Semiconductor SCF (semiconductor.patch applied)
- `KPOINTS` — Gamma-centered 8x8x12 mesh (k-spacing ~0.18 A^-1)
- `POSCAR` — TiO2 rutile conventional cell

## Key Settings
- `ISMEAR = -5` (tetrahedron with Blochl correction)
- `SIGMA = 0.05` (small, exact for tetrahedron)
- `ISPIN = 1` (non-magnetic)
- `LREAL = .FALSE.` (small cell, accurate)

## Notes
- Dense mesh required for tetrahedron method validity
- For publication-quality bandgap, consider ENCUT = 1.3 x max ENMAX
