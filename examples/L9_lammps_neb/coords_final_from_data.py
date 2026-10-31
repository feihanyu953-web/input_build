#!/usr/bin/env python
# Build the coords.final file required by the neb "final" file-style from the
# minimized FS endpoint (final_min.data, atom_style atomic).
# usage: python coords_final_from_data.py final_min.data coords.final
import sys

src, dst = sys.argv[1], sys.argv[2]
lines = open(src).read().splitlines()
start = next(i for i, l in enumerate(lines) if l.startswith("Atoms"))
rows = []
for l in lines[start + 1:]:
    s = l.strip()
    if not s:
        continue
    if not s[0].isdigit():
        break  # next section (Velocities, ...) — write_data emits one after minimize
    rows.append(s.split())
with open(dst, "w") as f:
    f.write("%d\n" % len(rows))
    for r in rows:  # atomic style columns: id type x y z [ix iy iz]
        f.write("%s %s %s %s\n" % (r[0], r[2], r[3], r[4]))
print("wrote %d atoms -> %s" % (len(rows), dst))
