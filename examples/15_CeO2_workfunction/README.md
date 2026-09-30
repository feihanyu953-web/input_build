# V15: CeO2(111) Surface Work Function

## System
- **Formula**: CeO2(111) surface slab
- **Surface termination**: CeO2-terminated (or O-terminated, user choice)
- **Task**: Extract work function from planar-averaged electrostatic potential

## Key Settings
- `LVHAR = .TRUE.` (VASP 6+ recommended) outputs ionic + Hartree potential to `LOCPOT`
- `IDIPOL = 3` + `LDIPOL = .TRUE.` to flatten vacuum potential plateau
- DFT+U on Ce 4f: `LDAUL = 3 -1`, `LDAUU = 5.0 0.0`, `LMAXMIX = 6`
- `ENCUT = 520` eV for publication-quality O-containing oxide
- `ISMEAR = 0`, `SIGMA = 0.05` eV for oxide

## Files
| File | Description |
|------|-------------|
| `INCAR` | VASP input for work function extraction |
| `POSCAR` | CeO2(111) slab structure (user-provided) |
| `KPOINTS` | Automatic k-mesh (typically 4x4x1 for slab) |

## Post-processing
```bash
# Option 1: VASPKIT
vaspkit -task 426

# Option 2: Manual plane average of LOCPOT along z
python average_locpot.py LOCPOT
```

## Source
- [VASP Wiki: LVHAR](https://www.vasp.at/wiki/LVHAR)
