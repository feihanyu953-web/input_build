# LAMMPS Workflow (input-build reference)

> Read this when generating LAMMPS input files. Routing and hard rules live in ../SKILL.md.

## LAMMPS Workflow

### Step 1: Read Structure

Parse `system.data` or equivalent for: elements, atom count, box dimensions, bond topology (if `atom_style full`).

### Step 2: Ask Minimal Questions

```
1. Potential file path(s)? [user provides exact path]
2. Workflow stage? [minimize/equilibrate/production/all]
3. Ensemble? [NVT/NVE/NPT]
4. Target temperature? [K]
5. Dump properties? [positions/forces/velocities/stresses]
6. Run duration? [steps or ps]
```

**Multi-stage equilibration:** `lammps_md.in` ships the full equilibration protocol (minimize -> NVT slow heating -> NVT -> NPT(optional) -> production); for an NPT run, uncomment the Stage 3 block. Consult `references/lammps_best_practices.md` for thermostat/barostat selection, damping parameters, and convergence criteria.

**CRITICAL:** Do NOT suggest, generate, or select potentials. The user must provide exact `pair_style` and `pair_coeff` lines.

### Step 3: Generate Module-Grouped Input

```fortran
# ==============================================================================
# LAMMPS Input Script
# Auto-detected: 5 elements, 137 atoms, slab geometry
# ==============================================================================

# ==============================================================================
# I. INITIALIZATION
# ==============================================================================
units           metal
atom_style      atomic                     # or full if bonds present
boundary        p p p
newton          on

# ==============================================================================
# II. SYSTEM SETUP
# ==============================================================================
read_data       system.data
# replicate     2 2 1                      # Uncomment if supercell needed

# ==============================================================================
# III. FORCE FIELD
# ==============================================================================
# >>> USER: insert pair_style/pair_coeff here <<<
#
# Example formats (replace with your actual potential):
# EAM 文件格式决定 pair_style 与 pair_coeff 参数个数
# （https://docs.lammps.org/pair_eam.html）：
#   funcfl 单元素格式（Cu_u3.eam、Al_u3.eam 等 *.eam）-> pair_style eam
#     pair_coeff 仅 3 参数（* * 文件名），不得带元素符号——pair_eam.cpp
#     硬性 narg==3，多一个参数即 "Incorrect args for pair coefficients" abort
#   setfl 合金格式（Al99.eam.alloy 等 *.eam.alloy）    -> pair_style eam/alloy
#     pair_coeff 必须在文件名后带元素符号
# pair_style      eam
# pair_coeff      * * Cu_u3.eam
#
# pair_style      eam/alloy
# pair_coeff      * * Al99.eam.alloy Al
#
# pair_style      deepmd graph.pb
# pair_coeff      * *
#
# pair_style      mace
# pair_coeff      * * mace.model H O Pt N Na

# ==============================================================================
# IV. ENERGY MINIMIZATION
# ==============================================================================
min_style       cg
minimize        1.0e-4 1.0e-6 1000 10000

# ==============================================================================
# V. TEMPERATURE INITIALIZATION
# ==============================================================================
velocity        all create 300.0 12345 dist gaussian
# velocity      all zero linear            # Uncomment to remove COM drift

# ==============================================================================
# VI. EQUILIBRATION
# ==============================================================================
neighbor        2.0 bin
neigh_modify    every 1 delay 0 check yes
timestep        0.0005                     # 0.5 fs (safe for H-containing)

fix             equil all nvt temp 300.0 300.0 0.05
thermo          100
thermo_style    custom step temp press pe ke etotal vol density
run             20000                      # 10 ps equilibration
unfix           equil

# ==============================================================================
# VII. PRODUCTION
# ==============================================================================
fix             prod all nvt temp 300.0 300.0 0.05
# fix           prod all nve               # Alternative: NVE production

# --- Trajectory output ---
dump            1 all custom 100 traj.lammpstrj id type x y z
dump_modify     1 sort id

# --- Restart files ---
restart         10000 restart1.restart restart2.restart

run             200000                     # 100 ps production

# ==============================================================================
# END OF INPUT
# ==============================================================================
```

## NEB（nudged elastic band）决策树

