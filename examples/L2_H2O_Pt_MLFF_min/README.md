## L2: H2O-Pt Interface — Minimization with MLFF

**Task:** Multi-stage energy minimization of a Pt + H2O interface using a MACE potential.

**System:** Pt slab + H2O molecules (27 atoms total, from `system_H2O_Pt.data`).

**Key settings:**
- `pair_style mace`, `pair_coeff * * mace.model H O Pt`
- Minimization only (no MD)
- Stage 1: `sd` (steepest descent)
- Stage 2: `cg` (conjugate gradient)
- Output: `minimized.data`

**Files:** `input.minimize`, `system.data` (copied from `system_H2O_Pt.data`)
