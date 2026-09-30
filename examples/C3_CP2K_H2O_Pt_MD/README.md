# C3: H2O-Pt(100) Interface NVT MD

**System:** H2O on Pt(100) slab (27 atoms: 1 H2O + 24 Pt)
**Task:** NVT molecular dynamics @ 300 K
**Method:** DFT-PBE with GPW, 400 Ry cutoff

## Key Settings

- **Cell:** 7.848 x 7.848 x 20.0 Å (surface slab with vacuum)
- **Periodicity:** XYZ
- **&KIND:** H, O, Pt
- **MD:** NVT ensemble, CSVR thermostat (TIMECON 100 fs)
- **Timestep:** 0.5 fs (safe for H)
- **Steps:** 5000 (2.5 ps total)
- **SCF_GUESS:** RESTART
- **No k-points:** large supercell

## Files

- `cp2k_md.inp` — CP2K input file
- `H2O_Pt.xyz` — Structure (H2O + Pt 2x2 surface slab)

## Usage

```bash
cp2k.popt -i cp2k_md.inp -o cp2k_md.out
```

Requires `BASIS_MOLOPT` and `GTH_POTENTIALS` files in the working directory.
A prior WFN restart file is recommended for SCF_GUESS RESTART.
