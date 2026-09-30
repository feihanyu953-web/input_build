# input_build smoke 框架

把"这个技能生成的输入文件真的能在真实代码里跑出物理正确的结果"固化成可重复执行的
最小算例集。当前固化 18 个用例（第一波 9 个 + 第二波 9 个）。历史运行结果不等于
当前环境可复现：`wsl-local` 尚缺 `vasp_ncl`、`lammps_full`、`mace_model_path`，
VASPsol 历史输出的 `Ediel_sol` 恒为 0，因而不能记为功能 PASS。

| 用例 | 代码 | 物理断言 | 蓝本 |
|---|---|---|---|
| `si_relax` | VASP | 弛豫收敛；PE = **-5.34 ± 0.1 eV/atom** | `base_templates/vasp_relax.incar` |
| `h2_freq` | VASP | H2 伸缩频率 **4200–4450 cm⁻¹** | `base_templates/vasp_freq.incar` |
| `vaspsol_h2` | VASP | 最后一个 `Ediel_sol` 绝对值 > 1e-8；`vasprun.xml` 含 `LSOL` 与 `EB_K`（build smoke，不是普适的 H2 溶剂化物理阈值） | `vasp_relax` + `modifiers/solvation.patch` |
| `h2o_geo_opt` | CP2K | 优化收敛；H-O-H 键角 **104 ± 2°** | `examples/C2_CP2K_H2O_opt` |
| `h2o_hirshfeld` | CP2K | Hirshfeld O 净电荷 **-0.30 ± 0.05 e** | `examples/C13_CP2K_H2O_hirshfeld` |
| `metadyn_dimer` | CP2K | `*-COLVAR.metadynLog` / `*-HILLS.metadynLog` 非空 | `examples/C15_cp2k_metadyn` |
| `feo_dftu_scf_start` | CP2K | 输出含 `SCF WAVEFUNCTION OPTIMIZATION`（进入 SCF） | `examples/C10_CP2K_FeO_dftu` |
| `al_eam_nvt` | LAMMPS | 无 ERROR；PE = **-3.36 ± 0.05 eV/atom** | `examples/L1_Al_EAM_MD` |
| `al_eam_minimize` | LAMMPS | 无 ERROR；PE = **-3.36 ± 0.05 eV/atom** | `base_templates/lammps_minimize.in` + L1 |
| `vasp_dftu_feo` | VASP | OUTCAR 含 `LDA+U is selected`；exit 0 | `base_templates/vasp_dftu.incar` |
| `vasp_soc_pt` | VASP | OUTCAR 含 `LNONCOLLINEAR`；exit 0 | `vasp_relax` + `modifiers/soc.patch` |
| `vasp_metagga_si` | VASP | OUTCAR 含 `R2SCAN`；exit 0 | `vasp_relax` + `modifiers/metagga.patch` |
| `vasp_efield_h2o` | VASP | VASPsol 非零能量+xml 参数块；OUTCAR 含 `EFIELD`；exit 0 | `vasp_relax` + `solvation`/`dipole`/`efield` patch |
| `lammps_nve_al` | LAMMPS | 无 ERROR；NVE Etot 漂移 **< 0.01 eV/atom**（500 步） | `base_templates/lammps_nve.in` + L1 |
| `lammps_npt_al` | LAMMPS | 无 ERROR；末段平均压力趋向 0（**\|P\| < 3000 bar**） | `base_templates/lammps_md.in`（NPT stage）+ L3 |
| `lammps_shake_spc` | LAMMPS | 无 ERROR；SHAKE stats 键 ave = **1.0 ± 0.001 Å** | `modifiers/lammps/fix_shake.snip` |
| `lammps_plumed_ar` | LAMMPS | 无 ERROR；`COLVAR` 非空且数据行 **> 40** | `base_templates/lammps_plumed.in` + L8 |
| `lammps_mace_3bpa` | LAMMPS | 无 ERROR；PE 有限值（**≈ -17660 eV / 27 原子**） | `base_templates/lammps_mlff.in` |

除上述 VASPsol 失效判据外，数值区间来自 wsl-local 历史实测（第一波 2026-06，
第二波 2026-07），仍需在当前二进制/模型环境中重新执行后才能更新为当前 PASS。

第二波用例依赖 `smoke_env.yaml` 增补键（cases.yaml 文件头有同样说明）：

- `codes.vasp_ncl` —— vasp_ncl 二进制（SOC 非共线）
- `codes.lammps_full` —— 全功能 lmp（10 Sep 2025，含 PLUMED + ML-MACE + KOKKOS）
- `data.mace_model_path` —— MACE 模型文件（`*.model-lammps.pt`）

## 文件

- `smoke_env.yaml` —— 平台环境（二进制路径、数据目录、launcher、OMP 线程、timeout）
- `cases.yaml` —— 平台无关用例（内联输入文件、截断记录、运行命令模板、物理断言）
- `run_smoke.py` —— 执行器（纯 stdlib；见下文"依赖"）
- `runs/` —— 运行产物（每次运行重建，不入库）

## 用法

```bash
cd .claude/skills/input_build/scripts/smoke

python run_smoke.py --list                  # schema + 所选 env 占位符闭包校验（不自启算）
python run_smoke.py                         # 默认环境跑全部
python run_smoke.py --only si_relax,h2_freq # 只跑指定用例
python run_smoke.py --env wsl-local --report runs/my_report.md
```

