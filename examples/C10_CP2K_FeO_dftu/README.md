# C10: FeO Rocksalt DFT+U

## System
- **Formula**: FeO (rocksalt)
- **Task**: DFT+U correction on Fe 3d states
- **Method**: DFT-PBE + Hubbard U (Mulliken projection), spin-polarized AFM

## Key Settings
- `PLUS_U_METHOD MULLIKEN` in `&DFT`
- `UKS .TRUE.` — unrestricted (spin-polarized) calculation; without it CP2K
  converges to a restricted non-magnetic solution, which is the wrong ground
  state for antiferromagnetic FeO
- Two Fe kinds with opposite `MAGNETIZATION` initial guesses (AFM-II ordering,
  alternating ferromagnetic (111) planes):
  - `&KIND Fe1` with `MAGNETIZATION 4.0` (spin-up sublattice)
  - `&KIND Fe2` with `MAGNETIZATION -4.0` (spin-down sublattice)
  - Atoms are labeled `Fe1`/`Fe2` in `FeO.xyz` to match
- `&DFT_PLUS_U ON` with `L 2` and `U_MINUS_J [eV] 4.0` on both Fe kinds
- K-points are **version-gated**: CP2K < 2026.2 → omit `&KPOINTS` entirely
  (any `&KPOINTS`, even `SCHEME GAMMA`, aborts with "Method not implemented
  for k-points"; omitting = Gamma point — a small cell implies undersampling,
  use a supercell); CP2K >= 2026.2 → Mulliken DFT+U supports k-points, use a
  converged MP mesh instead
- Fermi-Dirac smearing + `ADDED_MOS 10` for the metallic FeO rocksalt
- 600 Ry cutoff for stable U correction

## Files
- `FeO_dftu.inp` — CP2K input file
- `FeO.xyz` — Structure file (conventional rocksalt cell, Fe labeled Fe1/Fe2)

## Usage
```bash
cp2k.popt -i FeO_dftu.inp -o FeO_dftu.out
```

## Post-processing
Search the output for the DFT+U energy contribution, Fe 3d occupation matrices,
and the converged magnetic moments (expect ~±3.5–4 μB on the two Fe
sublattices for the AFM-II solution).

## Sources
- [CP2K DFT_PLUS_U](https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/SUBSYS/KIND/DFT_PLUS_U.html)
- [CP2K FORCE_EVAL/DFT](https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/DFT.html)
- [CP2K KIND (MAGNETIZATION)](https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/SUBSYS/KIND.html)
- [CP2K changelog (2026.2: DFT+U k-points)](https://manual.cp2k.org/trunk/changelog.html)
