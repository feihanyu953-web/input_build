# CP2K Workflow (input-build reference)

> Read this when generating CP2K input files. Routing and hard rules live in ../SKILL.md.

## CP2K Workflow

CP2K uses a **hierarchical section-based input format** (`&SECTION ... &END SECTION`) rather than key-value pairs. AI follows the same auto-detect-first principle.

### Step 1: Read Structure

Parse the coordinate file (XYZ, PDB, or CP2K &CELL/&COORD) for: elements, cell dimensions, periodicity.

For PDB input, CP2K defaults `TOPOLOGY/USE_ELEMENT_AS_KIND` to `FALSE`: the
PDB atom name is the KIND label. Only when it is explicitly `TRUE` should the
element column be used. Do not collapse atom names such as `CA` to element `C`.

### Step 2: Infer & Classify

| Property | Detection Method | Implication |
|----------|-----------------|-------------|
| **Elements** | Parse coord file / XYZ | Determines `&KIND` blocks + basis set / potential |
| **Periodicity** | Cell definition / user intent | Atomic config block, see table below: `&CELL PERIODIC` + `&POISSON PERIODIC` + `POISSON_SOLVER` must be set together |
| **System size** | Atom count | > 200 atoms → consider GPW-GAPW hybrid or MACE/LAMMPS instead |
| **Has H** | Element list | TIMESTEP ≤ 0.5 fs in MD |
| **Metal vs insulator** | Element identity | Metal → add `&SMEAR` + `ADDED_MOS` (keyword of `&SCF`, NOT a section) |

### Periodicity / Poisson solver — one atomic config block

`PERIODIC NONE` or `XY` without a compatible `POISSON_SOLVER` is a common
fatal misconfiguration: the default solver is `PERIODIC`, which is only valid
for fully 3D-periodic systems. Always generate the four settings together
(source: CP2K manual FORCE_EVAL/DFT/POISSON):

| Dimension | `&CELL PERIODIC` | `&POISSON PERIODIC` | `POISSON_SOLVER` | Notes |
|-----------|------------------|---------------------|------------------|-------|
| 3D bulk | `XYZ` | `XYZ` | `PERIODIC` (default) | — |
| 2D slab / surface | `XYZ` (keep) | `XY` | `ANALYTIC` | Decouples periodic images along the normal. Alternative: keep `POISSON PERIODIC XYZ` + large vacuum = 3D-periodic approximation of the slab (images interact; converge vacuum). |
| 0D molecule / cluster | `NONE` | `NONE` | `ANALYTIC` (or `MT` / `WAVELET`) | Box must be large enough that the density decays to ~0 at the edges (WAVELET only needs the molecule + a margin). |
| 1D wire | `X` (wire axis) | `X` (wire axis) | `ANALYTIC` | One periodic direction only; `MT` / `WAVELET` do NOT support 1D. Dimension-first routing incl. CELL sizing: see the decision tree below. |

### Dimension Routing Decision Tree（维度路由决策树）

Dimension is a routing decision, not just a question: once Step 2 classifies the structure (0D molecule / 1D wire / 2D slab / 3D bulk), decide the whole **four-tuple** atomically — `&CELL PERIODIC` + `&POISSON PERIODIC` + `POISSON_SOLVER` + CELL size / vacuum thickness. Emitting any subset without the rest yields wrong electrostatics or a crash. Unique recommended combination per dimension:

| Dimension | `&CELL PERIODIC` | `&POISSON PERIODIC` | `POISSON_SOLVER` | CELL size / vacuum recommendation |
|-----------|------------------|---------------------|------------------|-----------------------------------|
| 0D molecule / cluster | `NONE` | `NONE` | `ANALYTIC` (or `MT` / `WAVELET`) | Cubic box; density must decay to ~0 at the faces — cluster extent + ≥ 8–10 Å margin per side (`MT` converges cleanly at ~2× the cluster extent; `WAVELET` needs only the molecule + a small margin) |
| 1D wire | `X` (wire axis) | `X` (wire axis) | `ANALYTIC` | Wire along the periodic axis; ≥ 10 Å vacuum in each non-periodic direction. `MT` / `WAVELET` do NOT support 1D |
| 2D slab / surface | `XY` | `XY` | `ANALYTIC` (or `MT`) | Slab in the periodic plane; ≥ 15 Å vacuum along the non-periodic axis (verify energy / dipole vs vacuum) |
| 3D bulk | `XYZ` | `XYZ` | `PERIODIC` (default) | — |

2D slab variants (both legitimate; state the intent in a comment):

- Keep `&CELL PERIODIC XYZ` + `&POISSON PERIODIC XY` + `ANALYTIC` — decouple electrostatics along the surface normal while the cell stays 3D-periodic (validator `CP2K_PERIODIC_SLAB`, WARN: acceptable for 2D slabs if intentional — see the table above).
- Full 3D periodic (`XYZ` + `XYZ` + `PERIODIC`) + large vacuum — slab images keep interacting electrostatically; vacuum thickness becomes a convergence parameter and must be tested, not guessed.

