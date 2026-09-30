## L1: Al FCC Bulk — MD with EAM

**Task:** NVT molecular dynamics of Al FCC bulk using an EAM potential.

**System:** 4 Al atoms, FCC bulk (from `system_Al.data`).

**Key settings:**
- `pair_style eam`, `pair_coeff * * Al_u3.eam`（Al_u3.eam 为 funcfl 单元素格式：pair_coeff 仅 3 参数、不带元素符号；setfl 格式如 `*.eam.alloy` 才配 `eam/alloy` 且必须带元素符号）
- Timestep: 0.5 fs (template default)
- Temperature: 300 K
- Equilibration: 10 ps NVT (`Tdamp = 0.05` ps)
- Production: 100 ps NVT
- Boundary: `p p p`

**Files:** `input.md`, `system.data` (copied from `system_Al.data`)
