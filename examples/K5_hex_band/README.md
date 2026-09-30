# K5: Hexagonal Band Path — symprec Tolerance-Sensitivity Regression

## Test Purpose

This example is **not** a golden PASS example. It is a regression case for
**symprec-sensitive Bravais classification** (audit P0-03): the same POSCAR
is classified differently depending on the symmetry tolerance, and silently
picking either classification can produce the **wrong band path**.

The POSCAR (`examples/02_MoS2_monolayer/POSCAR`, MoS2 monolayer in a hexagonal
cell) is slightly distorted from the ideal hexagonal lattice
(b = 2.7626310 Å vs ideal a·sin60° = 2.7626164 Å, off by ~1.5e-5 Å):

| symprec | seekpath classification | Bravais lattice |
|---------|------------------------|-----------------|
| 1e-5 (default) | C2/m, No. 12 | **mC (monoclinic)** |
| 1e-4 | P-3m1, No. 164 | **hP (hexagonal)** |
| 1e-3 | P-3m1, No. 164 | hP (stable) |

Before the P0-03 fix, the helper used the seekpath default `symprec=1e-5`,
had no tolerance control, and **silently wrote a monoclinic (mC) path** for
this "hexagonal" example. The old output is exactly the kind of wrong
k-points the skill must refuse to produce.

## Expected Behavior (post-fix)

### 1. Default symprec → refuse (fail closed)

```bash
python scripts/kpoints_helper.py \
    --poscar examples/02_MoS2_monolayer/POSCAR \
    --band-structure --npoints 20 \
    -o examples/K5_hex_band/KPOINTS
```

The helper probes the classification at `symprec` and `symprec ×10`; they
disagree here (mC vs hP), so it **exits non-zero and writes no file**:

```
[ERROR] Bravais classification of this POSCAR is SENSITIVE to symprec:
          symprec 1e-05 -> SG 12 (C2/m), Bravais mC
          symprec 0.0001 -> SG 164 (P-3m1), Bravais hP
        The high-symmetry path depends on the space group; picking either
        classification silently could give the WRONG path. No KPOINTS
        file was written.
        Re-run with a --symprec at which the classification is stable ...
```

### 2. Explicit stable symprec → hexagonal hP path

```bash
python scripts/kpoints_helper.py \
    --poscar examples/02_MoS2_monolayer/POSCAR \
    --band-structure --npoints 20 \
    --symprec 1e-4 --lattice hexagonal \
    -o examples/K5_hex_band/KPOINTS
```

At `--symprec 1e-4` the classification is stable (probe at 1e-3 agrees:
P-3m1/hP), and `--lattice hexagonal` matches the identified family, so the
helper writes the correct **hexagonal** path Γ-M-K-Γ-A-L-H-A|L-M|H-K:

```
[OK] Wrote seekpath KPOINTS to examples/K5_hex_band/KPOINTS
      Space group: 164 (P-3m1)
      Bravais lattice: hP
      symprec: 0.0001 (stability probed at 0.001)
      Coordinate basis: reciprocal of the original input cell
```

The checked-in `KPOINTS` is this hP reference output. If the user declares a
conflicting family (e.g. `--lattice monoclinic`), the helper also exits
non-zero without writing.

## Regression Coverage

`tests/test_audit_kpoints.py` asserts both behaviors in-process and via CLI:
default symprec must raise/exit non-zero with no file written (never a
silent mC path), and `--symprec 1e-4` must write the hP path.

## Result

PASS — the helper fails closed at the default symprec and only writes the
physically correct hexagonal path when given an explicit, stable tolerance.
