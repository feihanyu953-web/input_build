# Example 19: CeO2 Bulk DFT+U Test Case

## System
- **Formula**: CeO2 (fluorite structure)
- **Atoms**: 12 (4 Ce, 8 O)
- **Lattice**: Cubic, a = 5.411 Å
- **Space group**: Fm-3m (No. 225)

## Calculation Settings
- **Task**: Geometry optimization (ionic + cell relax) with DFT+U
- **Functional**: PBE + Dudarev DFT+U (LDAUTYPE = 2)
- **Hubbard U**: Ce 4f, U = 5.0 eV; O none
- **k-points**: 6 x 6 x 6 Monkhorst-Pack mesh
- **ENCUT**: 400 eV
- **Smearing**: Gaussian, SIGMA = 0.1 eV

## Files
| File | Description |
|------|-------------|
| `POSCAR` | CeO2 bulk structure (copied from `tests/fixtures/POSCAR_CeO2`) |
| `INCAR` | VASP input with DFT+U parameters |
| `KPOINTS` | Automatic 6x6x6 Monkhorst-Pack mesh |

## DFT+U Parameters
```
LDAU     = .TRUE.
LDAUTYPE = 2
LDAUL    = 3 -1
LDAUU    = 5.0 0.0
LDAUJ    = 0.0 0.0
LMAXMIX  = 6        # Required for f-electron DFT+U
```

## Notes
- Ce 4f electrons are strongly correlated; DFT+U is essential for correct electronic structure.
- `LMAXMIX = 6` is required so that charge-density mixing includes the Ce 4f channel; omitting it gives incorrect U correction and poor SCF convergence.
- `POTIM = 0.2` is used as a conservative CG step width for correlated oxides.
- This is a small bulk cell; `LREAL = .FALSE.` is used for accuracy.
- A self-consistent run (`ISTART=0`, `ICHARG=2`) is performed.
- For surface/adsorbate calculations, also activate `IDIPOL=3` + `LDIPOL=.TRUE.` and consider `ISPIN=2` if Ce³⁺/surface states are present.
