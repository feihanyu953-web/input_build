# C11: Si Bulk Static Polarizability

## System
- **Formula**: Si (diamond cubic)
- **Task**: Static electric-dipole polarizability / dielectric response
- **Method**: DFPT linear response (LINRES/POLAR) with PBE, **Gamma-only OT**

## Key Settings
- `RUN_TYPE LINEAR_RESPONSE`
- `&FORCE_EVAL / &PROPERTIES / &LINRES / &POLAR` with `DO_RAMAN T`
- OT solver (`&OT`) recommended for linear-response calculations
- **No k-point mesh** — this is intentional:
  - `&OT` is Gamma-only (unsupported with k-points);
  - `&LINRES`/DFPT response is incompatible with k-points.
  The two CP2K optics routes are mutually exclusive:
  - **Route A (this example)**: Gamma-only + OT + LINRES/POLAR; for bulk
    crystals converge the supercell size instead of a k-mesh. A Gamma-only
    conventional Si cell under-samples the Brillouin zone — treat this
    example as a workflow demonstration, not converged physics.
  - **Route B**: k-point SCF with `&DIAGONALIZATION` (no OT, no LINRES);
    k-point optical spectra then require a different method (outside CP2K's
    DFPT route).
- 600 Ry cutoff

## Files
- `Si_optics.inp` — CP2K input file
- `Si_bulk.xyz` — Structure file (user-provided)

## Usage
```bash
cp2k.popt -i Si_optics.inp -o Si_optics.out
```

## Post-processing
The static polarizability tensor is printed in the output. Derive the ion-clamped dielectric constant from α and the unit-cell volume. Frequency-dependent absorption requires LR-TDDFT or real-time propagation.

## Sources
- [CP2K POLAR](https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/PROPERTIES/LINRES/POLAR.html)
- [CP2K LINRES](https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/PROPERTIES/TDDFPT/LINRES.html)
- [CP2K k-points compatibility](https://manual.cp2k.org/trunk/methods/dft/k-points.html)
