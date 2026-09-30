# Example 01: Al FCC Bulk — VASP Static SCF

## System
- **Material**: Aluminum (Al), face-centered cubic (FCC)
- **Lattice constant**: 4.0495 A
- **Atoms**: 4
- **Type**: 3D bulk metal

## Purpose
This is the simplest and most common use case: a single-point energy calculation on a metallic bulk system. It demonstrates the default `vasp_scf.incar` template with no modifiers applied.

## Workflow

### Step 1: Structure file (POSCAR)
```
Al
 1.0
    4.0495  0.0000  0.0000
    0.0000  4.0495  0.0000
    0.0000  0.0000  4.0495
 Al
   4
Cartesian
  0.0000  0.0000  0.0000
  2.0248  2.0248  0.0000
  2.0248  0.0000  2.0248
  0.0000  2.0248  2.0248
```

### Step 2: Generate KPOINTS
```bash
python scripts/kpoints_helper.py --poscar POSCAR --spacing 0.18 --scheme AUTO
```

**Output**: `9 9 9` Monkhorst-Pack mesh (auto-selected for cubic metal)

### Step 3: Generated input files

#### INCAR (from `vasp_scf.incar`)
- `ENCUT = 400` (safe for Al, ENMAX is low)
- `ISMEAR = 0, SIGMA = 0.1` (Gaussian smearing for metal)
- `ISPIN = 1` (Al is non-magnetic)
- `LREAL = .FALSE.` (small cell, reciprocal-space is accurate)
- `LWAVE = .TRUE., LCHARG = .TRUE.` (save for restart / DOS)

#### KPOINTS
```
Automatic mesh
0
Monkhorst-Pack
9 9 9
0.0 0.0 0.0
```

### Step 4: Submit calculation
Copy POTCAR (Al) to working directory and run VASP.

## Validation checklist
- [ ] SCF converges in < 20 steps (metals converge quickly with smearing)
- [ ] Final energy per atom ≈ -3.75 eV (Al bulk reference)
- [ ] No warnings in OUTCAR about insufficient ENCUT

## Files in this directory
| File | Description |
|------|-------------|
| `README.md` | This file |
| `POSCAR` | Al FCC structure |
| `INCAR` | Generated static SCF input |
| `KPOINTS` | Generated 9x9x9 MP mesh |
