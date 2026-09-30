## L4: H2O Molecule — NVE with MLFF

**Task:** NVE (microcanonical) MD of an isolated H2O molecule using a MACE potential.

**System:** 1 H2O molecule in a 20 Å box (3 atoms, from `system_H2O.data`).

**Key settings:**
- `pair_style mace`, `pair_coeff * * mace.model H O`
- Ensemble: NVE (no thermostat)
- Timestep: 0.5 fs (H present)
- Dump: unwrapped coordinates (`xu yu zu`) for MSD analysis
- Run: 100 ps production

**Validation:** Check energy conservation (`etotal` drift < 1 meV/atom/ps).

**Files:** `input.nve`, `system.data` (copied from `system_H2O.data`)
