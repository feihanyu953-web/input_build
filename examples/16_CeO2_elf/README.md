# V16: CeO2(111) Surface Electron Localization Function (ELF)

## System
- **Formula**: CeO2(111) surface slab
- **Task**: Compute and visualize ELF to inspect Ce-O bond character and surface lone pairs

## Key Settings
- `LELF = .TRUE.` enables output of `ELFCAR`
- `NPAR = 1` is **mandatory** when `LELF = .TRUE.` (VASP Wiki requirement)
- DFT+U on Ce 4f with `LMAXMIX = 6`
- `ENCUT = 520` eV
- `PREC = Accurate` for smooth ELF isosurfaces

## Files
| File | Description |
|------|-------------|
| `INCAR` | VASP input for ELF calculation |
| `POSCAR` | CeO2(111) slab structure (user-provided) |
| `KPOINTS` | Automatic k-mesh (typically 4x4x1 for slab) |

## Post-processing
```bash
# VESTA
vesta ELFCAR

# VMD
vmd ELFCAR
```

## Source
- [VASP Wiki: LELF](https://www.vasp.at/wiki/LELF)
