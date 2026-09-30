# input_build Examples Index

每个目录是一个自包含示例（结构 + 输入 + README 说明）。
**golden test**：`tests/test_validate_input.py` 会对本目录所有含 INCAR 的示例
跑 validator，任何 ERROR 级违规都会导致测试失败。

## Runner 输出语义（STATIC_PASS / INCOMPLETE / ERROR）

`scripts/validate_input.py --examples-dir` 对每份输入报告下列状态；这些状态只描述
**validator 检查层面**的结果：

| 状态 | 含义 | 处置 |
|---|---|---|
| STATIC_PASS | 0 条 ERROR，且 validator 所需上下文齐全。它只表示静态输入审查完成，不能缩写或转述为“计算 PASS” | 可交付输入；WARNING 必须连同上下文一并报告给用户 |
| INCOMPLETE | 缺少 VASP POSCAR，或 CP2K coordinate / LAMMPS `read_data` 等上下文缺失、格式不受静态解析器支持，相应结构/data-aware 检查被跳过（已提供但语法损坏的 POSCAR/XYZ/PDB 则为 FAIL） | **不是完整通过**；补齐上下文后必须复检，不得当作 STATIC_PASS 引用 |
| ERROR | 存在 ≥1 条 ERROR 级 finding（行首显示 FAIL，进程退出码 1） | 修复前禁止交付或提交作业 |

每条结果同时给出三个机器可读/文本可见层级：

| 层级 | 可能值 | 含义 |
|---|---|---|
| `syntax` | `PASS` / `FAIL` / `NOT_EVALUATED` | validator 支持的输入语法是否成功解析 |
| `combination` | `PASS` / `PASS_WITH_WARNINGS` / `INCOMPLETE` / `FAIL` / `BLOCKED` | 跨参数组合与上下文规则是否通过 |
| `physics` | `NOT_EVALUATED` | 静态 validator 不读取真实程序输出，不声明任务完成或物理收敛 |

因此，即使使用 `--verified KEY=VALUE` 将匹配的经验性 WARNING 降为 INFO，
`physics` 仍是 `NOT_EVALUATED`。真实运行与物理断言由 `scripts/smoke/`
或用户提供的 VASP/CP2K/LAMMPS 输出另行验证。

JSON 输出额外提供 `coverage.complete` / `coverage.reason`（单文件）或
`incomplete_reasons`（examples runner）。runner 会解析 CP2K
`COORD_FILE_NAME`/`COORD_FILE_FORMAT`（XYZ、PDB）和 LAMMPS `read_data` 的
相对路径；文件不存在、LAMMPS data 无法解析、CP2K 格式不支持或 inline
`&COORD` 依赖未展开的 `@INCLUDE` 时必须标为 INCOMPLETE。普通 inline
`&COORD`（包括坐标值使用 `${VAR}`）不需要外部文件，元素标签仍会参与
`&KIND` 覆盖检查。PDB 默认按 atom name 匹配 KIND；只有
`USE_ELEMENT_AS_KIND TRUE` 时才按 element column，若该开关是未展开的
预处理变量则保持 INCOMPLETE。

## 编号体系

| 前缀 | 内容 | 范围 |
|---|---|---|
| 数字 01–21 | VASP 示例 | relax / scf / md / aimd / band / freq / phonon(phonopy) / neb / bader / hse / dftu / workfunction / elf / optics / dielectric / slowgrowth |
| C1–C15 | CP2K 示例 | scf / geo_opt / md / band / cell_opt / neb / dos / phonon / workfunction / dftu / optics / elf / hirshfeld / sccs / metadyn |
| L1–L9 | LAMMPS 示例 | md / minimize / npt / nve / efield / conp / mlff / plumed / neb |
| K5–K8 | `kpoints_helper.py` 工具测试 | band path / 显式 MP / 显式 Gamma / 依赖自动安装 |

> 编号说明：K1–K4 为早期手算 KPOINTS 测试，已被 seekpath 方案淘汰，故缺号。
> K5 自 2026-07-19 外部审计起改为**容差回归测试案例**：该 MoS₂ 结构在
> SeeK-path 默认 symprec=1e-5 下被识别为 monoclinic（C2/m, No. 12, mC）而非
> hexagonal，用于回归测试 `kpoints_helper.py` 的 `--symprec` /
> `--angle-tolerance` 容差门控与 fail-closed 行为，不再作为 golden PASS 示例。

## VASP 示例（01–21）

