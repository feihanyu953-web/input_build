# C5: Al FCC Bulk Cell Optimization

**System:** Al FCC bulk (4 atoms)
**Task:** Cell + geometry simultaneous optimization
**Method:** DFT-PBE with GPW, 400 Ry cutoff

## Key Settings

- **Cell:** 4.0495 x 4.0495 x 4.0495 Å (initial guess)
- **Periodicity:** XYZ
- **&KIND:** Al only
- **K-points:** Monkhorst-Pack 9x9x9 (bulk metal)
- **Smearing:** Fermi-Dirac @ 300 K with ADDED_MOS 10
- **STRESS_TENSOR:** ANALYTICAL (required for CELL_OPT)
- **Optimizer:** BFGS, DIRECT_CELL_OPT
- **Pressure:** 1.01325 bar (1 atm)

## Files

- `cp2k_cell_opt.inp` — CP2K input file
- `Al_bulk.xyz` — Structure (4 Al atoms, FCC primitive cell)

## Usage

```bash
cp2k.popt -i cp2k_cell_opt.inp -o cp2k_cell_opt.out
```

Requires `BASIS_MOLOPT` and `GTH_POTENTIALS` files in the working directory.
