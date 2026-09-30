## V13: Si Bulk — Optical Properties

**Task:** Static SCF with optical dielectric tensor calculation.

**System:** 2 Si atoms, diamond cubic (conventional cell).

**Key settings:**
- `LOPTICS = .TRUE.`, `CSHIFT = 0.1` eV, `NEDOS = 3000`
- `ISMEAR = 0`, `SIGMA = 0.05` eV (semiconductor — small smearing)
- `ISPIN = 1`, `LREAL = .FALSE.` (small cell, accurate static)
- K-mesh: 14x14x14 Gamma-centered (dense mesh critical for smooth optical spectra)

**Note:** For publication-quality optics, a separate NSCF run on an even denser k-mesh is recommended.

**Files:** `INCAR`, `KPOINTS`, `POSCAR` (POTCAR required)
