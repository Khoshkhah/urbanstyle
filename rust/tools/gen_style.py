"""Writes rust/urbanstyle-model/src/style.rs from the Python tables (meta.STYLE, meta.CODE, parts.RAISED, parts.KERB_TOP_M).

    PYTHONPATH=src python rust/tools/gen_style.py

Run it again when one of those lists changes. Run it with the duckOSM environment."""
from urbanstyle import meta
from urbanstyle.parts import KERB_TOP_M, RAISED

opt_i = lambda x: "None" if x is None else f"Some({x})"
opt_s = lambda x: "None" if x is None else 'Some("%s")' % x
L = [
    "//! `urban.style` (how a viewer draws each kind, docs/design/drawing.md) and `urban.code` (our kinds in the standards, docs/design/tables.md).",
    "//! Generated from `meta.STYLE`, `meta.CODE`, `parts.RAISED` and `parts.KERB_TOP_M` of the Python code (rust/tools/gen_style.py); do not edit.",
    "",
    "/// table, rank, kind, draw order, form, colour, dash (metres on, off), raise in 3D (m)",
    "pub type StyleRow = (&'static str, Option<i32>, &'static str, i32, &'static str, &'static str, Option<[f64; 2]>, f64);",
    "pub const STYLE: &[StyleRow] = &[",
]
for t, r, k, o, f, c, d in meta.STYLE:
    raise_m = KERB_TOP_M if (t, k) == ("urban.mark", "kerb") else (RAISED.get(k, 0.0) if t in ("urban.part", "urban.mark") else 0.0)
    dash = "None" if d is None else "Some([%r, %r])" % (float(d[0]), float(d[1]))
    L.append(f'    ("{t}", {opt_i(r)}, "{k}", {o}, "{f}", "{c}", {dash}, {float(raise_m)!r}),')
L += ["];", "", "/// kind, CityGML 3.0, OpenDRIVE 1.9, OpenSidewalks, IFC 4.3",
      "pub type CodeRow = (&'static str, Option<&'static str>, Option<&'static str>, Option<&'static str>, Option<&'static str>);",
      "pub const CODE: &[CodeRow] = &["]
for k, a, b, c, d in meta.CODE:
    L.append(f'    ("{k}", {opt_s(a)}, {opt_s(b)}, {opt_s(c)}, {opt_s(d)}),')
L.append("];")
open("rust/urbanstyle-model/src/style.rs", "w").write("\n".join(L) + "\n")
print(len(meta.STYLE), "style rows,", len(meta.CODE), "code rows")
