# L7 · H₂O/Pt 界面 MLFF MD（MACE）

**演示要点**：`lammps_mlff.in` 模板的落地形态——MACE 模型做界面水 NVT 生产。

- `pair_coeff * * mace.model H O Pt` 的元素顺序 = data 文件 type 顺序（1=H 2=O 3=Pt），顺序错是 MLFF 第一静默错误源
- MLFF 无 kspace、无键拓扑（`atom_style atomic`）
- dump 带 `fx fy fz`：支撑主动学习/误差评估工作流
- 生产前紧盯前 10 ps 能量/温度——MLFF 失效通常表现为突发性能量爆炸
- 与 L2（MACE minimize）、L4（MACE NVE）构成完整 MLFF 工作流示例组
