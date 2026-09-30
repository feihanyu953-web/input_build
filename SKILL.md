---
name: input_build
description: Use when generating VASP INCAR, LAMMPS input, or CP2K input files. Triggered by /input_build or when the user needs input files for DFT, MD, NEB, DOS, band structure, or frequency calculations.
---

# input_build · Input File Generator

## Overview

Generate deterministic, module-grouped input files for **VASP**, **LAMMPS**, and **CP2K**. AI reads the user's structure file first, auto-detects system properties, asks only for what cannot be inferred, and produces annotated, sectioned output. Base parameter values live in `base_templates/`; this skill defines the decision logic and output format.

**Supported codes:** VASP (INCAR) | LAMMPS (in scripts) | CP2K (inp files)

**Core principle:** Auto-detect first, question second, annotate always.

## Legal Notice

- `input_build` generates **input control files only** (INCAR, KPOINTS, CP2K `.inp`, LAMMPS `.in`). It does **not** generate, distribute, or embed any copyrighted material including VASP POTCAR files, pseudopotentials, or executable code.
- Users are responsible for obtaining valid licenses for commercial software (e.g., VASP) and preparing their own POTCAR files from licensed pseudopotential libraries.
- Recommended POTCAR preparation tools: [vaspkit](https://github.com/pytlab/VASPKIT), `pymatgen.io.vasp.Potcar` (both require a user-provided local VASP pseudopotential library).

## Reference Files (read on demand)

| When generating... | Read first |
|---|---|
| LAMMPS input | `references/lammps.md` |
| LAMMPS parameter selection & equilibration protocol | `references/lammps_best_practices.md` |
| CP2K input | `references/cp2k.md` (incl. CP2K↔VASP parameter mapping) |
| KPOINTS / band paths | `references/kpoints.md` |
| VASP follow-ups | `references/vasp.md` |
| Worked examples | `examples/README.md` (index + task coverage matrix), then the matching example directory |

## Auto-Detection Logic

Before asking anything, read the structure file and infer:

| Property | Detection Method | Implication |
|----------|-----------------|-------------|
| **Elements** | Parse POSCAR line 6 / data file masses | Fe/Co/Ni/Mn/Cr present → magnetic (ISPIN=2); Ce/U/La → correlated + magnetic risk |
| **Vacuum layer** | Largest periodic circular-gap of fractional coordinates along each lattice vector (includes the 0/1 wrap) | > 5 Å → slab/interface review → asymmetric/polar slabs need IDIPOL+LDIPOL |
| **Adsorbate** | Compare top/bottom atom distributions | Asymmetric → single-sided adsorption |
| **Metal vs oxide** | Element identity + stoichiometry | Transition metal only → `metal_slab` defaults; oxide → `oxide_surface`/`oxide_bulk` defaults |
| **System size** | Atom count from structure | > 100 atoms → LREAL=Auto; < 50 → LREAL=.FALSE. |
| **Has H** | Element list contains H | POTIM ≤ 1.0 fs (MD) or ≤ 0.3 (CG relax with adsorbates) |

**What AI CAN infer (do NOT ask):**
- Lattice type, element types, atom count, vacuum presence, adsorbate asymmetry
- Default smearing (MP for metals, Gaussian for molecules/oxides)
- Basic geometry constraints (ISIF from task type)

**What AI CANNOT infer (must ask):**
- Dispersion correction needed? (vdW-DF, D3, D3BJ)
- DFT+U elements and U-J values
- Hardware constraints (cores, KPAR/NCORE)
- Precision vs speed trade-off
- LAMMPS: potential file paths

## Material-Aware Defaults

Use the detected material class to select parameter defaults before overlaying modifiers:

| Class | Detection | SCF defaults | Geometry defaults | Notes |
|---|---|---|---|---|
| **metal_slab** | transition metal + vacuum | `ISMEAR=0`, `SIGMA=0.1`, `NELM=60`, `ALGO=Normal` | `POTIM=0.5`, `ISIF=2`, `ISYM=0` | Current default path |
| **oxide_surface** | oxide + vacuum + adsorbate | `ISMEAR=0`, `SIGMA=0.05`, `NELM=100`, `ALGO=Normal` | `POTIM=0.2`, `ISIF=2`, `ISYM=0`, `LASPH=.TRUE.` | Tighten POTIM; DFT+U likely |
| **oxide_bulk** | oxide, no vacuum | `ISMEAR=0`, `SIGMA=0.05`, `NELM=100`, `ALGO=Normal` | `POTIM=0.2`, `ISIF=3`, `ISYM=2` | Keep symmetry where safe |
| **molecule/cluster** | no lattice / large vacuum | `ISMEAR=0`, `SIGMA=0.01`, `NELM=60` | `POTIM=0.5` (or smaller) | Gamma-only k-points |

**DFT+U rule:** When `LDAU=.TRUE.`, inspect `LDAUL`:
- Any `LDAUL = 2` (d) → set `LMAXMIX = 4`
- Any `LDAUL = 3` (f) → set `LMAXMIX = 6`
- For ordinary self-consistent DFT+U, these values are recommended so a written
  `CHGCAR` retains the relevant on-site occupancy components. For a fixed-density
  restart/post-processing calculation with `ICHARG=11`, the matching value is
  required; otherwise the charge density read from `CHGCAR` lacks those components.

**ENCUT rule:**
- `ENCUT = 400` is a safe **minimum** for most systems.
- For O-containing oxides or final energy comparisons, warn the user that `ENCUT = 520+` (1.3× max ENMAX) is recommended.
- Do not auto-increase ENCUT unless the user explicitly selects `Accurate` precision; instead, annotate the warning.

**Magnetic rule:**
- Auto-set `ISPIN=2` for Fe/Co/Ni/Mn/Cr.
- For Ce/U/La or adsorbates that may be radicals, **ask** whether to enable spin polarization and provide a `MAGMOM` template.

## Version & Capability Gating（版本与能力门控）

Baselines — templates are verified against these versions; anything older is untested:

| Program | Baseline | Verified build | Gate notes |
|---|---|---|---|
| VASP | ≥ 6.3 | 6.5.1 + VTST | `LCLIMB` / CI-NEB is a **VTST extension**, not a stock VASP tag — ask which binary runs the job; VASPsol requires a patched binary; `RANDOM_SEED` takes three integers |
| CP2K | ≥ 2024.3 | 2026.1 | **2026.2 changes (gated):** `&CELL_OPT/TYPE` removed (DIRECT_CELL_OPT is the default — omit the keyword for 2026.2+); Mulliken `DFT+U` supports k-points from 2026.2 — pre-2026.2 DFT+U must omit `&KPOINTS` entirely (even `SCHEME GAMMA` aborts with "Method not implemented for k-points"; omitting = Gamma point); `&PLANAR_AVERAGED_V_HARTREE` is a 2026.2-dev trunk addition — on 2026.1 use `&DFT/&PRINT/&V_HARTREE_CUBE` + external planar averaging (2026.1 aborts "unknown subsection") |
| LAMMPS | ≥ 22Jul2025 | 22 Jul 2025 Update 3 | `pair_style reax/c` was removed → use `reaxff` (plus a charge-carrying atom style and `fix qeq/reaxff`); package features (ELECTRODE, RIGID, PLUMED, ML-*) need the corresponding compiled package — check `lmp -h` |

Resolve the Step-3 version/build question **before** rendering a template; never mix syntax from different versions or external patches in one unconditional input.

## Template & Modifier Routing

**Routing index: `base_templates/INDEX.json`** (task → template → applicable modifiers, with notes and conflict matrix). It is the machine-readable routing table enforced by `tests/test_template_index.py` — **not** a single source of truth: parameter rules also live in this file, the templates/modifiers, `references/`, and `scripts/validate_input.py`; where sources disagree, the stricter rule wins and the disagreement is a bug to fix. Summary:

| VASP task | Template | LAMMPS task | Template | CP2K task | Template |
|---|---|---|---|---|---|
| relax / scf | vasp_relax / vasp_scf | md / npt | lammps_md | scf | cp2k_scf |
| md | vasp_md | nve | lammps_nve | geo_opt / cell_opt | cp2k_geo_opt / cp2k_cell_opt |
| slow-growth (SG-AIMD) | vasp_slowgrowth | | | | |
| dos / band | vasp_dos / vasp_band | plumed / neb | lammps_plumed / lammps_neb | md / neb | cp2k_md / cp2k_neb |
| freq / phonon | vasp_freq / vasp_phonopy | | | band / dos | cp2k_band / cp2k_dos |
| neb / bader / hse | vasp_neb / vasp_bader / vasp_hse | | | phonon / metadyn | cp2k_phonon / cp2k_metadyn |
| dftu | vasp_dftu | | | workfunction / dftu | cp2k_workfunction / cp2k_dftu |
| workfunction / elf | vasp_workfunction / vasp_elf | | | elf / hirshfeld | cp2k_elf / cp2k_hirshfeld |
| optics / dielectric | vasp_optics / vasp_lepsilon | | | optics | cp2k_optics |

**Modifier overlay semantics (v1, AI-guided):**
1. Start from the base template, then overlay modifiers from `modifiers/` **in the order INDEX.json lists them**.
2. On keyword collision, the **later** modifier wins.
3. Available modifiers: `ivdw` (D3-BJ dispersion), `dipole` (slab correction), `magnetic` (ISPIN=2), `semiconductor` (ISMEAR=-5 tetrahedron; static SCF/DOS on dense automatic meshes only — never relax/MD, molecules/Gamma-only, or line-mode band), `dftu` (LDAU\* + mandatory LMAXMIX), `optics` (LOPTICS), `solvation` (VASPsol implicit water), `efield` (sawtooth field; requires the dipole modifier), `soc` (LSORBIT+SAXIS; NBANDS ~2x), `metagga` (r2SCAN/SCAN; LASPH mandatory), `efield_lammps` (LAMMPS fix efield snippet), plus LAMMPS snippet modifiers `shake_lammps` (rigid water), `analysis_rdf_msd`, `analysis_hbond` (post-processing route), `ensemble_langevin`, `temp_ramp`, `dump_full`, `wall_slab`. `empty` documents the patch format only — never apply it.
4. **After overlaying, the result MUST pass `scripts/validate_input.py` with zero ERROR findings** (see Machine Validation).

### Step 1: Read Structure

```bash
# POSCAR/CONTCAR: parse lines 1-7 for elements, counts, lattice
# LAMMPS data: parse masses section for elements
```

### Step 2: Infer & Classify

Use auto-detection table above. Build a classification summary:

```
System: Pt(100) 6x6 slab + NH3 + 100 H2O + NaOH
Elements: Pt, N, H, O, Na
Magnetic: No (no Fe/Co/Ni/Mn/Cr)
Slab: Yes (vacuum 18 Å)
Adsorbate: Single-sided (asymmetric z-distribution)
Metal: Yes (Pt slab)
Has H: Yes
Size: ~137 atoms → LREAL=Auto
```

**Note:** The above is an example. Auto-detection works for any system—bulk, slab, molecule, cluster, or interface.

### Step 3: Ask Minimal Questions

```
1. What code and task? [VASP: relax/MD/slow-growth(SG-AIMD)/DOS/PDOS/NEB/freq/phonon(phonopy)/band/bader/HSE/DFT+U/workfunction/elf/optics/dielectric | LAMMPS: MD/NPT/NVE/minimize/MLFF/CONP/PLUMED/NEB | CP2K: GEO_OPT/MD/ENERGY_FORCE/BAND_STRUCTURE/DOS/PDOS/PHONON/METADYN/WORKFUNCTION/DFT+U/ELF/OPTICS/HIRSHFELD] → selects base template
2. Dispersion correction? [none/D3/D3BJ/VDW-DF] → sets IVDW (VASP) or &VDW_POTENTIAL (CP2K)
3. DFT+U? [no / yes: which elements + U values] → sets LDAU* (VASP only)
4. Precision? [Normal/Accurate] → sets PREC/ENCUT (VASP), CUTOFF (CP2K)
5. Hardware? [cores, memory, time limit] → parallelization section
6. Magnetic ordering? [non-magnetic / FM / AFM / ferrimagnetic + initial moment per species] → ISPIN, MAGMOM; **mandatory** whenever magnetic elements (Fe/Co/Ni/Mn/Cr/Ce/U/La) are present — ordering changes total-energy ordering and DFT+U local states, never guess from element identity alone
7. Surface normal? [slab normal along lattice vector a / b / c] → IDIPOL axis, CP2K PARALLEL_PLANE / SURF_DIP_DIR, LAMMPS barostat exclusion; **mandatory** for slab/interface systems
8. Boundary periodicity? [3D bulk / 2D slab / 1D wire / 0D molecule] → k-mesh, LAMMPS `boundary` + NPT coupling; for CP2K the answer decides the four-tuple atomically — `&CELL PERIODIC` + `&POISSON PERIODIC` + `POISSON_SOLVER` + CELL/vacuum sizing (never set one without the others; 改 PERIODIC 不改 solver = ERROR `CP2K_POISSON_SOLVER_INCOMPATIBLE`), route per the Dimension Routing Decision Tree（维度路由决策树） in `references/cp2k.md`; **mandatory**
9. Potential / pseudopotential files? [VASP: POTCAR set + version (e.g. PBE.54 vs PBE.64); LAMMPS: file path + format class — funcfl → `pair_style eam`, setfl → `eam/alloy`/`eam/fs`; CP2K: basis-set & GTH-potential file names] → pair_style/pair_coeff, ENMAX coverage; **mandatory** (never invent potentials)
10. Program version & build? [VASP version + stock / VTST / VASPsol patches; CP2K version; LAMMPS version + compiled packages (ELECTRODE/RIGID/PLUMED/...)] → gates version-specific syntax, see Version & Capability Gating; **mandatory**
```

**Code-specific follow-ups:**

**VASP:**（完整 follow-ups 见 `references/vasp.md`，生成前必读）
- VASPsol? → 需 patched binary 确认 + `solvation` modifier
- EFIELD / 带电 slab? → `efield` modifier，dipole modifier 必须同设
- SOC? → `soc` modifier，提醒 NBANDS ~2x、LMAXMIX 4/6、ENCUT 1.3–1.5×
- meta-GGA? → `metagga` modifier，LASPH 强制
- Phonon? → phonopy 单点 vs DFPT（IBRION=8）
- SG-AIMD (slow growth)? → `vasp_slowgrowth` template; two stages (equilibration `INCREM=0`/`LBLUEOUT=.FALSE.`, then growth); `MDALGO` must be 1 or 2 (**not** 3/Langevin); ICONST + both INCARs via `scripts/iconst_helper.py render --emit-incar`; **density relay** — stage the parent AIMD's end-of-run CHGCAR into the frame dir (cluster-side `cp`, same discipline as POTCAR) so the `ICHARG=1` equil has its initial guess; gate before submit: CHGCAR present and non-zero; see `references/vasp.md` "Slow-growth AIMD"

**LAMMPS:**
- Potential file path(s)? → exact pair_style / pair_coeff
- Ensemble? → NVT / NVE / NPT
- MLFF model? → `lammps_mlff` template; model path + element order (must match data-file type order) from user
- Constant-potential electrode? → `lammps_conp` template; requires ELECTRODE package + an /electrode kspace style
- Uniform applied field? → `efield_lammps` snippet (fix efield; charged atoms only — never on MLFF)
- Explicit water / rigid constraints? → `shake_lammps` snippet (fix shake after ALL force-adding fixes; 2 fs timestep OK)
- Analysis needs? → `analysis_rdf_msd` (RDF/MSD/Q6), `analysis_hbond` (no native compute — RDF + MDAnalysis/OVITO post-processing), `dump_full` (velocities+forces)
- Thermostat style / heating schedule? → `ensemble_langevin` (fix nve + fix langevin) and/or `temp_ramp` (0.1–1 K/ps)
- Confined liquid without vacuum? → `wall_slab` snippet (fix wall/lj93)
- Enhanced sampling? → `lammps_plumed` template (fix plumed + plumed.dat; one fix only)
- Reaction path / barrier? → `lammps_neb` template (replica run `-partition NxM`; min_style quickmin/fire only)

**CP2K:**
- Functional? → PBE / PBE0 / HSE06 / R2SCAN
- Basis set? → DZVP-MOLOPT-SR-GTH / TZV2P-MOLOPT-GTH
- Periodicity? → 3D bulk / 2D slab / 1D wire / 0D molecule — a routing decision, not just a question: the answer sets the four-tuple `&CELL PERIODIC` + `&POISSON PERIODIC` + `POISSON_SOLVER` + CELL/vacuum size atomically, per the Dimension Routing Decision Tree（维度路由决策树） in `references/cp2k.md`
- DOS/PDOS? → `ADDED_MOS` for unoccupied states; `NLUMO`/`COMPONENTS`
- Phonon? → confirm Phonopy environment and supercell size (`--dim`)
- Work function? → confirm surface normal direction (`PARALLEL_PLANE XY/YZ/XZ`); version gate: CP2K 2026.1 → `&V_HARTREE_CUBE` + external planar averaging (default), CP2K ≥ 2026.2-dev → `&PLANAR_AVERAGED_V_HARTREE`
- DFT+U? → which elements, `U_MINUS_J` values; k-point gating: before CP2K 2026.2 omit `&KPOINTS` entirely (any `&KPOINTS`, even `SCHEME GAMMA`, aborts "Method not implemented for k-points"; omitting = Gamma point), Mulliken DFT+U supports k-points from 2026.2 (ask CP2K version)
- ELF? → output `ELF_CUBE`; optional `E_DENSITY_CUBE` for Bader post-processing
- Optics? → static polarizability (`LINRES/POLAR`) vs frequency-dependent TDDFT workflow
- Hirshfeld? → self-consistent variant and shape function choice
- Metadynamics? → `cp2k_metadyn` template; CV choice (DISTANCE/ANGLE/COORDINATION...), WW 0.5–2 kcal/mol, WTGAMMA 10–50, optional &WALL

### Step 4: Generate Module-Grouped INCAR

Exact section order and separators:

```fortran
# ==============================================================================
# I. GLOBAL SETTINGS
# ==============================================================================
SYSTEM   = Pt100_6x6_NH3_NaOH_explicit    ! User-provided description
ISTART   = 0                               ! Start from scratch
ICHARG   = 2                               ! Superposition of atoms
ISPIN    = 1                               ! Non-magnetic (auto-detected)

# ==============================================================================
# II. ELECTRONIC SCF
# ==============================================================================
ENCUT    = 400                             ! Minimum for most systems
                                           ! Use 520+ for O-containing / publication-quality
PREC     = Normal                          ! Normal precision; explicit ENCUT
EDIFF    = 1E-6                            ! Energy convergence (tight for relax forces)
ALGO     = Normal                          ! Davidson/RMM-DIIS hybrid
ISMEAR   = 0                               ! Gaussian smearing
SIGMA    = 0.1                             ! 0.1 eV for metals; 0.05 eV for oxides
NELM     = 60                              ! Max electronic steps (100 for DFT+U)
NELMIN   = 4                               ! Min electronic steps

# ==============================================================================
# III. GEOMETRY / MD
# ==============================================================================
IBRION   = 2                               ! Conjugate gradient relax
ISIF     = 2                               ! Relax ions, fix cell
NSW      = 100                             ! Max ionic steps
EDIFFG   = -0.03                           ! Force convergence (eV/Å)
POTIM    = 0.3                             ! Step size / timestep; reduce to 0.2 for complex oxides

# ==============================================================================
# IV. ACCURACY & AUGMENTATION
# ==============================================================================
ADDGRID  = .TRUE.                          ! Fine grid for forces
LASPH    = .TRUE.                          ! Non-spherical augmentation
# LMAXMIX = 4                              ! Set for d-electron DFT+U (e.g. Fe, Ni, Co)
# LMAXMIX = 6                              ! Set for f-electron DFT+U (e.g. Ce, U, rare earths)
LREAL    = Auto                            ! Real-space projection (>100 atoms)
ISYM     = 0                               ! No symmetry (adsorbate relax)

# ==============================================================================
# V. SPECIAL FEATURES
# ==============================================================================
# --- Dipole correction (slab with vacuum detected) ---
IDIPOL   = 3                               ! Dipole correction along the 3rd lattice vector (z, surface normal)
                                           ! (IDIPOL=1/2/3 selects lattice vector a/b/c; 4 = all directions)
LDIPOL   = .TRUE.                          ! Activate dipole correction

# --- Dispersion correction (user selected D3BJ) ---
IVDW     = 12                              ! DFT-D3 with Becke-Johnson damping (D3BJ; IVDW=11 is D3 zero-damping)

# --- DFT+U (user selected: none for this system) ---
# LDAU     = .TRUE.
# LDAUTYPE = 2
# LDAUL    = -1 -1 2                       ! Per-element L quantum number
# LDAUU    = 0 0 3.5                       ! Per-element U value
# LDAUJ    = 0 0 0                         ! Per-element J value

# ==============================================================================
# VI. PARALLELIZATION
# ==============================================================================
KPAR     = 4                               ! k-point parallelization
NCORE    = 8                               ! Bands per core
LSCALU   = .FALSE.
NSIM     = 4

# ==============================================================================
# VII. OUTPUT
# ==============================================================================
LWAVE    = .FALSE.                         ! WAVECAR GB-scale, no default consumer
LCHARG   = .TRUE.                          ! CHGCAR ~50 MB; density relay (ICHARG=1/11)
LELF     = .FALSE.
LVTOT    = .FALSE.
NEDOS    = 3001                            ! Fine DOS grid

# ==============================================================================
# END OF INCAR
# ==============================================================================
```

### Post-Generation Annotation

Always output:

```markdown
## Auto-Detection Summary
- **Slab model detected**: vacuum = 18.2 Å → dipole correction activated
- **Metal detected**: Pt present → Gaussian smearing (ISMEAR=0, SIGMA=0.1)
- **Non-magnetic**: no Fe/Co/Ni/Mn/Cr/Ce/U → ISPIN=1
- **Medium system**: 137 atoms → LREAL=Auto for speed
- **Has hydrogen**: POTIM capped at 0.3 for CG relax (0.5 fs if MD)

## Suggested Improvements
1. For O-containing systems, verify ENCUT covers highest ENMAX in POTCAR; use 520+ eV for final energies.
2. If DFT+U is active, confirm LMAXMIX matches the correlated orbital (4 for d, 6 for f).
3. For complex oxide surfaces, consider POTIM=0.2 and NELM=100.
4. If adsorbate dissociates during relax, switch to IBRION=1 (quasi-Newton) after initial CG.
```

## LAMMPS Deterministic Renderer (Phase D) — LAMMPS-only routing

This section applies **only** when `code=lammps`. VASP and CP2K generation is unchanged.

When generating a LAMMPS input (`in.lammps`) and the user has already supplied the
potential/model path and the type mapping, route through the deterministic
renderer instead of hand-assembling the script:

- Call `scripts/render_lammps.py` with a Phase A `GenerationSpec` plus explicitly
  selected base template, modifiers and profiles; it writes `in.lammps` and
  `render_trace.json`.
- The renderer **never selects or invents** potential/model lines — `pair_style`
  and `pair_coeff` come verbatim from `spec.potential`.
- After rendering, `in.lammps` MUST pass the existing `validate_lammps_one()`
  with zero ERROR findings.
- The same input MUST produce the same `output_sha256` (byte-stable rendering).
- Initial coverage: `generic_md` and `mlff/mace` profiles only.
- Uncovered templates (`lammps_conp.in`, `lammps_plumed.in`, `lammps_neb.in`,
  `lammps_nve.in`, `lammps_minimize.in`) fail closed in Phase D —
  never silently degrade.

## Validation Rules

Before returning the generated file, verify:

| Check | Rule | Fail Action |
|-------|------|-------------|
| **ENCUT coverage** | ENCUT ≥ 1.3 × max ENMAX in POTCAR | Flag warning, do not auto-correct |
| **Oxide ENCUT** | O present + relax → warn if ENCUT < 450; recommend 520+ for final energies | Warning |
| **Magnetic consistency** | ISPIN=2 ↔ elements contain Fe/Co/Ni/Mn/Cr/Ce/U/La or user opts in | Warn if mismatch |
| **Dipole logic** | Detect vacuum from the largest periodic circular-gap. Missing IDIPOL/LDIPOL remains a WARN: asymmetric/polar slabs require correction; omission is acceptable only with evidence that top/bottom surfaces are symmetric and the net dipole normal to the slab is negligible | Warn if mismatch or symmetry evidence is absent |
| **Dipole axis** | IDIPOL axis (1=a / 2=b / 3=c) must match the detected vacuum axis. `IDIPOL=4` is the all-direction correction for isolated molecules; warn for slab/wire-like inputs or a workfunction task | Warn if mismatch / non-molecular IDIPOL=4 |
| **Smearing logic** | Task-aware: metals → ISMEAR=-1/0/1 (check entropy term); semiconductor/insulator static/DOS with dense automatic k-mesh → ISMEAR=-5 allowed (tetrahedron); molecule/Gamma-only → ISMEAR=0 small SIGMA; line-mode band → never tetrahedron | Warn on mismatch |
| **MD timestep** | POTIM ≤ 1.0 fs when H present; ≤ 2.0 fs otherwise | Cap and warn |
| **MD ISIF** | IBRION=0 with ISIF=2 computes a useless stress tensor every step; VASP defaults MD to ISIF=0 | Warn |
| **MD NCORE unset** | MD without explicit NCORE/NPAR defaults to NCORE=1 — grossly inefficient (measured 410 vs 10-16 s/step on 64 cores) | Warn |
| **MD vacuum sloshing** | Slab AIMD with total periodic vacuum > 18 Å (top+bottom combine across the boundary) + LDIPOL → SCF stalls at 100-200 iters/step; verified converging range 15-17 Å | Warn |
| **MD mixing metal+water** | Metal slab + explicit water/ions + default AMIX=0.4 charge-sloshes and diverges; require the verified trio AMIX=0.02, BMIX=1.0, AMIN=0.01 (BMIX=0.01 is the static two-step SCF prescription — do not mix the two) | Warn if AMIX unset |
| **MD NBANDS drift** | Slab AIMD without explicit NBANDS: auto value drifts with VASP version/binary (std vs gam)/PAW variant (Pt ZVAL=10 vs Pt_pv 16 shifts occupied bands ~100); pin NBANDS ≈ 1.2-1.4 × occupied after checking POTCAR ZVAL | Warn |
| **CG POTIM for adsorbates** | H present + IBRION=2 + slab → warn if POTIM > 0.3 | Warn |
| **DFT+U completeness** | LDAU=.TRUE. requires LDAUTYPE, LDAUL, LDAUU, LDAUJ; recommend LMAXMIX=4 (d) / 6 (f) for reusable CHGCAR | Error for missing LDAU*; Warn for LMAXMIX in self-consistent runs |
| **LMAXMIX value** | LDAUL contains 3 → LMAXMIX=6; contains 2 → LMAXMIX≥4; fixed-density `ICHARG=11` makes this mandatory | Warn for self-consistent runs; Error for ICHARG=11 |
| **NELM for DFT+U** | LDAU=.TRUE. + NELM < 80 → warn | Warn |
| **LAMMPS potential** | Section III contains `>>> USER: insert` OR actual pair_style | Error if blank without marker |
| **Parallelization** | KPAR × NCORE ≤ total cores | Warn if over-allocated |
| **CP2K basis coverage** | Every element in coord file has a matching `&KIND` block | Error if missing |
| **CP2K periodicity consistency** | Route `&CELL PERIODIC` and `&POISSON PERIODIC` together; `CELL XYZ` + `POISSON XY` is an allowed slab decoupling when intentional, while incompatible 0D/3D mismatches remain invalid | Warn for intentional slab split; Error for incompatible mismatch |
| **CP2K CUTOFF sanity** | CUTOFF ≥ 300 Ry for DFT; ≥ 600 Ry for meta-GGA/hybrids | Warn if below |
| **CP2K SCF convergence** | EPS_SCF ≤ 1.0E-5 for MD; ≤ 1.0E-7 for static / accurate forces | Warn if looser |
| **CP2K MD timestep** | TIMESTEP ≤ 0.5 fs when H present; ≤ 1.0 fs otherwise | Cap and warn |
| **Workfunction output** | VASP `workfunction` task requires `LVHAR=.TRUE.` or `LVTOT=.TRUE.` | Error if missing |
| **Workfunction dipole** | slab + (`workfunction` task OR `LVHAR`/`LVTOT` set) → recommend `IDIPOL` + `LDIPOL`; fires without a task hint | Warn if absent |
| **ELF output** | VASP `elf` task requires `LELF=.TRUE.` | Error if missing |
| **ELF NPAR** | `LELF=.TRUE.` requires `NPAR=1` | Error if missing |
| **Optics keyword** | VASP `optics` task requires `LOPTICS=.TRUE.` | Error if missing |
| **Optics empty bands** | `LOPTICS=.TRUE.` + metal/semiconductor → recommend `NBANDS` boost | Warn if absent |
| **CP2K DOS print** | `cp2k_dos.inp` must contain `&PDOS` in `&PRINT / &DFT` | Error if missing |
| **CP2K phonon workflow** | `cp2k_phonon.inp` must be `ENERGY_FORCE` with `&FORCES ON` and Phonopy instructions | Error if missing |
| **CP2K workfunction** | `cp2k_workfunction.inp` must contain `&V_HARTREE_CUBE` (2026.1-safe default, + external planar averaging) or `&PLANAR_AVERAGED_V_HARTREE` (CP2K ≥ 2026.2-dev only; 2026.1 aborts "unknown subsection") | Error if neither; Warn if the 2026.2+ section is used |
| **CP2K workfunction dipole** | workfunction input without active `SURFACE_DIPOLE_CORRECTION` → review slab symmetry; asymmetric/polar slabs require the correction. Static `.inp`/`.xyz` validation cannot prove top/bottom symmetry. If enabled, `SURF_DIP_DIR` must be X/Y/Z (omitted = CP2K default Z). CP2K `${VAR}`/`$VAR` preprocessor values cannot be resolved statically | Warn if inactive or unresolved; Error for invalid literal logical/direction value |
| **CP2K DFT+U keyword** | `cp2k_dftu.inp` must contain `&DFT_PLUS_U` under `&KIND` and `PLUS_U_METHOD` in `&DFT` | Error if missing |
| **CP2K DFT+U k-points gating** | DFT+U with any `&KPOINTS` block → warn: on CP2K < 2026.2 any `&KPOINTS` (even `SCHEME GAMMA`) aborts ("Method not implemented for k-points"); omit `&KPOINTS` = Gamma point; Mulliken DFT+U supports k-points ≥ 2026.2 | Warn |
| **CP2K optics keyword** | `cp2k_optics.inp` must be `RUN_TYPE LINEAR_RESPONSE` with `&LINRES / &POLAR` | Error if missing |
| **CP2K ELF keyword** | `cp2k_elf.inp` must contain `&ELF_CUBE` | Error if missing |
| **CP2K Hirshfeld keyword** | `cp2k_hirshfeld.inp` must contain `&HIRSHFELD` | Error if missing |
| **VASP dielectric keyword** | `vasp_lepsilon.incar` must contain `LEPSILON=.TRUE.` | Error if missing |
| **VASP dielectric conflict** | `LEPSILON=.TRUE.` + `LOPTICS=.TRUE.` in same INCAR → error | Error |
| **VASP dielectric smearing** | `LEPSILON=.TRUE.` + `ISMEAR < 0` on insulator/semiconductor → warn | Warn |
| **CP2K section placement** | `&FORCES` only valid under `FORCE_EVAL/PRINT` (under `DFT/PRINT` 2026.1 aborts "unknown subsection FORCES of section PRINT"); `&TRAJECTORY` under `MOTION/PRINT`, not `MOTION/CELL_OPT/PRINT` | Error if misplaced |
| **CP2K PDOS k-points** | `&PDOS` + `&KPOINTS` in one input → 2026.1 writes NO PDOS files ("pDOS is not implemented for k points"); drop `&KPOINTS` (Gamma-only) for PDOS | Warn |
| **VASPsol binary** | `LSOL=.TRUE.` requires a VASPsol-patched VASP (cannot be verified from files) → always warn: require BOTH a NON-ZERO last-step `Solvation Ediel_sol` (constant 0.00000000 = LSOL never coupled, seen on a real 6.5.1 build) AND an LSOL/EB_K solvent block in vasprun.xml | Warn always |
| **VASPsol precision** | `LSOL=.TRUE.` + PREC not Accurate → cavitation energy unreliable | Warn |
| **EFIELD dipole** | `EFIELD` requires IDIPOL + LDIPOL (field silently not applied otherwise) | Error if missing |
| **Charged slab dipole** | `NELECT` set + vacuum detected + no IDIPOL → recommend dipole correction | Warn |
| **CP2K SCCS dielectric** | `&SCCS` must set `DIELECTRIC_CONSTANT` explicitly (usual range 1-90) | Warn |
| **CP2K SCCS convergence** | `EPS_SCCS` > 1.0E-6 → warn (can silently return zero polarization energy) | Warn |
| **LAMMPS electrode kspace** | `fix electrode/*` requires `pppm/electrode` or `ewald/electrode` (plain pppm crashes) | Error |
| **LAMMPS MLFF model** | `pair_style mace/deepmd/pace` without a model file or `>>> USER` marker | Warn |
| **SOC empty bands** | `LSORBIT=.TRUE.` without explicit `NBANDS` (non-collinear ~2x bands) | Warn |
| **meta-GGA augmentation** | `METAGGA` set without `LASPH=.TRUE.` | Error |
| **meta-GGA grid** | `METAGGA` set without `ADDGRID` | Warn |
| **CP2K meta-GGA CUTOFF** | `XC_FUNCTIONAL` contains SCAN/R2SCAN + CUTOFF < 600 Ry | Warn |
| **VASP phonon SCF** | task=phonon + `EDIFF > 1E-7` (phonopy forces need 1E-8) | Warn |
| **CP2K metadyn sections** | metadyn task requires `&METADYN` + `&METAVAR` + `&COLVAR` under `FORCE_EVAL/SUBSYS` | Error if missing |
| **CP2K metadyn hills print** | `&METADYN` without `&PRINT/&HILLS` (FES reconstruction impossible) | Warn |
| **LAMMPS SHAKE reminder** | evaluate each executed MD `run` with its then-active timestep/fixes; >1 fs requires active `fix shake`/`fix rigid*` unless `--data` rules out H. If `--data` plus `group ... type` proves the constraint group excludes every H type, it does not suppress the warning | Warn |
| **LAMMPS high timestep** | timestep > 1 fs in any executed MD segment → warn unless an active constraint can cover H or `--data` proves no H; comments, a constraint added only after `run`, and a later `unfix` do not rewrite run history | Warn |
| **LAMMPS NEB fix** | `neb` command without `fix ID group neb Kspring` | Error |
| **VASP freq NSW** | `IBRION=5/6` without `NSW≥1` → finite-difference run never starts (static SCF only) | Error |
| **VASP RANDOM_SEED** | `RANDOM_SEED` present but not 3 integers (VASP 6.x syntax) | Warn |
| **DFT+U zero U** | `LDAU=.TRUE.` with all `LDAUL=-1` or all Ueff=0 → no U applied; exempt only explicit control calculations | Error |
| **LANGEVIN_GAMMA count** | value count ≠ NTYP species (needs POSCAR; skipped otherwise) | Warn |
| **LAMMPS 0 K velocity** | `velocity ... create 0.0` → LAMMPS aborts ("rescaling a 0.0 temperature") | Error |
| **LAMMPS pair_coeff** | `pair_style` present but no `pair_coeff` anywhere | Error |
| **LAMMPS integrator conflict** | same group carries more than one active time integrator (`nve`/`nvt`/`npt`/`nph`/`rigid*`) without `unfix` separation | Error |
| **LAMMPS barostat periodicity** | `fix npt/nph` pressurizes a non-periodic `boundary` dimension (e.g. vacuum axis) | Error |
| **LAMMPS reax/c removed** | `pair_style reax/c` no longer exists (≥ 22Jul2025) → use `reaxff` + `fix qeq/reaxff` | Error |
| **LAMMPS unresolved placeholder** | active (non-comment) line contains `>>> USER` marker | Error |
| **CP2K OT + k-points** | `&SCF/&OT` together with `&KPOINTS` (unsupported combination) | Error |
| **CP2K LINRES + k-points** | `&LINRES`/`&DFPT` together with `&KPOINTS` (unsupported combination) | Error |
| **CP2K REAL wfn + mesh** | general k-mesh (non-Gamma) with `WAVEFUNCTIONS REAL` → must be COMPLEX | Error |
| **CP2K Poisson solver** | every explicit `POISSON_SOLVER` must be known and compatible with effective `&POISSON PERIODIC` (not merely `&CELL PERIODIC`); non-XYZ cells without `&POISSON` remain unresolved | Error for incompatible/unknown; Warn if unresolved |
| **CP2K unparseable value** | unit tokens (`[Ry] 200`) and Fortran exponents (`1.0D-4`) are parsed; failure warns instead of silently falling back to defaults | Warn |
| **Finite scalar values** | VASP scalar fields used by validation and LAMMPS `timestep` must be finite (`NaN`/`Inf` are invalid); CP2K numeric helpers treat non-finite values as unparseable | Error for VASP/LAMMPS; Warn for CP2K unresolved checks |
| **Runner completeness** | Missing/unparseable VASP POSCAR, CP2K coordinate, or LAMMPS `read_data` context → `INCOMPLETE` or syntax `FAIL` as appropriate, never `STATIC_PASS`; CP2K XYZ/PDB and ordinary inline `&COORD` are parsed for KIND coverage (PDB obeys `USE_ELEMENT_AS_KIND`, default false), while unresolved preprocessor switches/`@INCLUDE`/unsupported coordinate formats remain `INCOMPLETE`; K-series KPOINTS format/README consistency is checked | Report |
| **SG ICONST context** | task=slowgrowth requires an ICONST context; explicit `--task slowgrowth` without `--iconst` is an error, an inferred slowgrowth without ICONST warns and skips CV checks; a given but nonexistent `--iconst` path warns (`SG_ICONST_UNREADABLE_PATH`) | Error / Warn |
| **SG thermostat** | `MDALGO` must be 1 (Andersen) or 2 (Nose-Hoover); 3 (Langevin) cannot drive INCREM; unset warns | Error (`SG_MDALGO_UNSUPPORTED`); Warn if MDALGO unset |
| **SG INCREM parseable** | every INCREM token must parse as a finite number (comma-style lists are silently mangled by tokenization) | Error (`SG_INCREM_UNPARSEABLE`) |
| **SG INCREM arity** | one INCREM value per controlled parameter, where a complex coordinate (S/C/D) voids the status of every preceding primitive | Error (`SG_INCREM_ARITY`) |
| **SG controlled coordinate** | a non-zero INCREM needs at least one STATUS=0 coordinate | Error (`SG_NO_CONTROLLED_COORD`) |
| **SG gradient output** | growth stage requires `LBLUEOUT=.TRUE.` or REPORT carries no free-energy gradient | Error; Info when set on an equilibration stage |
| **SG ICONST syntax** | flag arity (R=2, A=3, T=4; S/D = one coefficient per preceding primitive, D positive), primitives before complexes, integer status, atom index within 1..natoms | Error |
| **SG coverage** | flags outside {R,A,T,S,D} or status outside {0,7} parse but skip deep checks; ICONST comment lines have no documented syntax | Warn (checks skipped) |

## Machine Validation

The rules above are enforced deterministically by `scripts/validate_input.py` (stdlib-only; covers **VASP, CP2K, and LAMMPS** inputs). The skill is installable at project level (`.claude/skills/input_build/`) or user level (`~/.claude/skills/input_build/`); `<skill-dir>` below is wherever the skill is actually installed:

```bash
# Validate one input set
python <skill-dir>/scripts/validate_input.py --incar INCAR --poscar POSCAR --potcar POTCAR --kpoints KPOINTS
python <skill-dir>/scripts/validate_input.py --cp2k input.inp --xyz coord.xyz
python <skill-dir>/scripts/validate_input.py --lammps input.md

# Validate all shipped examples (golden check; VASP + CP2K + LAMMPS)
python <skill-dir>/scripts/validate_input.py --examples-dir <skill-dir>/examples

# Regression tests (stdlib unittest; kpoints tests need ase/spglib/seekpath, skip cleanly without)
python -m unittest discover -s <skill-dir>/tests -v
```

**Required behavior after generating any INCAR:** run the validator on it. ERROR findings must be fixed before returning the file; WARNING findings must be reported to the user with context. `ENCUT_NOT_VERIFIED` means no POTCAR was available — state that ENCUT coverage is unresolved rather than claiming it was checked.

Exit code is 1 on any ERROR finding, so the validator can also gate job-submission scripts.

### Three validation tiers

Validator output uses three separate fields so an input-only check is never
reported as a converged calculation:

| Tier | Values | Meaning |
|---|---|---|
| `syntax` | `PASS` / `FAIL` / `NOT_EVALUATED` | Supported structural syntax and literal keyword values parsed |
| `combination` | `PASS` / `PASS_WITH_WARNINGS` / `INCOMPLETE` / `FAIL` / `BLOCKED` | Deterministic cross-keyword and context-aware rules |
| `physics` | `NOT_EVALUATED` in this validator | Runtime completion and physical convergence require real program output/smoke checks |

The top-level success label is `STATIC_PASS`, not plain `PASS`. `--verified`
can downgrade a matching heuristic WARN to INFO, but it never changes
`physics=NOT_EVALUATED` and is not proof that the calculation ran or converged.
Single-file CLI and examples output also carry coverage metadata/reasons;
missing structure/data context makes `combination=INCOMPLETE` while preserving
the existing rule that only ERROR findings produce exit code 1.

### LAMMPS Phase A 分层证据报告

生成 LAMMPS 输入后，除运行上述静态 validator 外，还须：

- 使用 `schemas/lammps_generation_spec.schema.json` 在生成的 `in.lammps` 旁写入 `generation_spec.json`；
- 在记录前对声明的 `system.data_file` 和 `potential.artifacts[*].path` 计算 SHA256；
- 保留 unresolved 事实及其阻塞层级（L0-L5），而非猜测；
- 调用 `scripts/collect_lammps_evidence.py` 并返回四个报告 artifact（`generation_manifest.json`、`static_validation.json`、`validation_report.json`、`validation_report.md`）；
- 声明不得超过报告的 `highest_level`；
- 作为 Phase A 的一部分，不得修改 `in.lammps`、启动 LAMMPS、提交作业或修复科学参数。

### LAMMPS Phase I 输入解释报告（explain mode）

LAMMPS 输入已渲染且证据报告已生成后，调用 `scripts/explain_lammps.py` 生成输入解释报告：

- explain mode 只读取已有 artifact，不重新渲染、验证或执行；
- 返回 `explain_report.json` 和 `explain_report.md` 两个 artifact；
- 退出码 `0` 表示完整解释，`1` 表示部分解释，`2` 表示用法错误；
- explain mode 从不提升证据等级，其输出是解释而非新证据；
- 作为 Phase I 的一部分，不得修改 `in.lammps`、启动 LAMMPS、提交作业或修复科学参数。

### LAMMPS Phase C 命令模型与多行 Parser

LAMMPS 输入现在通过 `scripts/parse_lammps.py` 结构化解析（纯 stdlib，无运行时语义）：

- parser 合并 `&` 续行、保留引号内 `#`、剥离行内注释，并记录每条命令的源行范围（`Command.span`，1 起始闭区间）；
- `include <path>` 在 allowed root（默认根文件目录）子树内递归展开，路径逃逸（`../../`）、循环、深度超限（默认 8）与缺失文件均 fail-closed：发出 ERROR issue 并标记 `INCOMPLETE`；
- `if`/`jump`/`label`/`loop`/`next` 属动态控制流：parser 发出 `LAMMPS_DYNAMIC_CONTROL_FLOW` WARNING 并将 `ParseResult.completeness` 置为 `INCOMPLETE`，不展开分支、不评估条件、不模拟跳转；
- `fix`/`unfix`、`compute`/`uncompute`、`dump`/`undump` 生命周期被结构化跟踪（`LifecycleRecord`）；`active_lifecycle(result)` 返回文件结束时仍活跃的记录，供 renderer 分配唯一 ID；
- `validate_input.parse_lammps` 是懒加载委托适配器，保持旧 `(commands, raw_text)` 返回形状：简单输入（无 `&`、无引号、无 include）行为不变，`raw_text` 仅为根文件内容（`>>> USER` 扫描不变）；
- parser 不执行 LAMMPS、不调用任何 binary、不提升证据等级；`completeness=INCOMPLETE` 是解析层面的状态，供后续阶段 L1 评估器读取，本身不映射证据等级。

## LAMMPS Scientific Profiles (Phase G)

LAMMPS 复杂任务可通过显式激活科学 profile 获得 L4 验收契约。profile 是声明式 JSON 契约加确定性规则函数，位于 `profiles/lammps/` 下。

**强制规则：**

- profile 只能通过用户显式选择激活，不得从元素、文件名或 pair_style 推断科学意图；
- profile 永不选择 potential、model、charge、电极定义、水刚性、阈值或科学目标，缺失事实标记为 `unresolved` 或 `INCOMPLETE`；
- 多个 profile 可同时激活，不兼容组合（如 `mlff/mace` + `constant_potential`）被 registry 拒绝；
- L4 验收采用 fail-closed 逻辑：缺少必需证据时返回 `INCOMPLETE`，绝不返回 `PASS`；
- MACE 是 `mlff/mace` 子类型，不是独立顶层 profile；
- MLFF 柔性水不自动施加 SHAKE；SHAKE 仅用于用户确认的刚性经典水且 data 文件含 bond/angle 拓扑；
- profile 规则不执行 LAMMPS、不提交作业、不修改 `in.lammps` 内容。

**可用 profile：** `mlff/mace`、`constant_potential`、`interface_water`（PLUMED 和 NEB 留作未来）。

### LAMMPS 官方示例索引（Phase B）

`input_build` 维护 `references/lammps_examples_index.json` 作为 LAMMPS 官方示例的来源溯源数据。该索引只用于为后续 renderer 与 explain mode 提供命令来源标注。索引不复制参数到模板、不选择势函数、不渲染输入、不执行 LAMMPS、不提升证据等级。引用官方示例作为命令来源解释不等于证明用户体系的物理适用性。

## Red Flags

- **Do NOT** generate LAMMPS potentials without user-provided paths
- **Do NOT** set ISMEAR < 0 for molecules/Gamma-only systems or line-mode band structures; ISMEAR=-5 (tetrahedron) is allowed — and often best — for semiconductor/insulator static/DOS runs with a dense automatic k-mesh, but never for relax of unknown-character systems (use ISMEAR=0 + small SIGMA there)
- **Do NOT** omit LDIPOL when IDIPOL is set
- **Do NOT** use `IDIPOL=4` for a slab/wire or workfunction input; it is the all-direction correction intended for an isolated molecule. Use `IDIPOL=1/2/3` along the surface normal. If a slab omits dipole correction, require evidence that both surfaces are symmetric and the normal net dipole is negligible
- **Do NOT** use default ENCUT without checking POTCAR ENMAX
- **Do NOT** forget NELMIN ≥ 4 for metals (prevents premature exit)
- **Do NOT** set LREAL=Auto for small cells (< 20 atoms) or accurate static calculations
- **Do NOT** use HSE06 for geometry optimization without first converging with PBE (expensive)
- **Do NOT** forget to set element-specific LDAUL/LDAUU/LDAUJ when using DFT+U (single value is wrong)
- **Do NOT** run Bader analysis without LAECHG=.TRUE. and boosted NGXF/NGYF/NGZF
- **Do NOT** use NVE production without first verifying energy conservation in a short test run
- **Do NOT** submit AIMD with NCORE commented out — unset NCORE defaults to 1 and wastes an order of magnitude in wall time; always emit an explicit NCORE=4-8
- **Do NOT** set ISIF on MD INCARs (VASP defaults IBRION=0 to ISIF=0); ISIF=2 computes a stress tensor nobody uses, every step
- **Do NOT** run metal-slab + explicit-solvent AIMD on default mixing (AMIX=0.4) — it charge-sloshes and diverges (→ FEXCP downstream); add AMIX=0.02/BMIX=1.0/AMIN=0.01 and keep the trio intact (BMIX=0.01 belongs to static two-step SCF)
- **Do NOT** leave a slab-AIMD cell with huge vacuum "for safety": total periodic vacuum above ~18 Å makes SCF stall via charge sloshing; 15-17 Å total is the verified converging range for Pt/water interfaces
- **Do NOT** set ISMEAR=-5 for band structure calculations on non-automatic k-meshes
- **Do NOT** forget `&KIND` blocks for every element in CP2K (missing → crash)
- **Do NOT** set `PERIODIC XYZ` in `&POISSON` for molecule calculations (use `NONE`)
- **Do NOT** use CP2K MD with `EPS_SCF` > 1.0E-5 (energy drift will be severe)
- **Do NOT** choose `&POISSON PERIODIC` independently of the boundary route: an intentional `CELL XYZ` + `POISSON XY` slab split is allowed, but incompatible 0D/3D combinations give wrong electrostatics
- **Do NOT** use CP2K for systems > 500 atoms without GPW-GAPW or MLFF fallback (too slow)
- **Do NOT** set EFIELD without IDIPOL + LDIPOL (the sawtooth field is silently not applied)
- **Do NOT** assume LSOL works on an unpatched VASP binary — a "SOL:" line alone is not proof: require BOTH the last-step `Solvation Ediel_sol` to be NON-ZERO (constant 0.00000000 = LSOL never coupled, observed on a real 6.5.1 build) AND an LSOL/EB_K solvent parameter block in vasprun.xml
- **Do NOT** use fix electrode/* with plain pppm/ewald — the /electrode kspace variants are mandatory
- **Do NOT** apply fix efield to MLFF systems or uncharged pair styles (no per-atom q → no force)
- **Do NOT** set CP2K EPS_SCCS looser than 1.0E-6 (can silently return zero polarization energy)
- **Do NOT** use METAGGA (r2SCAN/SCAN) without LASPH=.TRUE. (meta-GGA needs non-spherical PAW terms; validator raises ERROR)
- **Do NOT** run LSORBIT without explicit NBANDS (non-collinear SOC ~doubles the band count)
- **Do NOT** define fix shake BEFORE force-adding fixes (fix efield / fix wall/...) — constraints are not satisfied; shake comes last
- **Do NOT** run CP2K metadynamics without a `&COLVAR` under FORCE_EVAL/SUBSYS (the bias has nothing to act on)
- **Do NOT** run LAMMPS `neb` without `fix ... neb` (and keep min_style to quickmin/fire)
- **Do NOT** claim native hydrogen-bond analysis in LAMMPS — route to RDF + MDAnalysis/OVITO post-processing
- **Do NOT** set `velocity ... create 0.0` in LAMMPS — the run aborts with "Attempting to rescale a 0.0 temperature"; use the target (or a non-zero preheat) temperature, or drop `velocity create` when the data file already assigns velocities
- **Do NOT** set IBRION=5/6 without a positive NSW — finite-difference frequencies need `NSW=1`; otherwise VASP performs only a static SCF
- **Do NOT** use the ICHARG=11 fixed-density path workflow for hybrid (HSE) band structures — the hybrid Hamiltonian depends on the orbitals/Fock operator on the regular k-mesh; use a regular mesh + zero-weight path points or the KPOINTS_OPT workflow
- **Do NOT** run `bader` directly on AECCAR0/AECCAR2 — sum first (`chgsum.pl AECCAR0 AECCAR2`), then `bader CHGCAR -ref CHGCAR_sum`; a wrong reference density changes basin partitioning and charge-transfer conclusions
- **Do NOT** pair funcfl-format potentials (e.g. `Al_u3.eam`) with `eam/alloy` or `eam/fs` — funcfl is the single-element format for `pair_style eam`; setfl is for `eam/alloy`/`eam/fs`
- **Do NOT** barostat a non-periodic or vacuum direction (e.g. `fix npt ... z` with `boundary p p f`) — LAMMPS errors out, or silently barostats the vacuum gap
- **Do NOT** combine CP2K OT with k-points (unsupported) — use DIAGONALIZATION for k-point runs
- **Do NOT** set `WAVEFUNCTIONS REAL` with a general (non-Gamma) k-mesh — REAL is only valid at Gamma / special real-Bloch points; use `COMPLEX`
- **Do NOT** accept `LDAU=.TRUE.` with all `LDAUL=-1` or all U_eff = 0 as a DFT+U setup — no U is actually applied; valid only as an explicitly declared control calculation
- **Do NOT** write `ADDED_MOS` as a section (`&ADDED_MOS 10`) — it is a keyword (`ADDED_MOS 10`); the &-form yields an unknown/unclosed section
- **Do NOT** use `MDALGO=3` (Langevin) for slow growth - `INCREM` is only honoured for `MDALGO=1/2`; the run looks fine and never grows the CV
- **Do NOT** count ICONST rows to size `INCREM`: once a complex coordinate (S/C/D) is present the status of every preceding primitive is **ignored**, so `R/R/S` with three `STATUS=0` rows is ONE controlled parameter and takes ONE `INCREM` value
- **Do NOT** treat `D` as a two-reference flag - it is a complex coordinate taking one reference distance per preceding primitive (exponents fixed at 9/14)
- **Do NOT** omit `INCREM` and expect growth: it defaults to 0, which is plain constrained MD
- **Do NOT** run the growth stage without `LBLUEOUT=.TRUE.` - REPORT then holds no free-energy gradient and the trajectory cannot be integrated
- **Do NOT** skip the equilibration stage: integrating from a non-equilibrated start biases the whole profile
- **Do NOT** pick the reacting atom by eye - use `iconst_helper.py candidates` (bonding-distance candidates are auto-excluded from the SUGGESTION) and confirm; a wrong atom index runs a different reaction silently
- **Do NOT** disable LCHARG in AIMD templates "to save IO" - CHGCAR is written once at run end (~50 MB), never per MD step, and is the density-relay carrier for downstream SG-AIMD frames and divergent-system restarts (`ICHARG=1`)
- **Do NOT** submit an `ICHARG=1` run without staging a non-zero CHGCAR in the run directory first - VASP aborts; parent AIMD runs write one by default (`LCHARG=.TRUE.` in `vasp_md`)
