# L6 · LAMMPS 恒电位电极（fix electrode/conp）

**演示要点**：双电极恒电位差 MD（ELECTRODE 包，Ahrens-Iwers 等）。

- kspace 必须用 `/electrode` 变体（`pppm/electrode`），普通 pppm 会直接报错——validator 已设为 ERROR 级
- `ffield yes` 有限场模式：保持 `boundary p p p`，**不要**再加 `kspace_modify slab`
- `couple top v_v symm on`：对电极耦合 + 电荷反称；`v_v` 变量实现 0→2 V 电位扫描
- `eta=1.805`：电极电荷高斯展宽的倒数宽度（1/Å，C/Au 典型 1.8–2.0）
- 工作流：先在 0 V 平衡，再扫电位；监控 `c_qbot`/`c_qtop` 电极电荷收敛
- 模板：`base_templates/lammps_conp.in`（含 conq 恒电荷 / thermo 热恒电位计备选）
