# L5 · LAMMPS 外加电场（fix efield）

**演示要点**：电解液体系在 z 向匀强电场下的 NVT MD。

- `fix efield` 只作用于带电原子（力 = qE），pair style 必须含电荷（`atom_style full` + coul）
- 用 `variable ramp` 缓升电场，避免瞬时强场打坏体系
- units real 下电场单位 V/Å，0.05–0.1 V/Å 已属强场
- MLFF 模型大多不输出 per-atom 电荷，**不要**对 MLFF 直接套 fix efield

对应 snippet：`modifiers/lammps/fix_efield.snip`。