| 目录 | 内容 | 演示要点 |
|---|---|---|
| 01_Al_FCC_bulk | Al FCC 体相静态 SCF | 基础流程；fcc → Gamma 网格（spglib 居中判定） |
| 02_MoS2_monolayer | MoS2 单层 relax | 真空层检测；IVDW=11（D3 zero-damping） |
| 03_Pt100_surface | Pt(100)+H₂O+NH₃+Na 界面 relax | 含 H 吸附体系 POTIM≤0.3；dipole 修正 |
| 04_Al_FCC_band | Al conventional 胞能带 | **seekpath 原胞坐标系**（修复后范例） |
| 06_Pt100_aimd | Pt(100) AIMD NVT | Langevin 恒温器；MD 关 WAVECAR/CHGCAR 输出 |
| 07_Fe3O4_magnetic | Fe₃O₄ 磁性 SCF | ISPIN=2 + DFT+U；静态 ISMEAR=-5（task-aware 规则允许） |
| 08_TiO2_semiconductor | TiO₂ 静态 SCF | 半导体 ISMEAR=-5 + 稠密网格 |
| 09_Al_HSE06 | Al HSE06 杂化 | PRECFOCK/NKRED 收敛性提醒 |
| 10_Al_NEB | Al CI-NEB | IMAGES/SPRING=-5/LCLIMB |
| 11_Al_bader | Al Bader 电荷 | LAECHG + FFT 网格加倍 |
| 12_Pt100_freq | Pt(100) 频率 | IBRION=5/NFREE=2/POTIM=0.015 |
| 13_Si_optics | Si 光学性质 | LOPTICS + NBANDS 提升 |
| 14_CeO2_100_surface_N2_COOH | CeO₂(100)+N₂+COOH | 全要素检查单（DFT+U/LMAXMIX=6/IVDW=12/POTIM=0.2） |
| 15_CeO2_workfunction | CeO₂(111) 功函数 | LVHAR + dipole + DFT+U |
| 16_CeO2_elf | CeO₂ ELF | LELF 强制 NPAR=1 |
| 17_TiO2_optics | TiO₂ 光学性质 | LOPTICS + CSHIFT |
| 18_TiO2_dielectric | TiO₂ 静态介电张量 | LEPSILON；可选 IBRION=8/LPEAD 离子贡献 |
| 19_CeO2_dftu | CeO₂ 体相 DFT+U | f 电子 LMAXMIX=6 强制示例 |
| 20_Si_phonopy | Si 声子（phonopy 流程） | 单点 IBRION=-1/NSW=0/EDIFF=1E-8；与 freq 定位区分 |
| 21_Pt100_NH3OH_slowgrowth | Pt(100)+NH₃+OH 慢增长质子转移 SG-AIMD | 两阶段 SG-AIMD + ICONST；S 差分坐标单一受控参数（INCREM 唯一） |

## CP2K 示例（C1–C15）

| 目录 | 内容 | 目录 | 内容 |
|---|---|---|---|
| C1_CP2K_Al_SCF | Al SCF | C8_CP2K_phonon | Si 声子（Phonopy 流程） |
| C2_CP2K_H2O_opt | H₂O 几何优化 | C9_CP2K_workfunction | Au(111) 功函数 |
| C3_CP2K_H2O_Pt_MD | H₂O/Pt 界面 MD | C10_CP2K_FeO_dftu | FeO DFT+U |
| C4_CP2K_Si_band | Si 能带 | C11_CP2K_Si_optics | Si 静态极化率 |
| C5_CP2K_Al_cell_opt | Al 晶胞优化 | C12_CP2K_Si_elf | Si ELF |
| C6_CP2K_Al_NEB | Al NEB | C13_CP2K_H2O_hirshfeld | H₂O Hirshfeld 电荷 |
| C7_CP2K_dos | TiO₂ DOS/PDOS | C14_CP2K_H2O_sccs | H₂O SCCS 隐式溶剂 |
| — | — | C15_cp2k_metadyn | 水二聚体 metadyn（WTMetaD + COLVAR） |

## LAMMPS 示例（L1–L9）

| 目录 | 内容 | 演示要点 |
|---|---|---|
| L1_Al_EAM_MD | Al EAM MD | 基础 MD 流程 |
| L2_H2O_Pt_MLFF_min | H₂O/Pt MACE 最小化 | MLFF pair_style；多阶段 minimize |
| L3_Al_EAM_NPT | Al EAM NPT | 压强调控 |
| L4_H2O_MLFF_NVE | H₂O MACE NVE | 能量守恒验证 |
| L5_electrolyte_efield | 电解液外加电场 | fix efield + 电位 ramp（snippet 演示） |
| L6_CONP_electrode | 恒电位电极 MD | fix electrode/conp + pppm/electrode + ffield |
| L7_H2O_Pt_MLFF_md | H₂O/Pt MACE NVT 生产 | lammps_mlff 模板落地；元素顺序警示 |
| L8_lammps_plumed | PLUMED 增强采样接口 | fix plumed + plumed.dat；单 fix、group-ID 忽略 |
| L9_lammps_neb | LAMMPS NEB | fix neb + neb 命令；-partition NxM 副本运行；coords.final 格式 |

