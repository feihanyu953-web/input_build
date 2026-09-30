# V7: Fe3O4 Bulk Magnetic SCF

## System
- Magnetite (Fe3O4) inverse spinel, cubic cell (56 atoms: 24 Fe + 32 O)
- Ferrimagnetic: tetrahedral Fe(A) antiparallel to octahedral Fe(B)

## Task
Static spin-polarized SCF with DFT+U (Fe 3d) and tetrahedron smearing

## Input Files
- `INCAR`  — Magnetic SCF (ISPIN=2, ISMEAR=-5, DFT+U)
- `KPOINTS` — MP-centered 4x4x4 mesh (k-spacing ~0.20 A^-1)
- `POSCAR` — Fe3O4 conventional cubic cell

## Key Settings
- `ISPIN = 2` (magnetic.patch applied)
- `ISMEAR = -5` (tetrahedron method, dense 4x4x4 mesh)
- `LREAL = .FALSE.` (accurate reciprocal-space for static)
- `LMAXMIX = 4` (required for Fe 3d DFT+U)
- `LDAU = .TRUE.` with `LDAUL = 2 -1`, `LDAUU = 4.3 0.0`
- MAGMOM comment for ferrimagnetic ordering included

## Notes
- For accurate ferrimagnetic ground state, explicitly set `MAGMOM = 8*5.0 16*-5.0 32*0.0`
- O POTCAR ENMAX typically ~300 eV; verify ENCUT covers max ENMAX