实测锚点：`examples/L9_lammps_neb`（Cu adatom hop on Cu(100)，2026-10-31
m9 30Mar2026 + REPLICA 包实测：8 像 × 8 核约 1 s，E‡ = 0.5015 eV，
EBF = EBR（对称路径），50 + 57 步收敛）。

### file-style 路由（按过渡复杂度决策，不按习惯）

| file-style | 中间像来源 | 适用 |
|---|---|---|
| `final <file>` | 内置线性插值（内存生成，无中间文件） | 小位移单一基元步骤（adatom hop、H 位间转移），直线插值不穿模 |
| `each <file>` | 每个中间像一个坐标文件（配 `variable i equal part`） | 大位移/多原子协同重排：喂 ASE IDPP、上一轮粗 NEB 路径或高温 MD 采样帧 |
| `none` | 不供文件，各像坐标已就位 | restart / 续跑上一条 NEB 路径 |

事前检查：移动原子直线位移大，或路径可能穿越其他原子（质子跨氢键网络、
构象翻转、扩散绕行）→ 不要用 `final`，改手工供像。

### 像数两段法

1. **先验估计**：移动原子位移 ÷ ~0.8 Å（经典间距惯例）向上取整；
2. **收敛实验拍板**：N−2 / N / N+2 像重跑对比 EBF，不随像数漂移即收敛、
   取最稀一组——LAMMPS/MLIP 下每组秒-分钟级，实验可负担；DFT 里
   dist/0.8 即终点，在这里只是起点。

事后体检：主 log 的 `RDT/(N-1)` = 平均像间距，明显大于 ~1 Å → 像太少。

### 运行契约

- 像数只由 `mpirun -partition NxM` 的 N 决定（neb 命令无像数参数）；
  `mpirun -np`、`#SBATCH -n`、`variable u uloop N`（per-replica dump 计数）
  三处与像数同步
- REPLICA 包必须在构建里（`lmp -h` 的 Installed packages 查；注意部分
  集群二进制名非 `lmp`，如 m9 的 `lmp_intel_cpu_intelmpi`）
- 两端点先各自最小化（`lammps_minimize` 模板），约束组（fix setforce 等）
  与 NEB 输入一字不差；NEB 不算端点弛豫
- coords.final：首行原子数 + 每行 `ID x y z`；从最小化后的 FS data 提取时
  注意 write_data 在 minimize 后追加 Velocities 段（4 列行），提取脚本
  遇非数字段头必须停止（见 `examples/L9_lammps_neb/coords_final_from_data.py`）

### 读 log

- 每 Nevery 步一行、25 列：`RD_i`（各像归一化反应坐标 0→1）与 `PE_i`
  （各像势能）从第 10 列起两列一组交替；`EBF`/`EBR` = forward/backward
  能垒（max PE − 端点 PE），直接读；对称路径 EBF 必须等于 EBR（学生自检点）
- 两个表 = 两阶段：阶段 1（MEP）收敛后出现 `Climbing replica = k` 横幅，
  阶段 2 自动把最高能像推上鞍点；step 在第二表继续累计，同一步数出现
  两次是阶段起点快照、不是重复计算
- 判敛看 MaxReplicaForce（含弹簧力）< ftol；etol 不含弹簧力、可置 0

### 实测坑（2026-10-31 Cu(100) 案例，validator 规则已布防）

1. funcfl 单元素 EAM 的 `pair_coeff` 只有 3 个参数（无元素符号）——
   多写元素符号直接 abort（模板 `lammps_neb.in` 注释有载）
2. data 文件 Atoms 段内出现空行即截断：向外部工具产出的 data 追加原子
   时必须追加到最后一个原子行之后（此类文件常带尾随空行）；违者
   read_data 报 'Did not assign all atoms correctly' →
   validator `LAMMPS_DATA_ATOM_COUNT_MISMATCH`
3. ASE 写出的单元素 data 从 type 0 编号 → 'Invalid atom type' →
   validator `LAMMPS_DATA_ATOM_TYPE_RANGE`（full 等带 molecule-ID 列的
   style 自动豁免，避免把分子编号误读为 type）


## Analysis & Water (Phase 2 snippets)

Snippet 组合系统：以下功能块位于 `../modifiers/lammps/*.snip`，按需粘贴到
production 段（INDEX.json 中已挂载到 md/npt/nve/mlff 等任务）。

