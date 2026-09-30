# C14 · CP2K SCCS 隐式溶剂化（H₂O 分子）

**演示要点**：`&DFT/&SCCS` 连续介质溶剂化（Andreussi），水分子的 GEO_OPT。

- `DIELECTRIC_CONSTANT 78.36`（水），`EPS_SCCS 1.0E-7`（松散会静默输出零极化能）
- `SCCS%EPS_SCF` 与 `DFT%SCF%EPS_SCF` 保持一致（CP2K-user 列表确认的坑）
- 孤立分子：`&CELL PERIODIC NONE` + `&POISSON PERIODIC NONE / POISSON_SOLVER MT`
- 工作流：先气相收敛，再从 restart 开 SCCS

结构：`H2O.xyz`（3 原子水分子，复用 tests/fixtures）。
