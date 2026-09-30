# C12: Si Bulk ELF

## System
- **Formula**: Si (diamond cubic)
- **Task**: Electron localization function (ELF) cube
- **Method**: DFT-PBE static SCF with `&ELF_CUBE` print

## Key Settings
- `RUN_TYPE ENERGY`
- `&DFT / &PRINT / &ELF_CUBE ON` with `STRIDE 2 2 2`
- 4×4×4 Monkhorst-Pack k-grid
- 600 Ry cutoff for smooth ELF isosurfaces

## Files
- `Si_elf.inp` — CP2K input file
- `Si_bulk.xyz` — Structure file (user-provided)

## Usage
```bash
cp2k.popt -i Si_elf.inp -o Si_elf.out
```

## Post-processing
Visualize the ELF cube with VMD, VESTA, or ovito. Common isosurfaces: 0.85 (bonds/lone pairs), 0.5 (electron-gas-like), 0.0 (delocalized).

## Sources
- [CP2K ELF_CUBE](https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/DFT/PRINT/ELF_CUBE.html)
