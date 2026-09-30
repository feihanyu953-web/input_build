## L3: Al FCC Bulk — NPT with EAM

**Task:** NPT equilibration and production for Al FCC bulk using an EAM potential.

**System:** 4 Al atoms, FCC bulk (from `system_Al.data`).

**Key settings:**
- `pair_style eam`, `pair_coeff * * Al_u3.eam`（Al_u3.eam 为 funcfl 单元素格式：pair_coeff 仅 3 参数、不带元素符号；setfl 格式如 `*.eam.alloy` 才配 `eam/alloy` 且必须带元素符号）
- Iso pressure: 1.0 bar
- `Tdamp = 0.05` ps, `Pdamp = 0.5` ps
- Equilibration: 10 ps NPT
- Production: 100 ps NPT (continues NPT)
- Boundary: `p p p`

**Files:** `input.npt`, `system.data` (copied from `system_Al.data`)
