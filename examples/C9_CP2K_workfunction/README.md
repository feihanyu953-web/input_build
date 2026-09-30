# C9: Au(111) Slab Work Function

## System
- **Formula**: Au(111) surface slab
- **Task**: Compute work function from planar-averaged Hartree potential
- **Method**: DFT-PBE with GPW, 600 Ry cutoff

## Key Settings
- `RUN_TYPE ENERGY` for static SCF
- `&PRINT / &V_HARTREE_CUBE ON` (2026.1-safe route): Hartree potential cube,
  plane-averaged externally over the xy planes
- Version gate: `&PLANAR_AVERAGED_V_HARTREE` exists only in CP2K >= 2026.2-dev
  (2026.1 aborts with "unknown subsection"; runtime-verified) — it is kept in
  the input as a commented-out alternative with `PARALLEL_PLANE XY` because
  the surface normal is along z
- Fermi-Dirac smearing + `ADDED_MOS 100` for metal
- Monkhorst-Pack 4x4x1 k-grid for slab

## Files
- `cp2k_workfunction.inp` — CP2K input file
- `Au111_slab.xyz` — Slab structure (user-provided)

## Usage
```bash
cp2k.popt -i cp2k_workfunction.inp -o cp2k_workfunction.out
```

## Post-processing
1. Read the `*-v_hartree-1_0.cube` file and average over the xy planes to get
   V(z) in Hartree (numpy / cp2kdata / CPACR-macroavg).
2. Find the flat plateau in the vacuum region (`V_vac`, in Hartree).
3. Read the Fermi energy from the output (`E_Fermi`, in Hartree).
4. Convert: `Phi = (V_vac - E_Fermi) * 27.211386 eV`.

## Source
- [CP2K V_HARTREE_CUBE](https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/DFT/PRINT/V_HARTREE_CUBE.html) (2026.1-safe)
- [CP2K PLANAR_AVERAGED_V_HARTREE](https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/DFT/PLANAR_AVERAGED_V_HARTREE.html) (requires CP2K >= 2026.2-dev)
