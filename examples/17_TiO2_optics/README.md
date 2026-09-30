# V17: TiO2 Anatase Bulk Optical Properties

## System
- **Formula**: TiO2 anatase
- **Task**: Frequency-dependent dielectric function / optical absorption
- **Method**: DFT-PBE + LOPTICS (random-phase approximation)

## Key Settings
- `LOPTICS = .TRUE.` enables optical dielectric tensor calculation
- `CSHIFT = 0.1` eV (Lorentzian broadening; typical range 0.05–0.3 eV)
- `NEDOS = 2000` for smooth spectra
- `NBANDS` should be increased 2–3x over the default (commented example)
- `ISMEAR = 0`, `SIGMA = 0.05` eV for semiconductor
- Optional Ti 3d DFT+U block included as comments

## Files
| File | Description |
|------|-------------|
| `INCAR` | VASP input for optical properties |
| `POSCAR` | TiO2 anatase structure (user-provided) |
| `KPOINTS` | Dense automatic k-mesh (optics is k-sampling sensitive) |

## Post-processing
```bash
# VASPKIT
vaspkit -task 71

# Or parse OUTCAR manually
python parse_loptics.py OUTCAR
```

## Source
- [VASP Wiki: LOPTICS](https://www.vasp.at/wiki/LOPTICS)
- `examples/13_Si_optics/INCAR`
