# L9 · LAMMPS NEB（fix neb + neb 命令）

**演示要点**：LAMMPS 副本式（replica）NEB 完整工作流，含端点最小化链。
**实测锚点**：Cu adatom 在 Cu(100) 四重空位间跳跃（hop = 2.553 Å = a/√2），
m9 集群 LAMMPS 30Mar2026（REPLICA 包），8 像 × 8 核，墙钟约 1 秒，
E‡ = 0.5015 eV（对称 bridge 路径，EBF = EBR），50 + 57 步收敛（2026-10-31 实测）。

## 硬性规则（本例全部遵守）

- 必须同时有 `fix ID group neb Kspring`（Kspring，units metal 下 eV/Å²）和
  `neb etol ftol N1 N2 Nevery <file-style> <file>`
- `min_style` 只能是 **quickmin 或 fire**（cg/sd/hftn 的 line search 无法跨副本
  同步，与 NEB 不兼容）
- `atom_modify map array` 是 fix neb 的硬性要求
- 判敛看 **ftol**（含弹簧力）；etol 不含，可置 0 只用力判敛
- N2 是**内置的 climbing image 阶段**：阶段 1 收敛后自动启动，最高能像被推上
  鞍点（log 出现 `Climbing replica = k`）；能垒直接读主 log 的 EBF/EBR 列
- **启动方式**：`mpirun -np N*M lmp -partition NxM -in in.neb`
  （N 个副本 × 每副本 M 核；本例 8×8=64 核。像数只由 `-partition` 的 N 决定，
  与 `mpirun -np`、`variable u uloop N` 三处保持一致）

## file-style 路由（按过渡复杂度决策，不要习惯性套 final）

| file-style | 中间像来源 | 适用场景 |
|---|---|---|
| `final <file>` | LAMMPS 内置线性插值（内存中生成，无中间文件） | 小位移单一基元步骤（adatom hop、H 位间转移），直线插值不穿模 |
| `each <file>` | 每个中间像一个坐标文件（配 `variable i equal part`） | 大位移/多原子协同重排：喂 ASE IDPP、上一轮粗 NEB 路径或高温 MD 采样帧 |
| `none` | 不供文件，各像坐标已就位 | restart / 续跑上一条 NEB 路径 |

本例 = 小位移单原子 hop → `final`。

## 像数怎么定（两段法）

1. **先验估计**：移动原子位移 ÷ ~0.8 Å（经典间距惯例），向上取整。
   本例 2.553/0.8 ≈ 3.2 → 4 个中间像（总 6 像）；实际用 8 像——LAMMPS 下
   计算便宜，加密一倍买更平滑的路径。
2. **收敛实验拍板**：用 N−2 / N / N+2 重跑对比 EBF，不随像数漂移即收敛，
   取最稀的一组。**事后体检**：主 log 里 RDT/(N−1) = 平均像间距，
   明显大于 ~1 Å 说明像太少。

## 端点链契约（NEB 的前提）

两端必须**先各自最小化**（`min_initial.in` → `initial_min.data`、
`min_final.in` → `final_min.data`），且约束（本例底两层 `fix setforce 0`）
与 NEB 输入一字不差。`coords.final` 由 `coords_final_from_data.py` 从
`final_min.data` 提取（保留 "ID x y z" 列；注意 write_data 在 minimize 后会
追加 Velocities 段，脚本遇到非数字段头即停）。本例的端点 data 文件由
emcbuild 技能建系产出（Cu(100) 17×17×6 slab + 端点制备脚本），未随样例分发。

## 文件清单

| 文件 | 说明 |
|---|---|
| `in.neb` | NEB 主输入（实测案例配置） |
| `min_initial.in` / `min_final.in` | 端点最小化（登录节点直接跑，各 <1 s） |
| `coords.final` | FS 端坐标清单（1735 原子，运行时由脚本生成后使用） |
| `coords_final_from_data.py` | `final_min.data` → `coords.final` 提取脚本 |

对应模板：`base_templates/lammps_neb.in`（含同样的 file-style 路由与像数决策
注释）。运行时实测证据（log 台阶图解析、mep.dat、能垒对照）归档于工作区
`EMCbuild/cu100-neb-demo/`。
