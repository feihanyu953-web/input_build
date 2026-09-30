# V10: H Diffusion on Al(100) NEB

## System
- Al(100) surface slab + H atom (9 atoms total: 8 Al + 1 H)
- Small system, Gamma-only k-sampling sufficient

## Task
CI-NEB transition-state search for H diffusion (requires VTST-patched VASP; see below)

## Input Files
- `INCAR`  — NEB parameters (IMAGES=3, LCLIMB=.TRUE.)
- `KPOINTS` — Gamma-only (1x1x1)
- `POSCAR_initial` — Initial state (H at hollow site)
- `POSCAR_final` — Final state (H at bridge/neighbor site)

## Key Settings
- `IMAGES = 3`
- `SPRING = -5.0` (negative = improved tangent NEB)
- `LCLIMB = .TRUE.` (climbing-image) — **VTST extension tag**: stock VASP does not
  recognize `LCLIMB`. For a stock VASP build, delete the `LCLIMB` line in `INCAR`;
  the job then runs as a plain NEB (no climbing image), not CI-NEB.
- `ISYM = 0` (symmetry broken along path)
- `LREAL = .FALSE.` (small cell)

## Notes
- Prepare 3 intermediate image directories (01/, 02/, 03/) with linearly interpolated POSCARs
- Copy `POSCAR_initial` to `00/POSCAR` and `POSCAR_final` to `04/POSCAR`
- Run with `mpirun -np N vasp_std` where N divides (IMAGES+2) appropriately
