# K8: Dependency Handling — No Auto-Install, Explicit `--bootstrap-deps`

## Test Purpose

Verify the dependency policy of `kpoints_helper.py` (audit P1-KPOINTS-04):

1. **Import and normal runs NEVER auto-install.** Missing dependencies only
   produce an error report with install instructions (non-zero exit). The
   import path never touches the network or modifies the Python environment.
2. Installing happens only via the **explicit** opt-in command
   `python scripts/kpoints_helper.py --bootstrap-deps`, which installs
   **pinned, tested versions** (`ase==3.29.0`, `spglib==2.7.0`,
   `seekpath==2.2.1`) with visible installer output.

## Expected Behavior

### Missing dependencies → error report, no install

```
[ERROR] Missing Python dependencies: ase, spglib, seekpath
[ERROR] kpoints_helper.py requires: ase, spglib, seekpath (>= 2.0)
[ERROR] This script does NOT auto-install on import. Install with:
    python scripts/kpoints_helper.py --bootstrap-deps   # pinned, tested versions
    # or choose versions yourself:
    uv pip install ase spglib seekpath
    pip install ase spglib seekpath
```

(exit code 1; nothing is installed). This is covered by
`tests/test_audit_kpoints.py`, which mocks a missing dependency and asserts
the module reports it, exits non-zero, and never calls `pip`/`uv`.

### Explicit bootstrap → pinned install

```bash
python scripts/kpoints_helper.py --bootstrap-deps
```

- If any dependency is missing: installs the pinned versions (tries
  `uv pip install`, falls back to `pip install`), re-verifies the imports,
  then exits. Installer output is **not** suppressed, so the user can audit
  exactly what enters the environment.
- If everything is already importable: no-op (see Actual Output below).

## Manual Validation Procedure (clean environment)

1. Create a throwaway virtual environment **outside the skill directory**
   (never inside `examples/` — a leftover venv is ~300 MB and pollutes
   file searches; delete it after validation):
   ```powershell
   uv venv --seed "$env:TEMP\k8_test_venv"   # --seed includes pip (fallback installer)
   ```
2. Run the script with the venv's Python (from the skill directory):
   ```powershell
   & "$env:TEMP\k8_test_venv\Scripts\python.exe" scripts/kpoints_helper.py `
       --poscar examples/01_Al_FCC_bulk/POSCAR -o "$env:TEMP\KPOINTS"
   ```
   Expect the error report above and exit code 1 — **without** any install.
3. Then bootstrap explicitly and re-run:
   ```powershell
   & "$env:TEMP\k8_test_venv\Scripts\python.exe" scripts/kpoints_helper.py --bootstrap-deps
   & "$env:TEMP\k8_test_venv\Scripts\python.exe" scripts/kpoints_helper.py `
       --poscar examples/01_Al_FCC_bulk/POSCAR --spacing 0.20 --scheme AUTO `
       -o examples/K8_auto_install/KPOINTS
   ```
4. Delete the venv after validation:
   ```powershell
   Remove-Item -Recurse -Force "$env:TEMP\k8_test_venv"
   ```

## Actual Output (2026-07-19, post P1-KPOINTS-04 fix)

`--bootstrap-deps` in an environment where the dependencies are already
importable:

```
[OK] All dependencies already importable (ase, spglib, seekpath) — nothing to install.
```

Mesh generation itself is unchanged; the checked-in `KPOINTS` remains the
Gamma-centered 8x8x8 mesh for Al FCC (k-spacing 0.20 Å⁻¹, spglib F centering
→ Gamma per VASP wiki recommendation for fcc):

```
Automatic mesh
0
Gamma
8 8 8
0.0 0.0 0.0
```

## Result

PASS — import-time auto-install is removed; missing dependencies fail with a
clear report, and installation only happens through the explicit pinned
`--bootstrap-deps` command.

## Notes

- On Windows, seed the venv with `pip` (uv `--seed`, or `python -m venv`)
  so the fallback installer path works.
- The test venv must be deleted after validation (see step 4). Do **not**
  create it inside `examples/` — an in-tree `test_venv` (~300 MB, ~19k
  files) was removed on 2026-07-18 for this reason.
