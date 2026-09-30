# L8 · LAMMPS + PLUMED（fix plumed）

**演示要点**：用 PLUMED 做 CV 监控 / 增强采样（metadynamics 等）的 LAMMPS 接口。

- 语法：`fix pl all plumed plumedfile plumed.dat outfile p.log`（需 PLUMED 包编译）
- 同一时刻只能有 **一个** fix plumed；其 group-ID 被忽略，恒为 `all`
- `fix_modify energy/virial` 对该 fix 默认 yes（偏置计入能量与压强）
- CV / 偏置写在 `plumed.dat`（本例：DISTANCE CV + PRINT；metadynamics 变体见注释）
- 重启时 LAMMPS 侧 read_restart 之外，PLUMED 侧还需要在 plumed.dat 顶部加 `RESTART`

对应模板：`base_templates/lammps_plumed.in`。
