# C2: H2O Molecule Geometry Optimization

**System:** Isolated H2O molecule (3 atoms)
**Task:** Geometry optimization (BFGS)
**Method:** DFT-PBE with GPW, 400 Ry cutoff

## Key Settings

- **Cell:** 20.0 x 20.0 x 20.0 Å (isolated molecule)
- **Periodicity:** NONE (both &CELL and &POISSON) + `POISSON_SOLVER ANALYTIC` (0D-compatible solver; the default PERIODIC solver is invalid for non-periodic systems)
- **&KIND:** H and O
- **Geo-opt:** BFGS optimizer
- **No k-points:** molecule

## Files

- `cp2k_geo_opt.inp` — CP2K input file
- `H2O.xyz` — Structure (1 O + 2 H)

## Usage

```bash
cp2k.popt -i cp2k_geo_opt.inp -o cp2k_geo_opt.out
```

Requires `BASIS_MOLOPT` and `GTH_POTENTIALS` files in the working directory.
