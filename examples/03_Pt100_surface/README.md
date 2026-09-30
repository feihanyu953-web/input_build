# Example 03: Pt(100) Surface — Catalytic Surface with Dipole Correction

## System
- **Material**: Pt(100) 3x3 surface with explicit water + electrolyte
- **Surface**: 3-layer Pt slab, 3x3 supercell
- **Solvation**: 25 H2O + Na+ + OH- + NH3 (electrochemical interface)
- **Type**: Catalytic surface slab with large vacuum

## Purpose
Demonstrates a realistic electrocatalysis workflow: geometry optimization of a solvated metal surface with dipole correction applied. This is the most complex VASP example, showing modifier application (`dipole.patch`) and practical parameter choices for large surface systems.

## Workflow

### Step 1: Structure file (POSCAR)
Pt(100) 3x3 slab with explicit water and ions. See `POSCAR` for full coordinates.

Cell dimensions: a = b = 8.32 A, c = 53.92 A (large vacuum region)

### Step 2: Generate KPOINTS
```bash
python scripts/kpoints_helper.py --poscar POSCAR --spacing 0.20 --scheme AUTO --vacuum-axis z
```

**Output**: `4 4 1` Gamma-centered mesh

- Tetragonal cell (a = b != c) with vacuum → auto Gamma
- `--vacuum-axis z` ensures k3 = 1

### Step 3: Select template and modifiers

**Base template**: `vasp_relax.incar` (geometry optimization)

**Modifier applied**: `dipole.patch`
```
# Dipole correction for asymmetric slab
LDIPOL   = .TRUE.
IDIPOL   = 3              # Correct dipole along z (vacuum axis)
DIPOL    = 0.5 0.5 0.25   # Center of slab in fractional coords
```

**Manual adjustments for this system**:
- `ENCUT = 400` (Pt has high ENMAX; 400 eV is standard trade-off)
- `ISYM = 0` (asymmetric adsorption breaks symmetry)
- `ISMEAR = 0, SIGMA = 0.1` (Gaussian for metal + solvent mixture)
- `LREAL = Auto` (109 atoms → real-space projection saves time)
- `NSW = 200` (solvated interfaces relax slowly)

### Step 4: Generated input files

#### INCAR
```
SYSTEM   = Pt100_3x3_Ammonia_OER_Interface
PREC     = Normal
ENCUT    = 400

ALGO     = Normal
EDIFF    = 1E-6
ISMEAR   = 0
SIGMA    = 0.1
NELMIN   = 6
NELM     = 100

IBRION   = 2
ISIF     = 2
NSW      = 200
EDIFFG   = -0.03
POTIM    = 0.3

ADDGRID  = .TRUE.
LASPH    = .TRUE.
LREAL    = Auto
ISYM     = 0

# Dipole correction (asymmetric slab: NH3 on one side)
LDIPOL   = .TRUE.
IDIPOL   = 3
DIPOL    = 0.5 0.5 0.25

# NCORE  = 4
# NPAR   = 4
# KPAR   = 1
```

#### KPOINTS
```
Automatic mesh
0
Gamma
4 4 1
0.0 0.0 0.0
```

### Step 5: Submit calculation
Copy POTCAR (Pt, O, H, Na, N) and run VASP.

## Validation checklist
- [ ] First ionic step: max force < 5 eV/A (bad contacts are OK if they reduce)
- [ ] After 50 steps: max force < 1 eV/A
- [ ] Final: max force < 0.03 eV/A (EDIFFG target)
- [ ] Pt-Pt bond lengths ~ 2.77 A (bulk Pt = 2.775 A)
- [ ] No water molecules dissociated unexpectedly
- [ ] Dipole correction energy < 0.1 eV (if > 0.5 eV, recheck IDIPOL)

## Key skill features demonstrated
| Feature | How it's used |
|---------|--------------|
| Template selection | `vasp_relax.incar` for geometry optimization |
| Modifier | `dipole.patch` for asymmetric slab |
| Vacuum handling | `--vacuum-axis z` in kpoints_helper |
| Large system | `LREAL = Auto` for 100+ atoms |
| Symmetry | `ISYM = 0` for broken symmetry |

## Files in this directory
| File | Description |
|------|-------------|
| `README.md` | This file |
| `POSCAR` | Pt(100) 3x3 + solvation structure |
| `INCAR` | Generated relaxation input with dipole correction |
| `KPOINTS` | Generated 4x4x1 Gamma mesh |
