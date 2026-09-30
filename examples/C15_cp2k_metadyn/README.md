# C15 · CP2K Metadynamics（well-tempered，水二聚体 O–O 距离 CV）

**演示要点**：`&MOTION/&FREE_ENERGY/&METADYN` 元动力学自由能计算骨架。

- CV 定义在 `FORCE_EVAL/SUBSYS/&COLVAR`（本例：`&DISTANCE ATOMS 1 4`，两水分子 O–O 距离）
- `DO_HILLS .TRUE.` + `NT_HILLS 100`：每 100 步 MD 撒一个高斯丘；`WW [kcalmol] 1.5`（典型 0.5–2 kcal/mol）
- `&METAVAR`：`SCALE 0.5`（丘宽，CV 单位）+ `COLVAR 1`（指向 SUBSYS 中第 1 个 COLVAR）
- `&WALL TYPE QUARTIC`：限制 CV 上限 5 Å，防止二聚体解离飞出
- well-tempered：`WELL_TEMPERED .TRUE.` + `WTGAMMA 20`（典型 10–50），自由能面随时间收敛
- `&PRINT/&COLVAR` 与 `&PRINT/&HILLS`：各含 `COMMON_ITERATION_LEVELS 3` + `&EACH MD 10`，HILLS 文件用于 sum_hills 重建 FES

结构：`coord.xyz`（6 原子水二聚体）。生产计算需把 STEPS 提高到 1E5–1E6 量级。
