# C7: TiO2 Anatase Bulk PDOS

## System
- **Formula**: TiO2 anatase
- **Task**: Projected density of states (PDOS)
- **Method**: DFT-PBE with GPW, 600 Ry cutoff

## Key Settings
- `RUN_TYPE ENERGY` for static SCF
- `&PRINT / &PDOS` with `NLUMO -1` and `COMPONENTS`
- `ADDED_MOS 100` to provide unoccupied states
- Monkhorst-Pack 4x4x4 k-grid
- `&KIND` blocks for Ti and O

## Files
- `cp2k_dos.inp` — CP2K input file
- `TiO2_anatase.xyz` — Structure file (user-provided)

## Usage
```bash
cp2k.popt -i cp2k_dos.inp -o cp2k_dos.out
```

## Post-processing
PDOS files are written per element/kind. Use `cp2kdata` or custom scripts to sum and plot.

## Sources
- [CP2K DOS manual](https://manual.cp2k.org/trunk/methods/electronic_structure/dos.html)
- [CP2K PDOS tutorial](https://www.cp2k.org/exercises:common:pdos)