### 结构/输运分析（analysis_rdf_msd.snip）

```fortran
compute         rdf1 all rdf 200 1 1 1 2 2 2        # Nbins + 类型对（data 文件 type ID）
fix             frdf all ave/time 100 10 1000 c_rdf1[*] file rdf.dat mode vector
compute         msd1 all msd
fix             fmsd all ave/time 100 10 1000 c_msd1[*] file msd.dat mode vector
```

- `compute coord/atom cutoff <r>`：配位数（界面吸附位点、溶剂化壳）
- `compute orientorder/atom degrees 6`：Q6 键取向有序参数（类冰/类液体水判别）

### 氢键统计（analysis_hbond.snip）

LAMMPS **没有原生 hbond compute**，不要编造命令。标准路线：RDF + 轨迹后处理
（MDAnalysis / OVITO），几何判据常用 O…O < 3.5 Å 且 ∠OOH < 30°（请按水模型/
文献约定调整）。snippet 内给出 O–O / O–H RDF 输出与 MDAnalysis 后处理示例。

### 刚性水与大步长（fix_shake.snip）

```fortran
fix             1 water shake 1.0e-4 20 10 b <O-H键类型> a <H-O-H角类型>
```

- 需 RIGID 包；只支持小分子团簇约束（水 OK，聚合物/框架不行）
- **顺序硬性要求**：fix shake 必须在所有附加力 fix（fix efield、fix wall/...）
  之后定义，否则约束不被满足
- 常见刚性水模型（SPC/E、TIP3P、TIP4P 均为刚性设计）搭配 shake 后，
  timestep 可由 0.5–1 fs 放宽到 **2 fs**（units metal: 0.002 ps）
- validator：units metal 且 timestep > 1 fs 且全文无 shake/rigid → WARN

### 其他

- `ensemble_langevin.snip`：fix nve + fix langevin（damp 典型 100 fs = 0.1 ps
  metal；seed 必填；与 fix nvt 二选一）
- `temp_ramp.snip`：fix nvt temp Tstart Tstop 随 run 线性升降温；速率 =
  (Tstop−Tstart)/(run步数×timestep)，典型 0.1–1 K/ps
- `dump_full.snip`：含速度/力的完整轨迹（MLFF 主动学习用）
- `fix_wall_slab.snip`：fix wall/lj93 软壁限制液体（区别于真空：保持 p p p
  与 kspace；epsilon/sigma 典型 0.1–1.0 eV / 2.5–3.5 Å，请按体系调整）

## Phase A 分层证据报告

生成 LAMMPS 输入后，调用 collector 生成确定性证据报告：

```powershell
python scripts\collect_lammps_evidence.py --spec generation_spec.json --output-dir validation
```

**输出文件**（始终生成，无论成功与否）：

| 文件 | 内容 |
|---|---|
| `generation_manifest.json` | spec/input/data/potential artifacts 的 SHA256 + 工具哈希 |
| `static_validation.json` | 现有 validator 的 tiers 和 findings，或 L0 不通过时的 BLOCKED 状态 |
| `validation_report.json` | L0-L5 完整证据报告（canonical JSON） |
| `validation_report.md` | 人类可读的层级表格摘要 |

**退出码**：`0` = L0+L1 均 PASS；`1` = 未达到 L1_STATIC_PASS；`2` = 参数错误。

**声明**：

- L0 PASS 表示声明的生成上下文和文件哈希完整；
- L1 PASS 表示未修改的静态 validator 未发现 ERROR；
- L1 WARNING 保持可见但不改变 PASS；
- L2-L5 保持 `NOT_EVALUATED`，Phase A 不评估；
- 此命令从不运行 LAMMPS、提交作业、更改输入、修复文件或证明势函数/模型的物理适用性。

## 官方示例索引（Phase B）

```powershell
python scripts\build_lammps_examples_index.py build --source-root <checkout>\examples --repository https://github.com/lammps/lammps --commit <SHA> --output references\lammps_examples_index.json
python scripts\build_lammps_examples_index.py check --index references\lammps_examples_index.json
```

**声明：**

