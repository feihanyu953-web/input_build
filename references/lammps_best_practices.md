# LAMMPS 模拟最佳实践

> AI 生成 LAMMPS 输入文件时参考本指南选择参数和协议。用户也可直接阅读。

## 1. 多级平衡协议

### 为什么需要多级平衡

直接对未平衡体系施加目标温度会导致原子爆炸（尤其是 MLFF、界面、软势）。
标准做法是分阶段逐步引入约束：

```
minimize -> NVT 缓慢升温 -> NVT 平衡 -> NPT(可选) -> NVT/NVE 产跑
```

### 标准协议

```lammps
# Stage 0: 能量最小化（去除坏接触）
min_style       cg
minimize        1.0e-4 1.0e-6 1000 10000

# Stage 1: NVT 缓慢升温（防止原子爆炸）
velocity        all create 100.0 12345 dist gaussian
fix             heat all nvt temp 100.0 300.0 0.05
run             10000               # 5 ps 从 100 K 升到 300 K
unfix           heat

# Stage 2: NVT 平衡（稳定温度）
fix             equil all nvt temp 300.0 300.0 0.05
run             20000               # 10 ps 在目标温度稳定

# Stage 3: NPT 平衡（稳定密度，仅当体积/密度重要时）
unfix           equil
fix             equil all npt temp 300.0 300.0 0.05 iso 0.0 0.0 0.5
run             50000               # 25 ps

# Stage 4: 产跑（切换回 NVT 或 NVE）
unfix           equil
fix             prod all nvt temp 300.0 300.0 0.05
run             200000              # 100 ps
```

### 为什么要缓慢升温

| 做法 | 风险 |
|---|---|
| 直接 `velocity create 300 K` | 未平衡结构在高动能下原子飞出，MLFF 尤其脆弱 |
| 先 `velocity create 100 K` 再 ramp | 低动能起步，系统有时间弛豫，安全 |
| 从 0 K ramp | 最保守，但 0 K 下 velocity create 会报错，用 50-100 K |

### 何时跳过 NPT 阶段

| 场景 | 是否需要 NPT | 原因 |
|---|---|---|
| 固体表面催化（slab 固定） | 否 | slab 体积不应变 |
| 液体密度需匹配实验 | 是 | 密度影响溶剂化结构 |
| 界面水模拟 | 是 | 水层密度需平衡 |
| 纯晶体性质 | 否 | 体积由晶格决定 |
| 电化学固液界面 | 是（仅 xy） | z 方向有真空 |

### Slab 体系的特殊处理

slab 体系不能在 z 方向加 barostat（真空方向）：

```lammps
# slab: 仅 xy 方向 NPT，z 方向固定
fix             equil all npt temp 300.0 300.0 0.05 x 0.0 0.0 0.5 y 0.0 0.0 0.5
# 绝不使用 iso 或 z，否则 barostat 压缩真空层
```

## 2. 恒温器选择

| 恒温器 | LAMMPS 命令 | 适用场景 | 优点 | 缺点 |
|---|---|---|---|---|
| Nose-Hoover | `fix nvt/npt temp` | 产跑（默认） | 正则系综正确、时间可逆 | 小系统可能振荡 |
| Langevin | `fix nve + fix langevin` | 粗粒化、隐式溶剂、快速平衡 | 各态历经好、鲁棒 | 不可逆、阻尼动力学 |
| Berendsen | `fix temp/berendsen` | **仅初始降温** | 快速接近目标温度 | **错误系综，绝不用于产跑** |
| 直接速度缩放 | `fix temp/rescale` | **永不推荐** | 无 | 破坏速度分布 |

### 决策树

```
需要恒温器？
├── 产跑 -> Nose-Hoover (fix nvt/npt)
├── 快速平衡/粗粒化 -> Langevin (fix nve + fix langevin)
├── 从高温降温 -> Berendsen 降温 -> 切换 NVT 产跑
└── 测量输运性质（扩散/粘度）-> NVE（不加恒温器，仅能量守恒）
```

### 阻尼参数选择

| 参数 | metal units | real units | 推荐范围 | 过小 | 过大 |
|---|---|---|---|---|---|
| Tdamp | 0.05-0.5 ps | 50-500 fs | 0.1 ps (100 fs) | < 0.01 ps: 过度约束、振荡 | > 1 ps: 控温失效 |
| Pdamp | 0.5-2.5 ps | 500-2500 fs | 1.0 ps (1000 fs) | < 0.25 ps: 体积振荡 | > 5 ps: 压力控制失效 |

**经验法则**：Tdamp ≈ 100 × timestep，Pdamp ≈ 1000 × timestep。

## 3. 恒压器选择

| 类型 | LAMMPS 关键字 | 适用场景 |
|---|---|---|
| 各向同性 | `iso` | 液体、气体、非晶固体 |
| 各向异性 | `aniso` | 晶体（各晶轴独立） |
| 仅 xy | `x 0 0 0.5 y 0 0 0.5` | slab/界面（z 有真空） |
| 三角 | `tri` | 三斜晶系 |

