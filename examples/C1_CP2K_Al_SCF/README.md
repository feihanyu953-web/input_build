# C1: Al FCC Bulk Static SCF

**System:** Al FCC bulk (4 atoms)
**Task:** Single-point energy + forces
**Method:** DFT-PBE with GPW, 400 Ry cutoff

## Key Settings

- **Cell:** 4.0495 x 4.0495 x 4.0495 Å, cubic
- **K-points:** Monkhorst-Pack 9x9x9 (bulk metal)
- **Smearing:** Fermi-Dirac @ 300 K with ADDED_MOS 10
- **&KIND:** Al only
- **SCF:** ATOMIC guess, EPS_SCF 1.0E-7

## Files

- `cp2k_scf.inp` — CP2K input file
- `Al_bulk.xyz` — Structure (4 Al atoms, FCC primitive cell)

## Usage

```bash
cp2k.popt -i cp2k_scf.inp -o cp2k_scf.out
```

Requires `BASIS_MOLOPT` and `GTH_POTENTIALS` files in the working directory.
