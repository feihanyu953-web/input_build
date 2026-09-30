# C4: Si Diamond Bulk Band Structure

**System:** Si diamond bulk (2 atoms, conventional cell)
**Task:** Band structure calculation
**Method:** DFT-PBE with GPW, 600 Ry cutoff

## Key Settings

- **Cell:** 5.431 x 5.431 x 5.431 Å, cubic
- **Periodicity:** XYZ
- **&KIND:** Si only
- **K-points SCF:** Monkhorst-Pack 4x4x4
- **Band path:** Γ → X → W → K → Γ → L → U → W → L → K
  (Si diamond, Fd-3m space group 227)
- **CUTOFF:** 600 Ry (higher for smooth bands)
- **ADDED_MOS:** 10 (extra empty bands)

## Files

- `cp2k_band.inp` — CP2K input file
- `Si_bulk.xyz` — Structure (2 Si atoms, diamond primitive cell)

## Usage

```bash
cp2k.popt -i cp2k_band.inp -o cp2k_band.out
```

Post-processing:
```bash
cp2k_bs2csv.py C4_CP2K_Si_band.bs > band.csv
```

Requires `BASIS_MOLOPT` and `GTH_POTENTIALS` files in the working directory.
