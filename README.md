# input_build

Deterministic input-file generation for **VASP / LAMMPS / CP2K**, packaged as an
AI-agent skill with a strict machine-validation gate.

**中文简介**：面向 VASP / LAMMPS / CP2K 计算的输入文件生成技能（AI agent
skill）。`SKILL.md` 驱动 AI agent 按"自动探测结构 → 材料感知默认值 → 最小提问
协议 → 模块化带注释输出"的流程生成输入文件，随后由确定性校验器
`scripts/validate_input.py`（~70 条规则，覆盖三种代码）把关：**ERROR 清零才允许
交付**。核心零第三方依赖，测试离线可跑。

> **Legal notice**: this skill generates *input control files only*. It does not
> and will not distribute pseudopotentials (e.g. VASP POTCAR), vendor data
> files, or any other licensed third-party content — bring your own.

## What it generates

| Code | Tasks covered (one base template each) |
|---|---|
| **VASP** (16) | relax · scf · md · slow-growth AIMD · dos · band · freq · phonopy · neb · bader · hse · dftu · workfunction · elf · optics · lepsilon |
| **CP2K** (14) | scf · geo_opt · cell_opt · md · neb · band · dos · phonon · metadyn · workfunction · dftu · elf · hirshfeld · optics |
| **LAMMPS** (8) | md · nve · minimize · mlff · conp (constant-potential electrode) · plumed · neb |

Modifiers overlay small patches on top of a base template — dispersion (D4/TS),
DFT+U, dipole correction, SOC, solvation (VASPsol), efield, optics, metagga,
magnetic ordering for VASP; LAMMPS snippets for `fix efield/shake/wall`,
Langevin ensemble, temp ramp, `dump full`, RDF/MSD/hbond analysis.

## Highlights

- **Deterministic validation gate** — `scripts/validate_input.py` implements the
  SKILL.md rule table (~70 rules) for all three codes; exit code 1 on any ERROR,
  so it can gate job-submission scripts too. Rules cover the classic failure
  modes: tetrahedron smearing on relax, `IBRION=5` without `NSW`, hybrid band
  workflows with `ICHARG=11`, Bader without `chgsum.pl`, funcfl/eam.alloy
  pairing, barostat on a non-periodic direction, OT + k-points in CP2K,
  all-zero DFT+U, `&ADDED_MOS` used as a section, and slow-growth AIMD
  (ICONST syntax/arity, INCREM parsing, MDALGO compatibility, LBLUEOUT).
- **Material-aware defaults** — metal slab / oxide surface / oxide bulk /
  molecule classes drive ENCUT, DFT+U `LMAXMIX`, and magnetic-moment defaults;
  auto-detection reads your structure first and never asks about what it
  already knows.
- **Machine-readable template routing** — `base_templates/INDEX.json` maps task
  → template → modifier list; the "later modifier wins" overlay semantics are
  enforced by tests, and every generated input must re-pass the validator.
- **LAMMPS engineering loop** — evidence collection (Phase A), provenance index
  of official LAMMPS examples (Phase B, 414 entries), structured input parser
  (Phase C), byte-stable deterministic renderer with a generation spec (Phase D),
  scientific profiles (Phase G: MLFF/MACE, interface water, constant-potential
  electrode), and a read-only explainer for existing inputs (Phase I).
- **Version gating** — VASP ≥ 6.3 (verified on 6.5.1 + VTST), CP2K ≥ 2024.3
  (verified on 2026.1, with 2026.2 behavior gates), LAMMPS ≥ 22Jul2025
  (`reax/c` → `reaxff`); templates carry explicit version-gate comments where
  behavior changed across versions.
- **48 golden examples** — every shipped example passes the validator
  (`STATIC_PASS`), and the suite doubles as a regression harness.
- **Zero-dependency core** — Python ≥ 3.11 standard library only; the full test
  suite (821 tests) runs offline.

## Repository layout

```
input_build/
├── SKILL.md            # the agent-facing workflow — start here
├── base_templates/     # 38 per-task base inputs + INDEX.json routing table
├── modifiers/          # overlay snippets (dispersion, DFT+U, dipole, efield, SOC, fix_* …)
├── profiles/           # LAMMPS scientific profiles (mlff/mace, interface_water, constant_potential)
├── references/         # code-specific deep dives (VASP / CP2K / LAMMPS / kpoints)
├── schemas/            # JSON Schema (draft 2020-12) for specs, profiles, examples index
├── scripts/            # validate_input.py (the gate), LAMMPS renderer/parser/evidence, kpoints helper
│   └── smoke/          # optional integration tests against real simulation binaries
├── tests/              # 34 stdlib-unittest files (~820 tests), offline
├── examples/           # 48 golden examples: 20 VASP / 15 CP2K / 9 LAMMPS / 4 kpoints
└── tools/              # maintainer sync + leak-gate script (not part of the skill)
```