## 工具测试（K5–K8）

| 目录 | 验证目标 |
|---|---|
| K5_hex_band | 六方体系 seekpath 能带路径（**容差回归测试案例**，见编号说明） |
| K6_explicit_MP | 显式 Monkhorst-Pack 网格 |
| K7_explicit_Gamma | 显式 Gamma 网格 |
| K8_auto_install | 干净环境下依赖自动安装（venv 在 temp 目录，用完即删） |

## 已知版本门控

以下示例/模板含版本或构建相关语法，使用前对照 `SKILL.md` 的
"Version & Capability Gating" 小节（基线：VASP ≥ 6.3 / CP2K ≥ 2024.3 / LAMMPS ≥ 22Jul2025）：

| 位置 | 门控内容 |
|---|---|
| 10_Al_NEB（及 `vasp_neb` 模板） | `LCLIMB` 属 VTST 扩展；stock VASP 必须删除该 tag 并按普通 NEB 运行 |
| C5_CP2K_Al_cell_opt（及 `cp2k_cell_opt` 模板） | `&CELL_OPT/TYPE` 在 CP2K ≤ 2026.1 有效，2026.2 已删除（DIRECT_CELL_OPT 为默认值，2026.2+ 省略该 keyword） |
| C10_CP2K_FeO_dftu（及 `cp2k_dftu` 模板） | < 2026.2 必须完全省略 `&KPOINTS`（含 `SCHEME GAMMA` 的任何 `&KPOINTS` 都会 abort "Method not implemented for k-points"，省略即 Γ 点）；CP2K 2026.2 起 Mulliken DFT+U 支持 k-points |
| 06_Pt100_aimd（及 `vasp_md` 模板） | `RANDOM_SEED` 取三个整数（当前官方语法） |
| L 系 LAMMPS 示例（及 `lammps_*` 模板） | `pair_style reax/c` 已由 `reaxff` 取代（22Jul2025 起）；ELECTRODE / RIGID / PLUMED 等功能依赖编译包 |

## 任务覆盖矩阵

| 任务 | VASP | CP2K | LAMMPS |
|---|---|---|---|
| relax / geo_opt | 01 02 03 19 | C2 C5 | L2 |
| scf / static | 07 08 | C1 | — |
| md / aimd | 06 | C3 | L1 L3 L4 |
| slowgrowth (SG-AIMD) | 21 | — | — |
| band | 04 | C4 | — |
| dos | — | C7 | — |
| freq / phonon | 12 20 | C8 | — |
| neb | 10 | C6 | L9 |
| bader / hirshfeld | 11 | C13 | — |
| hse | 09 | — | — |
| dftu | 07 14 19 | C10 | — |
| workfunction | 15 | C9 | — |
| elf | 16 | C12 | — |
| optics | 13 17 | C11 | — |
| dielectric | 18 | — | — |
| metadyn / 增强采样 | — | C15 | L8 |
| solvation (VASPsol / SCCS) | solvation.patch | C14 | — |
| efield / 外加电场 | efield.patch | — | L5 |
| conp / 恒电位电极 | — | — | L6 |
| mlff | — | — | L2 L4 L7 |

## Snippet 组合（LAMMPS）

`modifiers/lammps/*.snip` 是可粘贴功能块（Phase 2 新增 7 个，挂载见 INDEX.json）：

| snippet | 用途 |
|---|---|
| fix_efield.snip | 匀强外加电场（带电体系） |
| fix_shake.snip | 刚性水约束；须在 fix efield 等附加力 fix 之后定义；timestep 可放宽到 2 fs |
| analysis_rdf_msd.snip | RDF / MSD（compute + fix ave/time）；coord/atom、orientorder/atom（Q6）可用 |
| analysis_hbond.snip | 氢键统计无原生命令 → RDF + MDAnalysis/OVITO 后处理路线 |
| ensemble_langevin.snip | fix nve + fix langevin（与 fix nvt 二选一；seed 必填） |
| temp_ramp.snip | fix nvt 线性升降温（典型 0.1–1 K/ps） |
| dump_full.snip | 含速度/力的完整轨迹（MLFF 主动学习） |
| fix_wall_slab.snip | fix wall/lj93 软壁限域液体（区别于真空方案） |

## 结构测试素材

`tests/fixtures/`（原 `examples/_test_structures/`）：POSCAR/xyz/LAMMPS data
小结构（Al、Si、TiO₂、CeO₂、Fe₃O₄、H₂O、H₂O/Pt、NEB 端点），供 parser
回归测试复用。
