# KPOINTS Generation (input-build reference)

> Read this when generating KPOINTS or band paths (VASP & CP2K). Routing and hard rules live in ../SKILL.md.

## KPOINTS Generation (VASP & CP2K)

### Design: Unified Exact Generation via `kpoints_helper.py`

KPOINTS generation uses **`scripts/kpoints_helper.py`** (relative to this skill's directory — `<skill-dir>` = `.claude/skills/input_build/` at project level or `~/.claude/skills/input_build/` at user level) as the unified backend. The script:

1. **Auto-detects** missing dependencies (`ase`, `spglib`, `seekpath>=2.0`)
2. **Never auto-installs on import** — a missing dependency only produces an error report with install instructions. Installing happens exclusively via the explicit `python scripts/kpoints_helper.py --bootstrap-deps` command, which installs pinned, tested versions (`ase==3.29.0`, `spglib==2.7.0`, `seekpath==2.2.1`) with visible output
3. **Always uses `seekpath`** for exact space-group-aware paths
4. **Exits with a clear error** if dependencies are missing — there is deliberately **no fallback** to approximate built-in tables (wrong k-points are worse than none)

**Why seekpath by default?**
- It analyzes atomic positions via `spglib` to determine the **exact space group** (230 possibilities)
- It returns **standardized high-symmetry k-paths** endorsed by the International Union of Crystallography
- It eliminates AI misjudgment of cubic P/I/F, low-symmetry cells, and non-standard settings

### Why Not Pure AI?

AI can make **calculation errors** in:
- Trigonometric functions (α, β, γ → reciprocal lattice)
- Ceiling/floor rounding (mesh sizing)
- Edge-case crystal systems (monoclinic, triclinic lattice recognition)
- Distinguishing cubic P/I/F from lattice parameters alone

**Solution:** AI handles **decisions** (MP vs Gamma, k-spacing choice) → script handles **exact math** (mesh numbers, space-group paths).

### AI Inference Logic (Built into Skill)

#### Step 1: Read POSCAR → Infer Lattice Type

```
Read lattice vectors a, b, c, α, β, γ
Compare ratios and angles:
  a=b=c, α=β=γ=90°     → Cubic (subtype determined by seekpath)
  a=b≠c, α=β=90°,γ=120° → Hexagonal
  a=b≠c, α=β=γ=90°     → Tetragonal
  a≠b≠c, α=β=γ=90°     → Orthorhombic
  a≠b≠c, α=γ=90°≠β     → Monoclinic
  Otherwise              → Triclinic
```

#### Step 2: Auto-Select Scheme

| Lattice Type | Auto Scheme | Reason |
|-------------|-------------|--------|
| Hexagonal | **Gamma-centered** | MP offset breaks 6-fold symmetry (VASP wiki: KPOINTS) |
| fcc / fcc-orthorhombic (centering F) | **Gamma-centered** | Preserves reciprocal point-group symmetry; detected via spglib centering, not lattice lengths |
| Slab / 1D / 0D | **Gamma-centered** | Vacuum direction only Γ point |
| Metal (other bulk) | **Monkhorst-Pack** | Offset gives more uniform Fermi sampling |
| Other bulk (cubic-P/I, tetragonal, orthorhombic) | **Monkhorst-Pack** | Standard; fewer k-points for same accuracy |

> Scheme selection uses `spglib` Bravais centering (first letter of the Hermann-Mauguin symbol), not `a=b=c` guesses — cubic P/I/F are indistinguishable from lattice parameters alone.

#### Step 3: Auto-Select k-spacing

| System Type | Default k-spacing | Rationale |
|------------|-------------------|-----------|
| Metal | 0.18 Å⁻¹ | Dense for Fermi surface |
| Semiconductor / insulator | 0.22 Å⁻¹ | Moderate; band gap less sensitive |
| Surface / slab | 0.20 Å⁻¹ (in-plane only) | z = 1×1 always |
| Molecule / cluster | — | 1×1×1 Gamma-only |

#### Step 4: Compute Mesh (Script Formula)

```
b₁, b₂, b₃ = reciprocal lattice vectors INCLUDING the 2π factor
             (b₁ = 2π·(a₂×a₃)/V etc.; physics/VASP convention, units Å⁻¹)
|b₁|, |b₂|, |b₃| = their magnitudes

k₁ = ceil(|b₁| / spacing)        # identical to kpoints_helper.py compute_kmesh()
k₂ = ceil(|b₂| / spacing)        # k-spacing = distance between adjacent k-points (Å⁻¹)
k₃ = ceil(|b₃| / spacing)        # result is always ≥ 1

If z-axis has vacuum (> 5 Å): k₃ = 1
```

#### Step 5: Line-Mode for Band Structure (seekpath Exact)

For band structure, `kpoints_helper.py` calls **seekpath** to:
1. Analyze atomic positions → determine exact space group
2. Query standardized k-path for that space group
3. Generate line-mode KPOINTS **in the reciprocal basis of the original POSCAR cell** (`get_path_orig_cell`), so conventional cells (e.g. fcc conventional cell) get paths that match their POSCAR

**Supercells vs. conventional cells (fail closed only for true supercells).** seekpath sets `is_supercell` / emits `SupercellWarning` for *any* cell larger than the primitive — including the **standard conventional cell of a centered lattice** (fcc 4-atom, bcc 2-atom, base-centered 2-atom, …). For such conventional cells the orig-cell path labels **are** the crystal's true conventional-BZ high-symmetry points (the standard fcc Γ-X-W-K-Γ-L path, etc.) — physically correct and standard practice. The helper therefore standardizes the cell with spglib and compares volumes:

- `V_input ≈ V_standard_conventional` → centered conventional cell → path written (an INFO note explains the `is_supercell` flag);
- `V_input ≥ 2× V_standard_conventional` → **repetition supercell** → the first BZ is folded and the seekpath labels do **not** correspond to supercell-BZ high-symmetry points, nor is the path a substitute for band unfolding → the helper **refuses to write** and lists the three valid options:

1. **Primitive-cell band** — reduce to the primitive cell (spglib `find_primitive` / phonopy / VASPKIT) and run the band on it;
2. **Folded supercell band** — construct a Γ-anchored path for the supercell BZ yourself (the supercell BZ is folded; seekpath labels do not apply);
3. **Band-unfolding workflow** — run the supercell band and unfold onto the primitive BZ (BandUP / PyProcar / VASPKIT).

`--allow-supercell` overrides the refusal, with a loud warning that the labels refer to the primitive BZ.

**Case study (2026-10, Janus MoSSe 4x4 supercell -- bypassing the helper has consequences).**
A Pd-MoSSe SAC reproduction hand-wrote a line-mode band path by copying the
literature primitive-cell coordinates G-M-K-G = (0,0,0)-(0.5,0,0)-(1/3,1/3,0)-(0,0,0)
into the KPOINTS sitting next to the **4x4 supercell** POSCAR. In supercell
reciprocal coordinates those points are (2,0,0) and (4/3,4/3,0) of the primitive
lattice: the path actually sampled G-M-G-K-G of the primitive BZ at quarter
scale, while the figure was labeled G-M-K-G. The job also OOM-killed four times
(unrelated memory issue), which delayed discovery of the mislabel until the k
coordinates were checked against the cell. kpoints_helper.py would have refused
this exact input (repetition supercell; "labels refer to the primitive BZ").
Fix applied: divide the M/K coordinates by the supercell multiplicity
(M -> (0.125,0,0), K -> (1/12,1/12,0)) so the path samples the primitive
G-M-K-G at true scale, and rerun the band job. Rule of thumb: whenever the
POSCAR is an N x N supercell and the path coordinates come from a 1x1 paper,
divide the path coordinates by N (folding guarantees equivalent primitive points).

**Tolerance-sensitive structures (fail closed).** The Bravais classification depends on `symprec`: a slightly distorted cell can be monoclinic at 1e-5 but hexagonal at 1e-4 (see `examples/K5_hex_band`). The helper probes the classification at `symprec` and `symprec ×10`; if they disagree it **refuses to write** and asks you to re-run at a stable `--symprec` (or explicitly override with `--allow-tolerance-sensitive`). If you declare the expected family via `--lattice` or a keyword in the POSCAR comment line (`hexagonal`, `cubic`, …) and it conflicts with the identified Bravais family, the helper **exits non-zero** — a declared-vs-identified conflict is never overridden silently.

**No basis-mismatch fallback.** `seekpath.get_path_orig_cell` requires seekpath ≥ 2.0. If it is unavailable, the helper does **not** fall back to `seekpath.get_path()` (standardized primitive basis — silently wrong for conventional cells); it exits non-zero and tells you to upgrade.

Example output for Si (Fd-3m, No.227):
```
Space group: 227 (Fd-3m)
Bravais lattice: FCC
Path: Γ-X-W-K-Γ-L-U-W-L-K
```

### Usage

```bash
# <skill-dir> = the directory where this skill is installed
# (project level: .claude/skills/input_build/ ; user level: ~/.claude/skills/input_build/)

# Automatic mesh (Monkhorst-Pack or Gamma)
python <skill-dir>/scripts/kpoints_helper.py --poscar POSCAR --spacing 0.18 --scheme AUTO

# Band structure (exact seekpath path, original-cell coordinates)
python <skill-dir>/scripts/kpoints_helper.py --poscar POSCAR --band-structure --npoints 20

# Band structure with explicit symmetry tolerance (distorted cells) and a
# declared crystal family that must match the identified Bravais lattice
python <skill-dir>/scripts/kpoints_helper.py --poscar POSCAR --band-structure --symprec 1e-4 --angle-tolerance -1.0 --lattice hexagonal

# Supercell: refused by default; explicit opt-in only
python <skill-dir>/scripts/kpoints_helper.py --poscar POSCAR --band-structure --allow-supercell

# One-time explicit dependency install (pinned, tested versions)
python <skill-dir>/scripts/kpoints_helper.py --bootstrap-deps
```

| Flag | Meaning |
|------|---------|
| `--symprec` (default 1e-5) | Symmetry tolerance passed to seekpath/spglib; try 1e-4 for slightly distorted cells. The helper probes `symprec ×10` and refuses if the classification changes |
| `--angle-tolerance` (default -1.0) | Angle tolerance (degrees) passed through to seekpath/spglib; -1.0 = spglib automatic |
| `--lattice` | Declare expected crystal family (cubic/hexagonal/tetragonal/orthorhombic/monoclinic/rhombohedral/triclinic); any conflict with the identified Bravais lattice aborts with non-zero exit |
| `--allow-supercell` | Opt-in bypass of the supercell refusal (labels refer to the primitive BZ) |
| `--allow-tolerance-sensitive` | Opt-in bypass of the symprec-sensitivity refusal |
| `--bootstrap-deps` | Explicit one-time install of pinned `ase`/`spglib`/`seekpath`; the ONLY code path that runs an installer |

**Dependencies are never auto-installed on import.** On a missing dependency the script prints install instructions and exits non-zero.

### Behavior When the Script Cannot Run

The script requires `ase`, `spglib`, `seekpath>=2.0`. If they are missing (e.g., offline environment), the script **exits with an error** — install them via `python scripts/kpoints_helper.py --bootstrap-deps` (pinned versions) or manually (`uv pip install ase spglib seekpath` or `pip install ...`).

Without the script, AI may still draft a uniform-mesh KPOINTS **with explicit calculation steps shown in comments** (reciprocal vectors, |bᵢ|, ceil division), so the user can verify the math. Do **not** hand-derive band-structure paths for conventional cells, supercells, or low-symmetry crystals — use the script (see Step 5 above for why).

