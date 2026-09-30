# VASP Workflow (input_build reference)

## VASP Code-Specific Follow-ups

生成 VASP 输入时,Step 3 通用十问之外按需追加的问题。本节是 SKILL.md
code-specific follow-ups 的完整版;SKILL.md 仅保留高频摘要,生成 VASP 输入前必读。

### KPOINTS
- KPOINTS density? -> gamma-centered vs Monkhorst-Pack

### POTCAR
- POTCAR set? -> PBE / PAW / GGA

### Implicit solvation (VASPsol)
- Implicit solvation (VASPsol)? -> `solvation` modifier (LSOL/EB_K/TAU);
  **confirm the VASP binary is patched**; vacuum-first workflow

### Applied field / charged slab
- Applied field / charged slab? -> `efield` modifier (EFIELD; **the dipole
  modifier is mandatory**) and/or NELECT

### Work function
- Work function? -> `LVHAR` (VASP 6+) or `LVTOT`; dipole correction
  (`IDIPOL`/`LDIPOL`) for slabs

### ELF
- ELF? -> confirm `NPAR=1`; optional FFT grid boost (`NGXF/NGYF/NGZF`)

### Optics
- Optics? -> NSCF (`ISTART=1`, `ICHARG=11`) vs SCF + `LOPTICS`; `NBANDS` boost

### Dielectric
- Dielectric? -> static (`LEPSILON`) vs ionic contribution (`IBRION=8`,
  `LPEAD`); insulator smearing

### SOC (spin-orbit coupling)
- SOC (spin-orbit coupling)? -> `soc` modifier (LSORBIT+SAXIS); heavy elements;
  **remind NBANDS ~2x scalar**, LMAXMIX 4/6, ENCUT 1.3–1.5×

### meta-GGA
- meta-GGA? -> `metagga` modifier (r2SCAN recommended; SCAN alternative);
  VASP ≥ 6.2.0; **LASPH mandatory**

### Phonon
- Phonon? -> phonopy finite-displacement workflow (`vasp_phonopy` single point)
  vs DFPT (`IBRION=8`)

## Slow-growth AIMD (SG-AIMD)