- 索引只接受 `https://github.com/lammps/lammps` 作为来源仓库；
- `--commit` 与 `--release` 互斥且必填其一，不抓取 `latest`；
- `check` 不联网、不读 source checkout；
- 索引是 provenance 数据，不替代 validator、不运行 LAMMPS、不选择势函数、不提升 L0-L5 任何证据等级；
- `local_example` 是信息性关联，不表示官方示例证明了本地示例的物理适用性。

## Phase C 命令模型与多行 Parser

LAMMPS 输入的结构化解析由 `scripts/parse_lammps.py`（多行 parser）与
`scripts/lammps_command.py`（不可变命令模型）承担，纯 stdlib、无运行时语义。

### 输入与输出

```python
# 入口：解析单个根文件（可含 include 递归）
result = parse_lammps_file(path, *, allowed_root=None, max_depth=8)  # -> ParseResult
```

`ParseResult` 字段：

| 字段 | 含义 |
|---|---|
| `commands` | 按文件顺序的 `Command` 元组（`name` 小写、`args` 元组、`span` 源行范围、`raw_text` 逻辑行原文） |
| `raw_text` | 仅根文件的完整内容，不含被 include 文件内容（保证旧的 user-placeholder 扫描行为不变） |
| `issues` | `ParseIssue` 元组（severity/code/message/span） |
| `completeness` | `COMPLETE` 或 `INCOMPLETE` |
| `lifecycle` | 按创建顺序的 `LifecycleRecord` 元组（fix/compute/dump 的 ID/group/style/created_at/destroyed_at） |
| `includes` | 已成功展开的 include 归一化路径元组（按遇到顺序） |

### `Completeness.INCOMPLETE` 触发条件

当且仅当 parser 遇到以下情形之一：

- 动态控制流命令（`if`/`jump`/`label`/`loop`/`next`）——发出 `LAMMPS_DYNAMIC_CONTROL_FLOW` WARNING，命令保留在 `commands` 中，parser 不展开分支；
- include 展开失败（`LAMMPS_INCLUDE_ESCAPE` / `LAMMPS_INCLUDE_CYCLE` / `LAMMPS_INCLUDE_DEPTH` / `LAMMPS_INCLUDE_MISSING`，均为 ERROR）；
- 分词错误（`LAMMPS_UNCLOSED_QUOTE`，ERROR，跳过该逻辑行继续解析）。

### include 的 allowed root 与 fail-closed 行为

- `<path>` 相对于包含该 `include` 命令的文件所在目录解析；
- 解析后的归一化路径必须位于 `allowed_root`（默认根文件所在目录）子树内，否则 `LAMMPS_INCLUDE_ESCAPE` 且跳过；
- 循环（`LAMMPS_INCLUDE_CYCLE`）、深度超限（`max_depth` 默认 8，`LAMMPS_INCLUDE_DEPTH`）、文件缺失（`LAMMPS_INCLUDE_MISSING`）均 fail-closed；
- 成功展开时被包含命令追加到结果序列，其 `span.source` 设为被包含文件路径；`include` 命令本身不出现在 `commands` 中；
- `jump SELF <file>` 不视为 include，始终按动态控制流处理。

### 生命周期跟踪

- `fix/compute/dump <id> <group> <style> ...` 创建 `LifecycleRecord`；`unfix/uncompute/undump <id>` 设置 `destroyed_at`；
- 未知 ID 的销毁命令发出 `LAMMPS_{UNFIX|UNCOMPUTE|UNDUMP}_UNKNOWN` WARNING；未销毁时重复创建发出 `LAMMPS_DUPLICATE_LIFECYCLE_ID` WARNING；
- `active_lifecycle(result)` 返回文件结束时仍活跃的记录，供 renderer（Phase D）分配唯一 ID。

### 兼容适配器返回形状保证

`validate_input.parse_lammps(path)` 是懒加载委托适配器，返回 `(commands, raw_text)`：
`commands` 为 `to_legacy_commands(result)` 投影（`[(cmd, [args])]`，`cmd` 小写、`args` 列表、顺序一致），
`raw_text` 为根文件内容。简单输入（无 `&` 续行、无引号、无 include）的投影与旧 parser
逐元素相等，validator 的 finding 契约不变。

### 声明

