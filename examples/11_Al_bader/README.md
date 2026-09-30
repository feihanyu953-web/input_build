## V11: Al FCC Bulk — Bader Charge Analysis

**Task:** Static SCF calculation for Bader charge partitioning.

**System:** 4 Al atoms, FCC bulk (cubic, a = 4.0495 Å).

**Key settings:**
- `PREC = Accurate`, `ENCUT = 400`
- `ICHARG = 2` (full SCF from scratch; switch to `ICHARG = 1` if restarting from CHGCAR)
- `LAECHG = .TRUE.` (required for Bader; writes AECCAR0/AECCAR2)
- `NGXF/NGYF/NGZF` intentionally commented — user must set ~2x default FFT grid
- K-mesh: 9x9x9 Monkhorst-Pack (spacing ~0.18 Å⁻¹)

**Post-processing:**
```bash
chgsum.pl AECCAR0 AECCAR2      # sum core + valence densities -> CHGCAR_sum
bader CHGCAR -ref CHGCAR_sum   # partition CHGCAR against the total-density reference
```
(AECCAR0 or AECCAR2 alone are NOT valid references; never run `bader AECCAR0 AECCAR2`.)

**Files:** `INCAR`, `KPOINTS`, `POSCAR` (POTCAR required)