Free-energy profile along a geometric parameter xi, obtained by constrained MD
whose constraint value grows linearly every step; the mean constraint force is
integrated along xi afterwards. Official pages:
[Slow-growth approach](https://www.vasp.at/wiki/index.php/Slow-growth_approach),
[Constrained MD](https://www.vasp.at/wiki/index.php/Constrained_molecular_dynamics),
[ICONST](https://www.vasp.at/wiki/index.php/ICONST),
[INCREM](https://www.vasp.at/wiki/index.php/INCREM),
[LBLUEOUT](https://www.vasp.at/wiki/index.php/LBLUEOUT),
[REPORT](https://www.vasp.at/wiki/index.php/REPORT),
[MDALGO](https://www.vasp.at/wiki/index.php/MDALGO).

### Official facts

| Item | Fact |
|---|---|
| Thermostat | `INCREM` is only honoured for `MDALGO=1` (Andersen) or `2` (Nose-Hoover). `MDALGO=3` (Langevin) does not drive slow growth. |
| Growth rate | `INCREM` is a real array, default **0** - an absent tag means no growth (plain constrained MD). Each `STATUS=0` parameter is increased by its `INCREM` value every MD step. |
| Value count | One `INCREM` value per controlled parameter. |
| Gradient output | `LBLUEOUT=.TRUE.` writes the free-energy gradient to `REPORT`. Without it the integration is impossible. |
| ICONST scope | Read only for `IBRION=0` (MD). Atom indices are 1-based in POSCAR element-block order. |
| Build | `MDALGO`/`ICONST` need `-Dtbdyn` (default since VASP 5.4.4). |

### The arity trap

A complex coordinate (`S`, `C`, `D`, `IS`, `IZ`) must follow every primitive, and
**once one exists the status of every preceding primitive is ignored** - the
primitives are only its basis. So for a proton-transfer difference coordinate:

```
R 17 18 0
R 22 18 0
S 1 -1 0
```

there are three `STATUS=0` rows but only **one** controlled parameter, hence one
`INCREM` value. Counting rows instead of controlled parameters is the classic
mistake; `SG_INCREM_ARITY` enforces the correct count.

`D` (coordination number) is a complex coordinate too: its coefficients are one
reference distance per preceding primitive, with exponents fixed at 9 and 14. It
is not fixed at two references - the official example shows two only because two
`R` lines precede it.

### INCREM sign

The official pages neither permit nor forbid a negative `INCREM`; the type is a
real array, so a negative value is syntactically legal and simply means the CV
decreases (bond formation, reverse desorption). The validator therefore does not
warn on negative values. When applying slow growth to a new system for the first
time, run a short small-system test and confirm from `REPORT` that the CV moves
in the intended direction before committing to a long trajectory.

### Torsion sign convention

The helper evaluates `T` (torsional angle) with the IUPAC convention: viewed
down the central bond from the second toward the third atom, clockwise rotation
from the first to the fourth atom is positive (the praxeolitic formulation).
Declare `--xi`/`--xf` values measured with the same convention (ASE, OVITO and
most structure viewers use it). VASP's own internal torsion sign for the ICONST
`T` flag is not documented on the wiki pages above - before driving a torsion
CV, do one short equilibration step and confirm from `REPORT` that VASP's
monitored value matches the helper's reported xi (magnitude AND sign).

### Two-stage protocol

1. **Equilibration** - `INCREM` absent/zero, `LBLUEOUT=.FALSE.`: constrained MD
   holding the CV at its initial value until temperature and constraint force
   are stationary.
2. **Growth** - `INCREM` set, `LBLUEOUT=.TRUE.`, restarted from the equilibrated
   geometry, sharing the same ICONST.

Generate both stages plus ICONST with:

```bash
python scripts/iconst_helper.py candidates --poscar POSCAR --species H --acceptor 22
python scripts/iconst_helper.py render --poscar POSCAR \
    --cv "R 17 18" --cv "R 22 18" --cv "S 1 -1" \
    --xi -0.736 --xf 0.76 --nsw 4000 --potim 1.0 \
    --out ICONST --emit-incar \
    --template base_templates/vasp_slowgrowth.incar \
    --incar-growth INCAR_growth --incar-equil INCAR_equil
```

The helper never picks atoms, CV definitions or growth rates: it ranks candidate
atoms by real interatomic distance (candidates bonded to the acceptor, below
1.2 A, are excluded from the SUGGESTION with an explicit NOTE - they are the
acceptor's own atoms, not transferring ones), verifies the declared initial
value against POSCAR geometry (tolerances 0.1 A for distances, 2 deg for
angles/torsions, 0.05 for coordination numbers), does the INCREM arithmetic and
renders the files.

### Density relay (CHGCAR staging)

The rendered equilibration INCAR carries `ICHARG=1`: the run starts from a
staged CHGCAR instead of the atomic-superposition guess. Rationale: post-AIMD
metal/water snapshots can diverge from the superposition guess (SCF blow-up,
downstream FEXCP; observed twice at the first ionic step on a Pt/K/water
lineage before the relay was adopted), while a converged density from a
chemically similar geometry cures it (locally verified: the equil first
ionic step converged to the parent-production energy range from a 2.2 A-away
pre-relaxation density).

Relay chain: parent AIMD writes an end-of-run CHGCAR (`vasp_md` default
`LCHARG=.TRUE.`) -> cluster-side `cp` into the frame dir (same discipline as
POTCAR copying) -> the equil reads it (`ICHARG=1`) -> the equil writes its own
(`LCHARG=.TRUE.`) -> the growth stage reads that geometry-matched one.

Gate before every `ICHARG=1` submit: the CHGCAR is present AND non-zero (VASP
aborts on a missing file; a 0-byte remnant of a killed job is equally fatal).

Boundary conditions: same ENCUT and same POTCAR lineage as the CHGCAR
producer. A follow-up at a different ENCUT (e.g. 520 eV MLFF label
single-points) must NOT reuse the CHGCAR - that path uses the static two-step
SCF (`ICHARG=0`). Fallback when no parent CHGCAR exists (killed job, older
lineage): run a static SCF on the starting geometry first (`IBRION=-1`,
`NSW=0`, `LCHARG=.TRUE.`) and stage that - the "two-phase init" script
pattern.

### Practice from the paper kb

| record_id | Paper | Reusable numbers |
|---|---|---|
| `methods-0529` | Yang2022 | Slow growth + Jarzynski: 10 independent trajectories, CV rate 0.0001-0.001 /step, 3-9 ps each, 300 K. Convergence test: halve the rate, energy difference < 0.1 eV. |
| `methods-0008` | Chen2026_AuCPMD | 5 independent runs per reaction; first 20 ps with the CV fixed (equilibration); difference-coordinate CV precedent `d(O-H) - d(H-Au)`. Authors state slow growth is a qualitative estimate and does not guarantee the minimum-energy path. |
| `methods-0101` | Mou2025 | Nose-Hoover, 0.5 fs timestep, slow-growth step 0.0005 A (C-N bond formation). |

### Not covered by input_build v1

Multi-trajectory Jarzynski batches (do it by hand, following `methods-0529`),
`IRCCAR` and the path coordinates `IS`/`IZ`, and deep checks for the
`W/M/B/P/X/cX/LR/LA/LV` flags (they parse, but arity and geometry checks are
skipped; each skip is reported as a WARN on top of an otherwise-clean verdict).
