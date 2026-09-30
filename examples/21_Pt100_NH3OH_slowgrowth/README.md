# 21 - Pt(100) + NH3 + OH, SG-AIMD proton transfer

Slow-growth AIMD (thermodynamic integration) for `NH3* + OH* -> NH2* + H2O*`
on Pt(100). Collective variable: the difference coordinate
`xi = d(N-H) - d(O-H)` for the transferring hydrogen.

## System

- Pt(100) 2x2, 4 layers (16 Pt), a = b = 5.5492 A, c = 25.0 A, vacuum ~16.3 A
  (inside the locally verified 15-17 A window; longer vacuum breeds charge
  sloshing).
- Adsorbates: NH3 atop Pt, OH atop the neighbouring Pt.
- Atom indices: Pt 1-16, N 17, H 18-21 (18 = transferring, 21 = OH hydrogen),
  O 22.

## Collective variable

`ICONST`:

```
R 17 18 0
R 22 18 0
S 1 -1 0
```

Three lines, ONE controlled parameter. Once a complex coordinate (`S`) is
present VASP ignores the status of every preceding primitive, so only the `S`
line is controlled and `INCREM` takes exactly one value. Counting the three
`STATUS=0` rows instead is the classic mistake.

- xi in POSCAR: d(N-H18) = 1.02 A, d(O-H18) = 1.756 A -> xi = -0.736 A
- xi target: +0.76 A (proton on O)
- NSW = 4000, POTIM = 1.0 fs -> 4 ps
- INCREM = (0.76 - (-0.736)) / 4000 = 3.74E-4 A/step = 0.374 A/ps

## How this was generated

```bash
# 1. Which NH3 hydrogen is pre-oriented toward the OH oxygen?
python ../../scripts/iconst_helper.py candidates \
    --poscar POSCAR --species H --acceptor 22
#    -> H21 (the OH's own H) is excluded as bonded; H18 at ~1.76 A wins

# 2. Verify the CV, compute INCREM, write ICONST and both stage INCARs
python ../../scripts/iconst_helper.py render \
    --poscar POSCAR \
    --cv "R 17 18" --cv "R 22 18" --cv "S 1 -1" \
    --xi -0.736 --xf 0.76 --nsw 4000 --potim 1.0 \
    --out ICONST --emit-incar \
    --template ../../base_templates/vasp_slowgrowth.incar \
    --incar-growth INCAR_growth --incar-equil INCAR_equil
```

The committed INCARs additionally carry the system-specific parameters the
helper deliberately leaves to the user: `ENCUT=520` (O present), `NBANDS=120`
(175 valence electrons -> ~88 occupied bands x 1.3), the verified metal+water
mixing trio `AMIX=0.02 / BMIX=1.0 / AMIN=0.01`, and `IDIPOL=3 / LDIPOL=.TRUE.`
for the single-sided adsorbate.

## Validation

```bash
python ../../scripts/validate_input.py --incar INCAR_equil \
    --poscar POSCAR --kpoints KPOINTS --iconst ICONST --task slowgrowth
python ../../scripts/validate_input.py --incar INCAR_growth \
    --poscar POSCAR --kpoints KPOINTS --iconst ICONST --task slowgrowth
```

Expected: `STATIC_PASS` with zero errors. `ENCUT_NOT_VERIFIED` appears on both
stages, because no POTCAR is distributed with the skill - ENCUT coverage is
therefore unresolved, not verified. `INCAR_growth` ships no other warning;
`INCAR_equil` additionally reports `SG_INCREM_ALL_ZERO`, which is the intended
equilibration-stage signature (the validator's own hint to switch to a
non-zero INCREM for growth).

## Running order

1. `INCAR_equil` - constrained MD holding xi at -0.736 A until the temperature
   and the constraint force are stationary.
2. `INCAR_growth` - restart from the equilibrated geometry (`cp CONTCAR POSCAR`)
   with the same ICONST.
3. Read the free-energy gradient from `REPORT` and integrate it along xi.

POTCAR is not included: prepare it yourself from a licensed VASP
pseudopotential library (element order Pt N H O).
