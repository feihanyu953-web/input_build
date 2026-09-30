# C8: Si Bulk Phonon Calculation via Phonopy

## System
- **Formula**: Si diamond cubic
- **Task**: Phonon band structure / density of states
- **Method**: CP2K force calculations + Phonopy post-processing

## Key Settings
- `RUN_TYPE ENERGY_FORCE` — Phonopy needs forces on displaced supercells
- `&PRINT / &FORCES ON` — required output
- 600 Ry cutoff, tight `EPS_SCF = 1.0E-7`
- Fermi-Dirac smearing + `ADDED_MOS 100` for Si (semimetal/small gap)
- Monkhorst-Pack 4x4x4 k-grid for the primitive cell

## Files
- `cp2k_phonon.inp` — CP2K force-calculation input
- `Si_bulk.xyz` — Primitive cell structure (user-provided)

## Workflow
```bash
# 1. Generate displaced supercells
phonopy --cp2k -c cp2k_phonon.inp -d --dim="2 2 2"

# 2. Run CP2K on each displaced supercell
mpirun -np 16 cp2k.popt supercell-001.inp
mpirun -np 16 cp2k.popt supercell-002.inp
...

# 3. Collect forces
phonopy --cp2k -f supercell-001-forces-1_0.xyz supercell-002-forces-1_0.xyz ...

# 4. Plot phonon band structure
phonopy --cp2k -c cp2k_phonon.inp -p --dim="2 2 2" \
        --band="0.0 0.0 0.0  0.5 0.0 0.5  0.375 0.375 0.0  0.0 0.0 0.0"
```

## Sources
- [Phonopy CP2K interface](https://phonopy.github.io/phonopy/cp2k.html)
- [CP2K phonon tutorial](https://www.cp2k.org/exercises:2018_uzh_cmest:phonon_calculation)
