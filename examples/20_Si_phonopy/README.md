# 20 · Si 声子（phonopy 有限位移 + VASP 单点力）

**演示要点**：phonopy 工作流的高精度单点 INCAR（task = phonon）。

- `IBRION = -1` + `NSW = 0`：纯单点，不做离子弛豫（位移由 phonopy 生成）
- `EDIFF = 1E-8`：力进入动力学矩阵，SCF 必须极紧（validator：task=phonon 时 EDIFF > 1E-7 → WARN）
- `LWAVE / LCHARG = .FALSE.`：每个位移胞都不需要波函数/电荷文件
- 与 `12_Pt100_freq` 区分：freq 是 VASP 内部有限位移（IBRION=5，分子/吸附物振动）；
  本例是晶体声子，靠 phonopy 后处理
- DFPT 备选：`IBRION = 8`（不需要超胞/phonopy，但不能进 phonopy 生态）

工作流：
```bash
phonopy -d --dim="2 2 2"          # 生成 disp-001/ ... 位移超胞
# 对每个 disp-* 目录放本 INCAR + KPOINTS 跑 VASP
phonopy -f disp-*/vasprun.xml     # 收集力 -> FORCE_SETS
phonopy --dim="2 2 2" --band="..." # 声子谱
```

结构：Si 原胞（复制自 `tests/fixtures/POSCAR_Si`）；生产计算请用 phonopy
生成的 2×2×2 超胞，k 网格相应缩小（如 Gamma 2×2×2）。
