# Example 02: MoS2 Monolayer — 2D Material with Vacuum

## System
- **Material**: Molybdenum disulfide (MoS2), monolayer
- **Lattice**: Hexagonal (a = 3.19 A, gamma = 120 deg)
- **Atoms**: 3 (1 Mo + 2 S)
- **Type**: 2D material with vacuum along z

## Purpose
Demonstrates the vacuum-axis feature of `kpoints_helper.py` and the automatic Gamma-centered scheme selection for hexagonal lattices. Also shows how the skill handles 2D materials where k-sampling must be reduced along the non-periodic direction.

## Workflow

### Step 1: Structure file (POSCAR)
```
MoS2
 1.0
    3.1900   0.0000   0.0000
   -1.5950   2.7626   0.0000
    0.0000   0.0000  20.0000
 Mo   S
    1    2
Direct
  0.0000  0.0000  0.5000
  0.3333  0.6667  0.5794
  0.6667  0.3333  0.4206
```

### Step 2: Generate KPOINTS
```bash
python scripts/kpoints_helper.py --poscar POSCAR --spacing 0.20 --scheme AUTO --vacuum-axis z
```

**Output**: `12 12 1` Gamma-centered mesh

- Hexagonal lattice triggers automatic Gamma-centered selection
- `--vacuum-axis z` forces k3 = 1 (only Gamma point along vacuum direction)

### Step 3: Generated input files

#### INCAR (from `vasp_scf.incar` + minor adjustments)
For 2D semiconductors, typical adjustments include:
- `ISMEAR = 0, SIGMA = 0.05` (smaller smearing for gapped systems)
- Consider `IVDW = 11` (DFT-D3) if interlayer interactions matter
- `LREAL = .FALSE.` (small cell)

#### KPOINTS
```
Automatic mesh
0
Gamma
12 12 1
0.0 0.0 0.0
```

### Step 4: Submit calculation
Copy POTCAR (Mo, S) and run VASP.

## Validation checklist
- [ ] SCF converges (semiconductors may need more steps than metals)
- [ ] Bandgap opens (~1.8 eV for monolayer MoS2 at PBE level)
- [ ] No spurious interactions between periodic images (vacuum >= 15 A)

## Key skill features demonstrated
| Feature | How it's used |
|---------|--------------|
| Lattice auto-detection | Hexagonal recognized from a=b, gamma=120 |
| Gamma auto-selection | Hexagonal → always Gamma-centered |
| Vacuum axis | `--vacuum-axis z` sets k3 = 1 |

## Files in this directory
| File | Description |
|------|-------------|
| `README.md` | This file |
| `POSCAR` | MoS2 monolayer structure |
| `INCAR` | Generated static SCF input |
| `KPOINTS` | Generated 12x12x1 Gamma mesh |