**禁忌**：对非周期方向（`boundary f` 或 `s`）施加 barostat -> LAMMPS ERROR。

## 4. Timestep 选择

| 条件 | timestep (metal) | timestep (real) | 说明 |
|---|---|---|---|
| 含 H + SHAKE | 0.002 ps (2 fs) | 2 fs | SHAKE 冻结 O-H 键 |
| 含 H 无 SHAKE | 0.0005 ps (0.5 fs) | 0.5 fs | H 原子振动快 |
| 不含 H | 0.001 ps (1 fs) | 1 fs | 重原子体系 |
| MLFF (MACE/DeepMD) | 0.0005-0.001 ps | 0.5-1 fs | 按 H 是否存在 |
| ReaxFF | 0.00025 ps (0.25 fs) | 0.25 fs | 电荷平衡需要小步 |

**验证方法**：NVE 下跑 10000 步，总能漂移应 < 1 meV/atom/ps。

## 5. 收敛判据

平衡阶段必须监控以下指标，**全部满足后才能进入产跑**：

| 指标 | 判据 | 监控方法 |
|---|---|---|
| 温度 | std/mean < 1%（1000 步窗口） | `thermo_style custom step temp` |
| 能量 | 总能漂移 < 0.01 eV/atom/ps | `thermo_style custom step etotal` |
| 体积（NPT） | std/mean < 1% | `thermo_style custom step vol` |
| 压力（NPT） | 平均值接近目标 ± 200 bar | `thermo_style custom step press` |
| 密度（NPT） | 匹配实验值 ± 2% | `thermo_style custom step density` |

**产跑长度 ≥ 10 × 平衡时间**。

## 6. 产跑长度指南

| 目标性质 | 最少步数 (0.5 fs) | 最少时间 | 理由 |
|---|---|---|---|
| 结构（RDF、密度分布） | 20000 | 10 ps | 足够采样构型 |
| 扩散系数 | 200000 | 100 ps | 原子需足够位移 |
| 径向分布函数精细 | 100000 | 50 ps | 统计噪声降低 |
| 粘度 | 1000000 | 500 ps | 长时间关联函数 |
| 界面水取向 | 200000 | 100 ps | 取向弛豫慢 |
| 电极界面电荷 | 500000 | 250 ps | 电荷涨落收敛慢 |

## 7. 常见陷阱

### 7.1 平衡不充分

- **症状**：温度漂移、密度未稳定、RDF 形状随时间变化
- **诊断**：检查 log.lammps 中 temp/vol/etotal 的最后 5000 步标准差
- **修复**：延长平衡至指标满足收敛判据

### 7.2 timestep 过大

- **症状**：NVE 能量漂移 > 1 meV/atom/ps、lost atoms 错误
- **诊断**：NVE 跑 10000 步检查 `etotal` 漂移
- **修复**：减半 timestep 或加 SHAKE

### 7.3 积分器冲突

- **症状**：LAMMPS 报 "One or more atoms are time integrated more than once"
- **诊断**：检查同一 group 是否同时有 `fix nvt` + `fix nve`（或多个积分器）
- **修复**：`unfix` 旧积分器后再 `fix` 新的

### 7.4 Berendsen 用于产跑

- **症状**：物理量统计偏差、结果不可复现
- **诊断**：检查产跑段的 fix 列表中是否有 `temp/berendsen`
- **修复**：切换为 `fix nvt` 或 `fix nve`

### 7.5 slab 加 iso barostat

- **症状**：LAMMPS 报错或真空被压缩
- **诊断**：检查 `boundary` 和 `fix npt` 的压力耦合方向
- **修复**：仅 `x y` 方向 barostat，z 方向 `boundary f`

### 7.6 SHAKE 顺序错误

- **症状**：约束不被满足、能量爆炸
- **诊断**：检查 `fix shake` 是否在所有力 fix 之后定义
- **修复**：`fix shake` 必须是最后一个 fix（在 `fix efield`、`fix wall` 等之后）

## 8. 单位换算速查

| 物理量 | metal | real | SI |
|---|---|---|---|
| 时间 | ps | fs | s |
| 长度 | Å | Å | m |
| 能量 | eV | kcal/mol | J |
| 温度 | K | K | K |
| 压力 | bar | atm | Pa |
| timestep 示例 | 0.001 ps = 1 fs | 1 fs | 1e-15 s |
| Tdamp 示例 | 0.1 ps = 100 fs | 100 fs | 1e-13 s |

## 参考资料

- [LAMMPS 官方手册](https://docs.lammps.org/)
- Frenkel & Smit, "Understanding Molecular Simulation"
- Allen & Tildesley, "Computer Simulation of Liquids"
- Thompson et al. (2022) LAMMPS paper, Comp Phys Comm
