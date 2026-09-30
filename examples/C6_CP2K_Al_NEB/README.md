# C6: H Diffusion on Al(100) CI-NEB

**System:** H on Al(100) surface (9 atoms: 8 Al + 1 H)
**Task:** CI-NEB barrier calculation (5 replicas)
**Method:** DFT-PBE with GPW, 400 Ry cutoff

## Key Settings

- **Cell:** 7.848 x 7.848 x 20.0 Å (surface slab with vacuum)
- **Periodicity:** XYZ
- **&KIND:** H and Al
- **SUBSYS coordinates:** `&TOPOLOGY` points at the initial-state xyz —
  `&REPLICA` coordinates do NOT exempt SUBSYS from providing a coordinate
  source (CP2K 2026.1 aborts in topology.F with "No atomic coordinates";
  runtime-verified). Each `&REPLICA` overrides the coordinates per image.
- **NEB:** CI-NEB, 5 replicas, K_SPRING 0.05 Ha/bohr²
- **Parallelization:** NPROC_REP 4 (total 20 MPI ranks)

## Files

- `cp2k_neb.inp` — CP2K input file
- `Al_NEB_initial.xyz` — Initial state (H at hollow site)
- `Al_NEB_final.xyz` — Final state (H at bridge/top site)

## Usage

```bash
# Optimize initial and final states separately first (GEO_OPT)
# Then run NEB:
mpirun -np 20 cp2k.popt -i cp2k_neb.inp -o cp2k_neb.out
```

Requires `BASIS_MOLOPT` and `GTH_POTENTIALS` files in the working directory.
Total MPI ranks must equal NPROC_REP × NUMBER_OF_REPLICA = 4 × 5 = 20.