**改 PERIODIC 不改 solver = ERROR.** Changing `PERIODIC` (e.g. to `NONE` or `XY`) without switching `POISSON_SOLVER` off its default `PERIODIC` is a fatal misconfiguration — the `PERIODIC` solver only supports fully 3D-periodic (`XYZ`) cells. The validator flags it as `CP2K_POISSON_SOLVER_INCOMPATIBLE` (ERROR; the per-dimension compatible-solver set lives in `scripts/validate_input.py`, per CP2K manual FORCE_EVAL/DFT/POISSON). Related checks: `CP2K_PERIODIC_MISMATCH` (ERROR), `CP2K_POISSON_ON_MOLECULE` (ERROR), `CP2K_POISSON_SOLVER_UNVERIFIED` (WARN — non-XYZ cell without an explicit `&POISSON` block).

### Step 3: Ask Minimal Questions

```
1. What task? [GEO_OPT / MD / ENERGY_FORCE / BAND_STRUCTURE] → sets RUN_TYPE
2. Functional? [PBE / PBE0 / HSE06 / B3LYP / R2SCAN] → sets &XC_FUNCTIONAL
3. Basis set family? [DZVP-MOLOPT-SR-GTH / TZV2P-MOLOPT-GTH] → sets &KIND BASIS_SET
4. Dispersion? [none / D3 / D3BJ] → adds &VDW_POTENTIAL
5. Periodicity? [3D / 2D-slab / 1D-wire / 0D-molecule] → decides the four-tuple atomically: &CELL PERIODIC + &POISSON PERIODIC + POISSON_SOLVER + CELL/vacuum size (see decision tree above)
6. MD ensemble? [NVT / NVE / NPT_I] → sets ENSEMBLE + thermostat/barostat
```

### Step 4: Generate Module-Grouped CP2K Input

Exact section order:

```fortran
# ==============================================================================
# I. GLOBAL SETTINGS (&GLOBAL)
# ==============================================================================
&GLOBAL
  PROJECT     my_system             # Job name
  RUN_TYPE    GEO_OPT               # Task selector
  PRINT_LEVEL LOW
&END GLOBAL

# ==============================================================================
# II. FORCE EVALUATION (&FORCE_EVAL → &DFT)
# ==============================================================================
&FORCE_EVAL
  METHOD Quickstep
  &DFT
    # ... basis sets, potentials, XC, SCF, Poisson ...
  &END DFT
  &SUBSYS
    # ... cell, kinds, topology ...
  &END SUBSYS
&END FORCE_EVAL

# ==============================================================================
# III. MOTION (&GEO_OPT / &MD)  — band structure is NOT here, see below
# ==============================================================================
&MOTION
  &GEO_OPT
    # ... or &MD ...
  &END GEO_OPT
&END MOTION

# NOTE: &BAND_STRUCTURE does NOT belong to &MOTION. In CP2K it lives under
#   FORCE_EVAL / DFT / PRINT / BAND_STRUCTURE
# (see base_templates/cp2k_band.inp for the correct hierarchy).
```

### CP2K ↔ VASP Parameter Quick Reference

| CP2K Parameter | VASP Equivalent | Typical Value | Notes |
|---------------|-----------------|---------------|-------|
| `CUTOFF` (Ry) | `ENCUT` (eV) | — | NOT convertible: CP2K CUTOFF controls the auxiliary real-space grid for density/potential (orbitals use Gaussian basis); converge CUTOFF/REL_CUTOFF independently of any ENCUT experience |
| `EPS_SCF` | `EDIFF` | 1.0E-6 to 1.0E-7 | Energy convergence threshold |
| `MAX_SCF` | `NELM` | 300 | Max SCF iterations |
| `SCF_GUESS` | `ISTART`/`ICHARG` | ATOMIC / RESTART | Initial density guess |
| `BROYDEN_MIXING` | Default VASP mixing | — | Charge mixing algorithm |
| `ALPHA` | `AMIX` | 0.4 | Linear mixing parameter |
| `ELECTRONIC_TEMPERATURE` [K] | `SIGMA` (eV) | 300 K ≈ 0.026 eV | Smearing width (Fermi-Dirac) |
| `ADDED_MOS` | `NBANDS` (extra) | 10 | Empty bands for smearing |
| `TIMESTEP` (fs) | `POTIM` (fs) | 0.5 fs | MD time step |
| `STEPS` | `NSW` | 5000 | MD / opt steps |
| `MAX_ITER` (GEO_OPT) | `NSW` | 200 | Max geometry steps |
| `MAX_FORCE` | `EDIFFG` | 4.5E-4 Ha/bohr ≈ 0.023 eV/Å | Force convergence |
| `&PRINT / &PDOS` | `LORBIT` + `NEDOS` | — | Projected DOS |
| `&PLANAR_AVERAGED_V_HARTREE` | `LVHAR` / `LVTOT` + `LOCPOT` | — | Work function extraction; CP2K >= 2026.2-dev only — on 2026.1 use `&DFT/&PRINT/&V_HARTREE_CUBE` + external planar averaging (2026.1 aborts "unknown subsection") |
| `SURFACE_DIPOLE_CORRECTION` + `SURF_DIP_DIR` | `LDIPOL` + `IDIPOL` | off; Z | Required for asymmetric/polar slabs; keep off only for demonstrably symmetric slabs. Validator warns when a workfunction input leaves it inactive because `.inp`/`.xyz` alone cannot prove slab symmetry |
| CP2K + Phonopy workflow | `IBRION = 5/6/7/8` | — | Finite-difference / DFPT phonons |
| `&KIND / &DFT_PLUS_U` | `LDAU + LDAUL + LDAUU + LDAUJ` | — | Hubbard U correction; version-gated, see note below |
| `&PROPERTIES / &LINRES / &POLAR` | `LEPSILON` | — | Static polarizability / dielectric tensor |
| `&DFT / &PRINT / &ELF_CUBE` | `LELF` | — | Electron localization function |
| `&DFT / &PRINT / &HIRSHFELD` | `LORBIT + Bader` | — | Population analysis (CP2K prints directly) |