退出码：全部 PASS → 0；任一 FAIL/TIMEOUT/ERROR → 1；用法/配置错误 → 2。
报告同时打印到 stdout 并写入 `runs/smoke_report.md`（可用 `--report` 改路径）。

## 设计要点

- **绝不只看退出码。** LAMMPS 报 `ERROR` 时退出码也是 0（VASP 部分错误亦然），
  所以每个用例必须带物理断言；LAMMPS 用例必须带 `not_grep ERROR`。
- **强 timeout。** 每个用例有 `timeout`（秒），超时杀进程树（Windows 用
  `taskkill /T /F`，POSIX 用进程组 SIGKILL）并判 TIMEOUT。发现算例卡死不要等。
- **算力纪律。** OMP 线程数由 env 的 `omp_num_threads` 控制（VASP=2，
  CP2K/LAMMPS=1），runner 自动 `export OMP_NUM_THREADS=...`。
- **截断透明。** 相对蓝本放松的性能参数（NSW、STEPS、MAX_SCF、k-mesh…）全部记录
  在用例的 `truncations` 字段里，smoke 通过 ≠ 生产参数收敛。
- **显式路径。** POTCAR / CP2K data / LAMMPS potentials 一律走 env `data` 的显式
  路径；`VASP_PP_PATH` 环境变量不可靠，不要依赖。
- **环境闭包 fail closed。** `--list` 同时解析所选 env；任何 `{{var}}` 缺失都会
  返回非零并列出变量名；`potcar:` 的隐式 `data.vasp_potcars` 依赖也会检查，
  不把无法启动的用例算作 schema PASS。

## 新增用例

1. 在 `cases.yaml` 追加一个列表项，必填 `name` / `code` / `run` 和至少一个
   `asserts`；输入文件用 `files:` 字面块内联（`{{var}}` 引用 env 的 codes/data，
   如 `{{vasp_std}}`、`{{cp2k_data}}`、`{{al_eam_path}}`）。
2. 物理断言先在该环境实测一遍再定区间；区间宽度要容忍合理的版本/编译差异，
   但不能宽到失去判别力。
3. `python run_smoke.py --list` 做 schema 校验，然后 `--only <name>` 实跑验证。
4. 在用例里记录 `blueprint`（技能内出处）与 `truncations`。

### 断言类型

| type | 参数 | 语义 |
|---|---|---|
| `file_exists` | `path`（支持 glob）、`min_size`（默认 0） | 文件存在且不小于 min_size 字节 |
| `grep` | `path`、`pattern`（正则） | 文件内容匹配 |
| `not_grep` | `path`、`pattern` | 文件内容**不**匹配（LAMMPS ERROR 必备） |
| `regex_number` | `path`、`pattern`（至少 1 个捕获组）、`occurrence`（first/last，默认 last）、`divide_by`、`min`、`max`、`abs_min` | 提取有限数值并做区间/绝对值下限断言；捕获到 NaN/Inf 必须失败（如 TOTEN、非零 `Ediel_sol`） |
| `xyz_angle` | `path`（glob）、`atoms: [i,j,k]`（1 基，j 为顶点）、`min`、`max`（度） | XYZ 轨迹**最后一帧**的键角 |

## 新增平台（第二份 env）

在 `smoke_env.yaml` 的 `environments:` 下复制一个现有 environment 块改造
（模板见 `smoke_env.example.yaml`）。关键字段：

- `shell_prefix`：本机 WSL 是 `["wsl","-d","Ubuntu-24.04","--","bash","-lc"]`；
  在 Linux 集群上本地跑 runner 则留空（默认 `bash -lc`）。
- `launcher`：`direct` 之外的字符串是模板，`{cmd}` 会被替换成运行命令，
  例如 `"srun -n 16 --mpi=pmix {cmd}"` 或 `"mpirun -np 16 {cmd}"`。
- `exec.work_root`：执行侧看到的 runs 路径。Windows runner + WSL 执行时用
  `/mnt/e/...`；runner 与执行同机时留空。

注意：runner 只在**本地**写输入文件。如果 `shell_prefix` 是 `ssh ...` 这类远程
执行，远端必须能看到 runs/ 目录（共享盘或提前 rsync）。集群首推"把技能仓库同步
到集群、在集群登录节点本地跑 runner"的方式。`smoke_env.yaml` 文件尾部有完整的
srun 环境示例注释。

## 依赖与解析器

`run_smoke.py` 纯 stdlib。配置文件解析顺序：

1. 环境装有 PyYAML → `yaml.safe_load` 解析 `.yaml`；
2. 无 PyYAML → 内置 YAML 子集解析器（足够解析本目录的两个 `.yaml`）；
3. `--env-file` / `--cases-file` 传 `.json` → 直接 `json.load`（适合想绕开
   YAML 的环境，可自行把 YAML 转成同名 JSON）。

### 附录 A：内置 YAML 子集语法

- 块映射 `key: value`、块列表 `- item`（含 `- key: value` 行内映射起始），
  2 空格缩进；
- 字面块 `key: |` / `key: |-`（内容原样保留，用于内联输入文件）；
- flow 集合 `[a, b]` / `{k: v}`（元素限标量，可嵌套集合）；
- 标量：int / float / true / false / null / `~` / 单双引号字符串 / 裸字符串；
- `#` 注释（引号内除外）。

不支持：锚点/别名（`&`/`*`）、多文档流（`---`）、标签（`!`）、折叠块（`>`）、
列表项内字面块（`- |`）。超出子集会抛 `YamlSubsetError` —— 装 PyYAML 或改 JSON
即可绕开。