parser 不执行 LAMMPS、不调用二进制、不提交作业、不访问网络；输出是静态结构描述，
无法将证据提升到 L1 以上。`completeness=INCOMPLETE` 是解析层面的状态，不直接映射
Phase A 的证据等级；后续阶段的 L1 评估器可读取 `completeness` 与 `issues` 决定是否
将 L1 标记为 `INCOMPLETE`。

## Phase D 确定性渲染器

### 职责

渲染器 `scripts/render_lammps.py` 接收 Phase A 的类型化 `GenerationSpec` 加显式选择的
base template / modifiers / profiles（`RenderRequest`），输出字节稳定的 `in.lammps` 与
`render_trace.json`（`RenderResult`）。渲染器只组装和排序已有的科学内容，不做势函数选择、
ensemble 自动调参或物理阈值推断，绝不选择或发明 potential/model 行。

### 输出文件

- `in.lammps`：LF 换行、末尾换行、固定命令格式（命令与参数单空格、对齐空格归一化、
  行内注释 ` #` 分隔、section 分隔注释按固定宽度生成）。相同 `RenderRequest` 产生
  字节完全相同的 `input_text` 与 `output_sha256`（`sha256:<hex>`）。
- `render_trace.json`：UTF-8、LF、结尾换行、两空格缩进、`ensure_ascii=False`、
  `sort_keys=True`；含 schema_version、base_template/modifiers/profiles、
  anchors（1-indexed 行区间）、commands（command/id/namespace/anchor/output_span/
  source/official_examples/ordering_edges/anchor_inferred/conflict_refs）、
  id_allocations、conflicts、unresolved、validator_findings、validator_tiers。

### ID 分配策略

`fix` / `compute` / `dump` 是三个独立命名空间：同命名空间内 ID 唯一；跨命名空间重用
合法且可追踪。分配按 `(anchor_ordinal, source_declaration_order)` 排序：保留扫描 →
碰撞检测（同命名空间两个活跃命令声明相同 ID 且无 `unfix`/`uncompute`/`undump` 释放，
确定性重编号为下一个可用整数）→ 确定性分配。

### Anchor 词表与排序图

12 个闭合 anchor：`initialization system force_field minimization velocity_init
external_force_fixes constraints integration analysis output run cleanup`。排序图 DAG
强制：初始化 → system → force_field → minimization/velocity_init →
external_force_fixes → constraints → integration → analysis → output → run → cleanup。
未知/缺失/重复 anchor 与未知/未覆盖模板 fail closed（`AnchorError`，不产生 `in.lammps`）。

### 冲突分类

- **机械修复（REPAIRED）**：`DUPLICATE_ID`（重编号）、`DUPLICATE_OUTPUT`（跳过第二个 dump）。
- **科学阻断（BLOCKED）**：`MULTIPLE_INTEGRATORS`（同 group 同 stage 两个及以上积分器）、
  `INCOMPATIBLE_ENSEMBLE`（npt/nph 作用于非周期维度）、`LIFECYCLE_VIOLATION`、
  `PROFILE_COLLISION`、`MODIFIER_REPLACES_INTEGRATOR`（未确认的替换）。
- **未决（UNRESOLVED）**：modifier 活跃行中 `>>>` 引导的用户占位标记，或占位 group 名
  （`water`/`electrolyte`）未被 spec 声明。

渲染器不得通过调参、更换 ensemble 或选择势函数来绕过科学冲突。

### 初始覆盖

- 覆盖：`generic_md`（`lammps_md.in`）与 `mlff/mace`（`lammps_mlff.in`）两个 profile。
- 不覆盖：`lammps_conp.in`、`lammps_plumed.in`、`lammps_neb.in`、
  `lammps_nve.in`、`lammps_minimize.in` 在 Phase D 中 fail closed，不静默降级。

### 渲染器不做的事

不选势函数、不调 ensemble、不设物理阈值、不执行 LAMMPS 二进制、不提交作业、
不访问网络。渲染后 `in.lammps` 必须通过现有 `validate_lammps_one()` 且零 ERROR
（`validator_tiers` 的 `overall` 不为 `FAIL`，`physics` 恒为 `NOT_EVALUATED`）。



## Phase G 科学 profiles

科学 profile 为复杂 LAMMPS 任务提供 L4 验收契约。每个 profile 是 `profiles/lammps/` 下的独立目录，包含 `profile.json`（封闭契约）和 `rules.py`（静态规则与 L4 验收函数）。

