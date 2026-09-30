# L9 · LAMMPS NEB（fix neb + neb 命令）

**演示要点**：LAMMPS 副本式（replica）NEB 最小工作流。

- 必须同时有 `fix 1 all neb 1.0`（Kspring，units metal 下 eV/Å²）和 `neb etol ftol N1 N2 Nevery final coords.final`
- `min_style` 只能是 **quickmin 或 fire**（cg/sd/hftn 与 NEB 不兼容）
- `atom_modify map array`（或 yes）是 fix neb 的硬性要求
- NEB timestep 可取常规 MD 的 ~10 倍（本例 0.005 ps = 5 fs）
- file-style 终态坐标 `coords.final`：首行为所列原子数，随后每行 `ID x y z`
  （只需列出发生移动的原子；ID 与 data 文件一致；本例为占位样例）
- **启动方式**：`mpirun -np N*M lmp -partition NxM -in in.neb`
  （N 个副本 × 每副本 M 核；如 8 副本单核：`-partition 8x1`）

对应模板：`base_templates/lammps_neb.in`。
