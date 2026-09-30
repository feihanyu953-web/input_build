# Example 04: Al FCC Band Structure — Non-SCF with High-Symmetry k-Path

## System
- **Material**: Aluminum (Al), face-centered cubic (FCC)
- **Lattice constant**: 4.0495 A
- **Atoms**: 4
- **Type**: 3D bulk metal

## Purpose
Demonstrates the full band-structure workflow: (1) converged SCF, (2) seekpath-generated high-symmetry k-path, (3) non-SCF band calculation using `vasp_band.incar`.

## Workflow

### Step 1: Run converged SCF
Use Example 01 (Al FCC SCF) to obtain `CHGCAR` and `WAVECAR`.

### Step 2: Generate band-structure KPOINTS
```bash
python scripts/kpoints_helper.py --poscar POSCAR --band-structure --npoints 20
```

**Output**: Line-mode KPOINTS with FCC high-symmetry path

```
Band structure (seekpath)
20
Line-mode
rec
0.000000 0.000000 0.000000 GAMMA
0.500000 0.000000 0.500000 X
...
```

**Path**: Gamma -> X -> U -> K -> Gamma -> L -> W -> X
**Space group**: 225 (Fm-3m)

### Step 3: Select template
**Base template**: `vasp_band.incar`

Key settings:
- `ISTART = 1, ICHARG = 11` (non-SCF from prior CHGCAR)
- `PREC = Accurate` (smooth bands)
- `SIGMA = 0.05` (sharp band edges)
- `LORBIT = 11` (lm-decomposed DOS for fat bands)
- `ISYM = 0` (symmetry disabled for k-path)

### Step 4: Generated input files

#### INCAR
```
SYSTEM   = Al FCC Band Structure
PREC     = Accurate
ENCUT    = 400

ALGO     = Normal
EDIFF    = 1E-6
ISMEAR   = 0
SIGMA    = 0.05
ISTART   = 1
ICHARG   = 11
NELM     = 100

LORBIT   = 11
ISYM     = 0

NBANDS   = 384    # Optional: boost by ~30% for empty states

ADDGRID  = .TRUE.
LASPH    = .TRUE.

LCHARG   = .FALSE.
LWAVE    = .FALSE.
```

#### KPOINTS (line-mode)
```
Band structure (seekpath)
20
Line-mode
rec
0.000000 0.000000 0.000000 GAMMA
0.500000 0.000000 0.500000 X
...
```

### Step 5: Submit calculation
Copy `CHGCAR` and `WAVECAR` from Step 1, then run VASP.

### Step 6: Post-processing
Extract eigenvalues from `EIGENVAL` or use `pymatgen`/`sumo` to plot:
```bash
sumo-bandplot
```

## Validation checklist
- [ ] Non-SCF converges in < 10 steps (one step is often enough)
- [ ] Band energies are smooth along k-path (no discontinuities)
- [ ] Fermi level crosses bands (Al is metallic)
- [ ] Band width matches literature (~12 eV for Al sp band)

## Key skill features demonstrated
| Feature | How it's used |
|---------|--------------|
| seekpath integration | Auto-generates space-group-aware k-path |
| Non-SCF template | `vasp_band.incar` with `ICHARG = 11` |
| Empty states | `NBANDS` boost for band visualization |
| lm-decomposition | `LORBIT = 11` for orbital character |

## Files in this directory
| File | Description |
|------|-------------|
| `README.md` | This file |
| `POSCAR` | Al FCC structure (same as Example 01) |
| `INCAR` | Generated band-structure input |
| `KPOINTS` | Generated seekpath line-mode k-path |