## Requirements

- **Python ≥ 3.11** (core uses `enum.StrEnum`). Everything except the kpoints
  helper is standard library only.
- Optional: `ase` + `spglib` + `seekpath` for `scripts/kpoints_helper.py`
  (band-path generation); the kpoints tests skip cleanly without them.
- Simulation codes are only needed for the optional smoke tests — the skill
  itself generates and statically validates inputs.

## Install

```bash
git clone https://github.com/feihanyu953-web/input_build.git
```

- **Claude Code** — user level: put the repo at `~/.claude/skills/input_build`;
  project level: `.claude/skills/input_build` inside your project.
- **ZCode** — put the repo at `~/.zcode/skills/input_build`, or point
  `-ClaudeSkillsRoot` at a directory containing it.
- **Other agents** — any runtime that can read `SKILL.md` as instructions can
  use the workflow; the scripts and tests are plain Python.

## Usage

Ask your agent for input files, or use the slash command:

```
/input_build
"Generate VASP relaxation inputs for NH3 on Pt(111)"
```

The agent will:

1. read your structure file (POSCAR / CONTCAR, LAMMPS data file, XYZ/PDB),
2. auto-detect composition, dimensionality, vacuum, adsorbate asymmetry, metal
   vs oxide, magnetic elements — and never ask about what it already knows,
3. ask only the questions auto-detection cannot answer (a bounded
   10-question protocol: code + task, dispersion, DFT+U, precision, hardware,
   magnetic ordering, surface normal, boundary periodicity, potential files,
   program version),
4. emit a module-grouped, line-annotated INCAR / `in.lammps` / CP2K input,
5. run `scripts/validate_input.py` on the result and fix every ERROR before
   handing the files over.

### Validator CLI

```bash
# one input set
python <skill-dir>/scripts/validate_input.py --incar INCAR --poscar POSCAR --potcar POTCAR --kpoints KPOINTS
python <skill-dir>/scripts/validate_input.py --cp2k input.inp --xyz coord.xyz
python <skill-dir>/scripts/validate_input.py --lammps input.md

# all shipped examples (golden check; VASP + CP2K + LAMMPS)
python <skill-dir>/scripts/validate_input.py --examples-dir <skill-dir>/examples
```

Exit code is 1 on any ERROR finding, so the validator can gate submission
scripts directly.

## Tests

```bash
python -m unittest discover -s <skill-dir>/tests -v
```

~820 tests, standard library only, no network access. Kpoints tests need
`ase`/`spglib`/`seekpath` and skip cleanly when those are absent.

## Smoke tests (optional, needs real binaries)

`scripts/smoke/` runs 18 physics-assertion cases against your own VASP / CP2K /
LAMMPS installations (lattice relaxation, H2 frequency, VASPsol solvation,
CP2K geometry optimization / Hirshfeld / metadynamics, LAMMPS EAM NVE/NVT/NPT,
SHAKE, plumed, MLFF, …):

```bash
cd <skill-dir>/scripts/smoke
cp smoke_env.example.yaml smoke_env.yaml   # then edit the paths for your machine
python run_smoke.py --list
python run_smoke.py --only <case-id>
```

Each case runs the real code and asserts *physics* (energies, temperatures,
diffusion, bond angles), not just exit codes.

## Ecosystem

This skill is part of a small computational-materials toolchain:

| Repo | Role |
|---|---|
| **emcbuild** | build DFT/MD starting structures (slabs, heterojunctions, electrolyte boxes) → feeds POSCAR / `system.data` into input_build |
| **cluster-connect** | SSH bridge to HPC (Slurm/PBS, sandboxed file transfer) — submits what input_build generates |
| **vaspkit-remote** | remote VASP post-processing on the cluster (bands/DOS/workfunction/MD) |
| **lammps-analyze** | local trajectory analysis for the MD runs input_build sets up |

Each works standalone; only the integrations listed above require the partner
skill.

## Encoding & language

Documentation mixes English and Chinese (中文) throughout; every file is UTF-8
without BOM. Open and edit files as UTF-8.

## Maintainers

`tools/make_release.py` syncs a development copy of the skill into this repo
and runs a leak gate that fails on any machine-specific path or private
identifier:

```bash
python tools/make_release.py --src /path/to/your/dev/input_build
python tools/make_release.py --check-only
```

## License

[MIT](LICENSE). The skill generates input files only and distributes no
pseudopotentials or vendor data (see the legal notice above and the notice in
`SKILL.md`).
