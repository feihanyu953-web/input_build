# V18: TiO2 Anatase Bulk Static Dielectric Tensor

## System
- **Formula**: TiO2 anatase
- **Task**: Static dielectric tensor (ion-clamped) via DFPT
- **Method**: DFT-PBE + `LEPSILON = .TRUE.`

## Key Settings
- `LEPSILON = .TRUE.` enables DFPT calculation of the static dielectric matrix
- `ISMEAR = 0`, `SIGMA = 0.05` eV for the semiconductor
- `EDIFF = 1E-8` and `ENCUT = 520` eV for accuracy
- Optional ionic contribution block: `IBRION = 8`, `LPEAD = .TRUE.`
- Optional Ti 3d DFT+U block included as comments

## Files
| File | Description |
|------|-------------|
| `INCAR` | VASP input for static dielectric response |
| `POSCAR` | TiO2 anatase structure (user-provided) |
| `KPOINTS` | Dense automatic k-mesh |

## Usage
```bash
mpirun -np 32 vasp_std
```

## Post-processing
Search `OUTCAR` for:
- `MACROSCOPIC STATIC DIELECTRIC TENSOR` (ion-clamped)
- `BORN EFFECTIVE CHARGES`
- `PIEZOELECTRIC TENSOR`

For ionic contribution with `IBRION=8`, also look for `MACROSCOPIC STATIC DIELECTRIC TENSOR IONIC CONTRIBUTION`.

## Sources
- [VASP Wiki: LEPSILON](https://www.vasp.at/wiki/index.php/LEPSILON)
- [VASP SiC dielectric tutorial](https://www.vasp.at/wiki/index.php/Dielectric_properties_of_SiC)
