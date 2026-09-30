# C13: H2O Molecule Hirshfeld Charges

## System
- **Formula**: H2O (isolated molecule)
- **Task**: Hirshfeld population analysis
- **Method**: DFT-PBE in a 10 Å box with `PERIODIC NONE`

## Key Settings
- `RUN_TYPE ENERGY`
- `&DFT / &PRINT / &HIRSHFELD ON`
- `SELF_CONSISTENT F` (set T for self-consistent Hirshfeld-I-like variant)
- `SHAPE_FUNCTION DENSITY`（GAUSSIAN 会使 O 电荷到 -1.117 e 且总电荷不守恒；DENSITY 给 O=-0.304 e、H=+0.152 e、总和 0.000 — 2026.1 实测）
- `&POISSON PERIODIC NONE` and `&CELL PERIODIC NONE`

## Files
- `H2O_hirshfeld.inp` — CP2K input file
- `H2O.xyz` — Structure file (user-provided)

## Usage
```bash
cp2k.popt -i H2O_hirshfeld.inp -o H2O_hirshfeld.out
```

## Post-processing
Hirshfeld charges are printed in the output. For Bader charges, use a separate `E_DENSITY_CUBE` print and the external Henkelman bader program.

## Sources
- [CP2K HIRSHFELD](https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/DFT/PRINT/HIRSHFELD.html)
