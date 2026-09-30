# Pressure Test: CeO₂(100) Surface + N₂ + COOH with DFT+U

## Purpose

This example is a **regression / pressure test** for the oxide/DFT+U branch of `input_build`. It mirrors the case that exposed the original skill缺陷:

- `ENCUT=400` was treated as sufficient for an O-containing oxide.
- `LMAXMIX` was missing even though Ce 4f DFT+U was active.
- `POTIM=0.5` was used for a complex surface adsorbate CG relaxation.
- `NELM=60` was too low for a DFT+U oxide surface.

After the skill fix, `input_build` should generate an INCAR that passes the validation rules in `SKILL.md` for this system.

## System

- **Surface**: CeO₂(100) 3×3 slab
- **Adsorbates**: N₂ + COOH
- **Atoms**: ~85 (Ce, O, N, C, H)
- **DFT+U**: Ce 4f, U = 5.0 eV
- **Dispersion**: D3BJ (`IVDW = 12`)

## Expected Auto-Detection

| Property | Expected Inference |
|---|---|
| Material class | `oxide_surface` |
| Magnetic | Ask user (Ce³⁺/surface states possible); default `ISPIN=1` unless user opts in |
| Dipole correction | Yes (`IDIPOL=3`, `LDIPOL=.TRUE.`) |
| DFT+U | Yes, Ce 4f |
| `LMAXMIX` | **6** (because `LDAUL` contains 3) |
| `POTIM` | **0.2** (complex oxide surface with adsorbates) |
| `NELM` | **100** (DFT+U surface) |
| `SIGMA` | **0.05** (oxide/semiconductor) |
| `ENCUT` | **400** with annotation to use 520+ for final energies |

## Critical Checks

When `input_build` is asked to generate a relax INCAR for this system, verify that the output:

1. ✅ Contains `LMAXMIX = 6`
2. ✅ Contains `POTIM = 0.2`
3. ✅ Contains `NELM = 100`
4. ✅ Contains `SIGMA = 0.05` (not 0.1)
5. ✅ Contains `LASPH = .TRUE.` and `ADDGRID = .TRUE.`
6. ✅ Contains `IDIPOL = 3` and `LDIPOL = .TRUE.`
7. ✅ Contains `IVDW = 12` (D3BJ; `IVDW = 11` is D3 zero-damping)
8. ✅ Warns/annotates that `ENCUT = 400` is a minimum and 520+ is recommended for O-containing systems
9. ✅ Does **not** contain `POTIM = 0.5`
10. ✅ Does **not** contain `NELM = 60`

## Files

| File | Description |
|---|---|
| `INCAR` | Expected post-fix VASP input for this system |
| `README.md` | This file |

## Note

This directory does **not** include a `POSCAR`; it documents the expected output from `input_build` when given the user's CeO₂(100) + N₂ + COOH structure.
