# K7: Explicit Gamma-Centered Scheme (Al FCC)

## Test Purpose
Verify that `kpoints_helper.py` respects an explicitly requested
**Gamma-centered** scheme and does not override it with auto-selection.

## Command
```bash
python scripts/kpoints_helper.py \
    --poscar examples/01_Al_FCC_bulk/POSCAR \
    --spacing 0.18 --scheme Gamma \
    -o examples/K7_explicit_Gamma/KPOINTS
```

## Expected Behavior
- Explicitly Gamma-centered mesh (not auto-selected)
- Mesh size: 9x9x9

## Actual Output
```
[INFO] Lattice type: cubic
       a=4.0495, b=4.0495, c=4.0495 A
       alpha=90.00, beta=90.00, gamma=90.00 deg
       |b1|=1.5516, |b2|=1.5516, |b3|=1.5516 A^-1
[OK] Wrote Gamma-centered 9x9x9 mesh to ...\K7_explicit_Gamma\KPOINTS
       k-spacing ~ 0.180 A^-1 -> mesh 9x9x9
```

## Generated KPOINTS
```
Automatic mesh
0
Gamma
9 9 9
0.0 0.0 0.0
```

## Result
PASS. The script correctly used the explicitly requested Gamma scheme with a 9x9x9 mesh.