> **DFT+U version gate (CP2K 2026.2):** on CP2K < 2026.2, ANY `&KPOINTS`
> block (even `SCHEME GAMMA`) activates the k-point code path and Mulliken
> DFT+U aborts with "Method not implemented for k-points" — omit `&KPOINTS`
> entirely (omitting = Gamma point, the default). From CP2K 2026.2, Mulliken
> DFT+U supports k-points.
> Magnetic correlated systems also need `UKS .TRUE.` plus opposite
> `MAGNETIZATION` initial guesses on the two sublattices (see
> `base_templates/cp2k_dftu.inp`).
>
> **OT / LINRES vs k-points:** `&OT` is Gamma-only; `&LINRES`/DFPT response
> is incompatible with k-points. For k-point SCF use `&DIAGONALIZATION`
> (CP2K manual methods/dft/k-points).

### Implicit Solvation (SCCS)

CP2K implements the self-consistent continuum solvation (SCCS) model
(Andreussi 2012 / Fattebert-Gygi) natively — no patch needed. Add `&SCCS` inside
`&FORCE_EVAL / &DFT`:

```fortran
&SCCS
  METHOD              ANDREUSSI        # or FATTEBERT-GYGI
  DIELECTRIC_CONSTANT 78.36            # water; set explicitly every time
  EPS_SCCS            1.0E-7           # polarization-charge convergence; keep <= 1E-6
  EPS_SCF             1.0E-6           # keep EQUAL to DFT/SCF/EPS_SCF (known pitfall)
  MAX_ITER            100
  MIXING              0.6              # reduce to 0.2-0.3 if SCCS cycles oscillate
  DERIVATIVE_METHOD   FFT
  DELTA_RHO           2.0E-5
  &ANDREUSSI
    RHO_MAX           0.001
    RHO_MIN           0.0001
  &END ANDREUSSI
  # &FATTEBERT-GYGI                    # alternative interface model
  #   BETA              1.3
  #   RHO_ZERO          0.00078
  # &END FATTEBERT-GYGI
  # ALPHA / BETA / GAMMA               # cavitation/dispersion/repulsion terms;
                                       # 0.0 = electrostatics only (robust default)
&END SCCS
```

Practical notes (from CP2K-user list experience):
- SCCS iterations add an inner loop per SCF step — expect 2-5x cost.
- `EPS_SCCS` should be at least as tight as 1E-6, ideally 1E-7/1E-8; loose values
  silently return zero polarization energy.
- For molecules use `&POISSON PERIODIC NONE` (+ `POISSON_SOLVER MT`).
- First converge the gas-phase GEO_OPT, then switch SCCS on from the restart.

### meta-GGA (r2SCAN) via LibXC

r2SCAN is available through LibXC inside `&XC_FUNCTIONAL` (one `&LIBXC` block
for exchange, one for correlation):

```fortran
&XC
  &XC_FUNCTIONAL
    &LIBXC
      FUNCTIONAL MGGA_X_R2SCAN
    &END LIBXC
    &LIBXC
      FUNCTIONAL MGGA_C_R2SCAN
    &END LIBXC
  &END XC_FUNCTIONAL
&END XC
```

- Hybrid r2SCAN variants also exist: R2SCAN0 / R2SCAN50 (via LibXC; exact
  functional names depend on the linked LibXC version — check before use).
- meta-GGA grids: like hybrids, use `&MGRID CUTOFF >= 600 Ry` — the validator
  warns below that when SCAN/R2SCAN is detected.
