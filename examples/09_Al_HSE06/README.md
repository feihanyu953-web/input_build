# V9: Al FCC HSE06 Hybrid Functional

## System
- Aluminum FCC bulk, cubic cell (4 atoms)
- Simple metal, test case for hybrid functional

## Task
Static SCF with HSE06 hybrid functional

## Input Files
- `INCAR`  — HSE06 parameters (LHFCALC=.TRUE., HFSCREEN=0.2)
- `KPOINTS` — Gamma-centered 8x8x8 mesh (k-spacing ~0.20 A^-1)
- `POSCAR` — Al FCC conventional cell

## Key Settings
- `LHFCALC = .TRUE.`, `HFSCREEN = 0.2` (HSE06)
- `PREC = Accurate`, `PRECFOCK = Fast`
- `LREAL = .FALSE.` (small cell)
- `LCHARG = .TRUE.`, `LWAVE = .TRUE.` (for restart)
- Geometry section commented out (static only)

## Notes
- HSE06 is ~10-100x more expensive than PBE; consider PBE pre-convergence first
- For production, test `PRECFOCK = Normal` and `NKRED` convergence
- NPAR must divide NBANDS evenly for hybrid parallelization
