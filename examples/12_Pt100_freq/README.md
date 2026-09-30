## V12: Pt(100)-NH3 — Vibrational Frequency

**Task:** Finite-difference vibrational frequency calculation on a large slab.

**System:** Pt(100) 3x3 slab + NH3 + explicit water + NaOH (109 atoms total). Slab with ~18 Å vacuum.

**Key settings:**
- `IBRION = 5`, `NSW = 1`, `NFREE = 2`, `POTIM = 0.015` Å
- `ISYM = 0` (symmetry disabled for explicit displacements)
- `LREAL = .FALSE.` (reciprocal-space projection for accurate forces)
- `ISPIN = 1`, `ISMEAR = 0`, `SIGMA = 0.1`
- K-mesh: 4x4x1 Gamma-centered (spacing ~0.25 Å⁻¹; z = 1 due to vacuum)

**Note:** `IBRION = 5/6` requires `NSW > 0` — VASP performs one ionic step in which the
finite-difference Hessian is built; without it the run degenerates to a static SCF and
no frequencies are computed (vasp.at/wiki/IBRION). `NFREE = 2` controls the number of
displacements per direction (central differences), not the step count. For adsorbate
low-frequency modes, keep `EDIFF = 1E-6` (or tighter) and check the output for
acoustic/spurious imaginary modes.

**Files:** `INCAR`, `KPOINTS`, `POSCAR` (POTCAR required)