### 可用 profile

| profile | 触发条件 | L4 必需证据 |
|---|---|---|
| `mlff/mace` | 用户显式选择；MACE 模型路径与 sha256 来自用户 | 独立 DFT 验证集 energy/force 误差、NVE 能量漂移、结构覆盖 |
| `constant_potential` | 用户显式选择；电极 group、电位约定、边界模式来自用户 | 0 V 平衡电荷稳定、目标电位电荷稳定 |
| `interface_water` | 用户显式选择；H/O type mapping、水模型、柔性来自用户 | 密度分布对照计划、RDF 对照计划、水完整性证据 |

### 显式激活

profile 不从元素、文件名或 pair_style 推断。用户必须在 `generation_spec.json` 的 `profiles` 列表中显式声明，并在 `profile_context.json` sidecar 中提供 profile 专属事实。

### 组合与冲突

- `mlff/mace` + `interface_water`：兼容（MLFF 驱动界面水 MD）；
- `interface_water` + `constant_potential`：兼容（水电解质加电极）；
- `mlff/mace` + `constant_potential`：冲突（MLFF 无 per-atom 电荷），registry 拒绝。

### L4 fail-closed

缺少必需证据时 L4 状态为 `INCOMPLETE`，绝不降格为 `PASS`。L3 smoke 未通过时 L4 状态为 `BLOCKED`。

### 声明与不声明

- profile 声明：必需 spec 字段、渲染器扩展、静态规则、能力要求、smoke 协议、L4 验收指标、未决行为、官方来源和后处理交接。
- profile 不声明（也不选择）：potential、model、charge、电极定义、水刚性、阈值、科学目标。这些由用户提供，缺失时标记为 `unresolved` 或 `INCOMPLETE`。

## Phase I 输入解释报告

生成并验证 LAMMPS 输入后，调用 `scripts/explain_lammps.py` 生成只读的解释报告：

```powershell
python scripts\explain_lammps.py --spec generation_spec.json --input in.lammps --render-trace render_trace.json --examples-index references\lammps_examples_index.json --validation-report validation\validation_report.json --static-validation validation\static_validation.json --output-dir explain
```

### 输出文件

- `explain/explain_report.json`：确定性 JSON（UTF-8、LF、结尾换行、两空格缩进、`ensure_ascii=False`、`sort_keys=True`）。含 `status`、`exit_code`、`inputs`、`missing_inputs`、`commands`、`id_allocations`、`findings`、`unexplained_findings`、`evidence`、`unresolved`。
- `explain/explain_report.md`：人类可读的 Markdown 报告，固定章节顺序。

### 退出码

- `0`：完整解释。所有必需和可选输入均存在，所有 validator finding 均在规则注册表（`references/lammps_validation_rules.json`）中找到对应规则。
- `1`：部分解释。缺少可选输入，或存在未知 finding code，或缺失 provenance。
- `2`：`argparse` 用法错误（缺少必需参数或参数格式错误）。

### 输入文件语义

| 参数 | 文件 | 必填 |
|---|---|---|
| `--spec` | `generation_spec.json` | 是 |
| `--input` | `in.lammps`（渲染产物） | 是 |
| `--render-trace` | `render_trace.json`（Phase D） | 可选 |
| `--examples-index` | `lammps_examples_index.json`（Phase B） | 可选 |
| `--validation-report` | `validation_report.json`（Phase A） | 可选 |
| `--static-validation` | `static_validation.json`（Phase A） | 可选 |
| `--output-dir` | 输出目录 | 是 |

### 声明与不声明

- explain mode 只读，不修改任何输入文件；只写入 `explain_report.json` 和 `explain_report.md` 两个文件。
- 完整解释需要全部六个输入存在且所有 finding code 在规则注册表中找到对应规则。
- 缺少可选输入或存在未知 finding code 时报告为 `PARTIAL`，退出码 `1`。
- 证据等级从 `validation_report.json` 原样复制，explain mode 绝不重新计算或提升等级。
- 未知 finding code 保持可见并标记为未解释，explain mode 绝不编造理由。
- 此命令从不运行 LAMMPS、提交作业、更改输入、修复文件或证明势函数/模型的物理适用性。
