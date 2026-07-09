"""
IFC -> BIM_Ontology mapping engine.

Pipeline:
  1. open IFC with ifcopenshell
  2. steel-structure detection (materials + element-type taxonomy fit)
  3. element extraction (placement, profile dims, project info)
  4. classification into ontology classes (Stud/Track/Joist/Nogging/Fastener)
  5. connection detection via axis-aligned bounding-box overlap
  6. emit structured JSON + a TTL conformant to the corrected BIM_Ontology
     (reified Geometric_Information / Project_information nodes, connectsElement,
     hasIntersection, and rule-materialised Crossing typing)

Geometry is derived analytically from IfcLocalPlacement + profile/quantity
dimensions, so no OpenCASCADE shape compilation is required and the engine runs
on any IFC2X3/IFC4 file that carries placements. Classification rules live in
CLASS_RULES (single editable table) so the taxonomy is easy to extend.
"""
from __future__ import annotations
import os, re, math, datetime
from pathlib import Path
import ifcopenshell
import rdflib
from rdflib import Graph, Namespace, Literal, URIRef, RDF, RDFS, OWL, XSD
from rdflib.collection import Collection
from rdflib import BNode
import pandas as pd

NS = Namespace("http://www.semanticweb.org/mmari/ontologies/2026/0/BIM_Ontology#")
TBOX = Path(__file__).parent / "tbox.ttl"

# ---- steel material signals ------------------------------------------------
STEEL_PAT = re.compile(
    r"steel|metal|galv|cold[\s\-]?form|cold[\s\-]?roll|"
    r"\bs235\b|\bs275\b|\bs355\b|\bg550\b|\bg350\b|gauge",
    re.I,
)

# ---- classification table (ordered; first hit wins) ------------------------
# Each rule: (ontology_class, ifc_type_set_or_None, name_regex_or_None)
CLASS_RULES = [
    ("Fastener",  {"IfcMechanicalFastener", "IfcFastener", "IfcDiscreteAccessory"}, None),
    ("Fastener",  None, r"connector|fastener|bracket|clip|gusset|screw|bolt|rivet|anchor"),
    ("Track",     None, r"\btrack\b|\bu[\-_ ]?section\b|\bu1\d{3}\b|runner"),
    ("Nogging",   None, r"nogg|nogging|noggin|blocking|dwang|bridging"),
    ("Stud",      None, r"\bstud\b"),                # 'Stud-Joist' -> Stud (matches source data)
    ("Joist",     None, r"\bjoist\b|\brafter\b"),
    ("Stud",      None, r"\bc[\-_ ]?section\b|\bc1\d{3}\b"),
]
# IFC types considered candidate structural members at all
MEMBER_TYPES = {
    "IfcMember", "IfcBeam", "IfcColumn", "IfcPlate", "IfcMemberStandardCase",
    "IfcBeamStandardCase", "IfcColumnStandardCase", "IfcMechanicalFastener",
    "IfcFastener", "IfcDiscreteAccessory", "IfcBuildingElementProxy",
}
GAP_TOL = 50.0          # mm: max bbox gap to count as a connection
# families that are not physical structural members (voids, annotation, holes)
EXCLUDE_NAME = re.compile(r"service\s*hole|opening|\bvoid\b|\bhole\b|punch(?:ing)?|"
                          r"annotation|service\s*penetration", re.I)
PARALLEL_TOL = 10.0     # deg: axes within this of 0/180 are 'parallel'
PERP_TOL = 7.0          # deg: axes within this of 90 are a 'right angle'
COLOCATE_TOL = 3.0      # mm: two contact points closer than this are co-located


def _clamp01(v):
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def _segment_contact(ei, ej):
    """Closest-approach contact point between the two member segments (midpoint
    of the closest points) and the clear gap. Returns (point_xyz|None, gap|None);
    None when a segment is unavailable (fall back to the bbox centroid)."""
    import numpy as np
    if not (ei.get("p0") and ei.get("p1") and ej.get("p0") and ej.get("p1")):
        return None, None
    P1 = np.array(ei["p0"]); Q1 = np.array(ei["p1"])
    P2 = np.array(ej["p0"]); Q2 = np.array(ej["p1"])
    d1 = Q1 - P1; d2 = Q2 - P2; r = P1 - P2
    a = float(d1.dot(d1)); e = float(d2.dot(d2)); ff = float(d2.dot(r)); eps = 1e-9
    if a < eps and e < eps:
        s = t = 0.0
    elif a < eps:
        s = 0.0; t = _clamp01(ff / e)
    else:
        c = float(d1.dot(r))
        if e < eps:
            t = 0.0; s = _clamp01(-c / a)
        else:
            b = float(d1.dot(d2)); denom = a * e - b * b
            s = _clamp01((b * ff - c * e) / denom) if denom > eps else 0.0
            t = (b * s + ff) / e
            if t < 0:
                t = 0.0; s = _clamp01(-c / a)
            elif t > 1:
                t = 1.0; s = _clamp01((b - c) / a)
    c1 = P1 + d1 * s; c2 = P2 + d2 * t
    r_i = 0.5 * max(ei.get("width") or 0.0, ei.get("depth") or 0.0, 0.0)
    r_j = 0.5 * max(ej.get("width") or 0.0, ej.get("depth") or 0.0, 0.0)
    gap = max(0.0, float(np.linalg.norm(c1 - c2)) - r_i - r_j)
    return ((c1 + c2) / 2.0).tolist(), gap


def _angle_deg(a, b):
    """Acute angle (0..90 deg) between two axis vectors; None if unavailable."""
    import numpy as np
    if not a or not b:
        return None
    va, vb = np.array(a), np.array(b)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return None
    c = abs(float(np.dot(va, vb)) / (na * nb))
    c = max(0.0, min(1.0, c))
    return math.degrees(math.acos(c))


def _ends_at(el, P):
    """True if contact point P falls near an endpoint of the member (the member
    terminates at the joint) rather than along its span."""
    import numpy as np
    p0, p1 = el.get("p0"), el.get("p1")
    if not p0 or not p1:
        return False
    a = np.array(p0); b = np.array(p1); p = np.array(P)
    L = float(np.linalg.norm(b - a))
    if L < 1e-6:
        return True
    t = float(np.dot(p - a, (b - a) / L))          # param along axis, 0..L
    end_tol = max(el.get("depth") or 0.0, el.get("width") or 0.0, 10.0)
    return t <= end_tol or t >= L - end_tol


def _classify_connection(ei, ej, P, gap):
    """Return one of Perpendicular / Crossing / Angled / Lateral, or 'Connection'
    when axes are unavailable or a fastener is involved (the geometric joint
    taxonomy describes member-to-member junctions, not fastenings)."""
    if ei["cls"] == "Fastener" or ej["cls"] == "Fastener":
        return "Connection"
    theta = _angle_deg(ei.get("axis"), ej.get("axis"))
    if theta is None:
        return "Connection"
    if theta <= PARALLEL_TOL:
        return "Lateral"
    end_i = _ends_at(ei, P)
    end_j = _ends_at(ej, P)
    if not end_i and not end_j:
        return "Crossing"                          # both members run through
    if abs(theta - 90.0) <= PERP_TOL:
        return "Perpendicular"                     # T-junction at right angle
    return "Angled"                                # T/Y junction at a skew angle


def _local(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", s)


# --------------------------------------------------------------------------- #
# IFC reading helpers
# --------------------------------------------------------------------------- #
def _placement_point(elem):
    """World XYZ of the element's local placement origin (mm)."""
    m = _matrix(elem)
    if m is None:
        return None
    return float(m[0][3]), float(m[1][3]), float(m[2][3])


def _matrix(elem):
    try:
        return ifcopenshell.util.placement.get_local_placement(elem.ObjectPlacement)
    except Exception:
        return None


def _dir(d):
    import numpy as np
    v = np.array(d.DirectionRatios, dtype=float)
    n = np.linalg.norm(v)
    return v / n if n else v


def _a2p_rot(p):
    """3x3 rotation (cols x,y,z) of an IfcAxis2Placement3D."""
    import numpy as np
    z = _dir(p.Axis) if getattr(p, "Axis", None) else np.array([0.0, 0, 1])
    x = _dir(p.RefDirection) if getattr(p, "RefDirection", None) else np.array([1.0, 0, 0])
    x = x - np.dot(x, z) * z
    nx = np.linalg.norm(x)
    x = x / nx if nx else np.array([1.0, 0, 0])
    return np.column_stack([x, np.cross(z, x), z])


def _extrusion(elem):
    """(world_axis_unit, depth, base_point_world) from the first extruded-area
    solid body, transformed by the object placement; None if not found."""
    import numpy as np
    M = _matrix(elem)
    rep = getattr(elem, "Representation", None)
    if M is None or not rep:
        return None
    for r in rep.Representations or []:
        for item in r.Items or []:
            it = item
            if it.is_a("IfcMappedItem"):
                items = it.MappingSource.MappedRepresentation.Items
                it = items[0] if items else None
            if it is not None and it.is_a("IfcExtrudedAreaSolid"):
                d_local = _dir(it.ExtrudedDirection)
                base_local = np.zeros(3)
                if it.Position is not None:
                    d_local = _a2p_rot(it.Position).dot(d_local)
                    base_local = np.array(it.Position.Location.Coordinates, dtype=float)
                R, t = M[:3, :3], M[:3, 3]
                d_world = R.dot(d_local)
                nrm = np.linalg.norm(d_world)
                if nrm:
                    d_world = d_world / nrm
                return d_world, float(it.Depth), R.dot(base_local) + t
    return None


def _axis_from_axis_rep(elem):
    """Endpoints from an 'Axis' representation (IfcPolyline centreline), the most
    reliable source for Revit beams. Points (often 2D) are padded to 3D and
    transformed by the object placement. Returns (axis, p0, p1) or None."""
    import numpy as np
    M = _matrix(elem)
    rep = getattr(elem, "Representation", None)
    if M is None or not rep:
        return None
    for r in rep.Representations or []:
        if r.RepresentationIdentifier != "Axis":
            continue
        for it in r.Items or []:
            if it.is_a("IfcPolyline") and it.Points and len(it.Points) >= 2:
                def w(p):
                    c = list(p.Coordinates)
                    if len(c) == 2:
                        c = [c[0], c[1], 0.0]
                    return (M @ np.array([c[0], c[1], c[2], 1.0]))[:3]
                p0 = w(it.Points[0]); p1 = w(it.Points[-1])
                d = p1 - p0; n = np.linalg.norm(d)
                if n < 1e-6:
                    continue
                return (d / n).tolist(), p0.tolist(), p1.tolist()
    return None


_PROFILE_CODE = re.compile(r"\b([CUZLT])(\d{3})(\d{2})-(\d{1,2})\b")


def _dims_from_name(name):
    """Recover (width, depth, thickness) mm from a Revit MF profile code such as
    'C10251-15' (C 102x51x1.5) or 'U10758-15', used only when no parametric
    profile is attached. Returns {} if the name doesn't match."""
    if not name:
        return {}
    mobj = _PROFILE_CODE.search(name)
    if not mobj:
        return {}
    depth = float(mobj.group(2))
    width = float(mobj.group(3))
    thick = float(mobj.group(4)) / 10.0
    return {"depth": depth, "width": width, "thickness": thick}


def _axis_endpoints(elem, length):
    """Return (axis_unit|None, p0|None, p1|None) in world mm. Order of preference:
    Axis centreline polyline -> extrusion body -> local +Z over `length`."""
    import numpy as np
    ax = _axis_from_axis_rep(elem)
    if ax is not None:
        return ax
    ext = _extrusion(elem)
    if ext is not None:
        d, depth, base = ext
        return d.tolist(), base.tolist(), (base + depth * d).tolist()
    M = _matrix(elem)
    if M is None:
        return None, None, None
    d = M[:3, :3].dot(np.array([0.0, 0, 1]))
    nrm = np.linalg.norm(d)
    d = d / nrm if nrm else d
    t = M[:3, 3]
    if length:
        return d.tolist(), t.tolist(), (t + length * d).tolist()
    return d.tolist(), t.tolist(), t.tolist()


def _quantities(elem):
    out = {}
    for rel in getattr(elem, "IsDefinedBy", []) or []:
        if rel.is_a("IfcRelDefinesByProperties"):
            pdef = rel.RelatingPropertyDefinition
            if pdef and pdef.is_a("IfcElementQuantity"):
                for q in pdef.Quantities or []:
                    for attr in ("LengthValue", "AreaValue", "VolumeValue", "WeightValue"):
                        if hasattr(q, attr) and getattr(q, attr) is not None:
                            out[q.Name] = float(getattr(q, attr))
    return out


def _profile_dims(elem):
    """Width/Depth/Thickness from an associated parametric profile, if any."""
    dims = {}
    try:
        for rel in getattr(elem, "HasAssociations", []) or []:
            if rel.is_a("IfcRelAssociatesMaterial"):
                mat = rel.RelatingMaterial
                profiles = []
                if mat.is_a("IfcMaterialProfileSetUsage"):
                    profiles = mat.ForProfileSet.MaterialProfiles or []
                elif mat.is_a("IfcMaterialProfileSet"):
                    profiles = mat.MaterialProfiles or []
                for mp in profiles:
                    p = mp.Profile
                    if p is None:
                        continue
                    # width: Width (C), FlangeWidth (U/L), OverallWidth (I)
                    for w in ("Width", "FlangeWidth", "OverallWidth"):
                        if getattr(p, w, None):
                            dims["width"] = float(getattr(p, w)); break
                    # depth: Depth (C/U), OverallDepth (I)
                    for d in ("Depth", "OverallDepth"):
                        if getattr(p, d, None):
                            dims["depth"] = float(getattr(p, d)); break
                    # thickness: WallThickness (C), WebThickness (U/I), Thickness (L)
                    for t in ("WallThickness", "WebThickness", "Thickness"):
                        if getattr(p, t, None):
                            dims["thickness"] = float(getattr(p, t)); break
    except Exception:
        pass
    return dims


def _materials(elem):
    names = []
    try:
        for rel in getattr(elem, "HasAssociations", []) or []:
            if rel.is_a("IfcRelAssociatesMaterial"):
                mat = rel.RelatingMaterial
                names += _material_names(mat)
    except Exception:
        pass
    return names


def _material_names(mat):
    out = []
    if mat is None:
        return out
    if mat.is_a("IfcMaterial"):
        out.append(mat.Name)
    elif mat.is_a("IfcMaterialList"):
        for m in mat.Materials or []:
            out += _material_names(m)
    elif mat.is_a("IfcMaterialLayerSetUsage"):
        out += _material_names(mat.ForLayerSet)
    elif mat.is_a("IfcMaterialLayerSet"):
        for l in mat.MaterialLayers or []:
            if l.Material: out.append(l.Material.Name)
    elif mat.is_a("IfcMaterialProfileSetUsage"):
        out += _material_names(mat.ForProfileSet)
    elif mat.is_a("IfcMaterialProfileSet"):
        for p in mat.MaterialProfiles or []:
            if p.Material: out.append(p.Material.Name)
    return [n for n in out if n]


def _storey(elem):
    try:
        for rel in getattr(elem, "ContainedInStructure", []) or []:
            s = rel.RelatingStructure
            if s and s.is_a("IfcBuildingStorey"):
                return s.Name
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
# classification & geometry
# --------------------------------------------------------------------------- #
def classify(ifc_type, name):
    nm = name or ""
    for cls, types, pat in CLASS_RULES:
        if types and ifc_type in types:
            return cls
        if pat and re.search(pat, nm, re.I):
            return cls
    return "Structural_element"


def _bbox(el):
    """Axis-aligned bbox (mm) around the member segment p0->p1, expanded by the
    cross-section radius. Falls back to a box centred on the placement point when
    no segment is available."""
    p0, p1 = el.get("p0"), el.get("p1")
    r = 0.5 * max(el.get("width") or 0.0, el.get("depth") or 0.0, 1.0)
    if p0 and p1:
        lo = [min(p0[i], p1[i]) - r for i in range(3)]
        hi = [max(p0[i], p1[i]) + r for i in range(3)]
        return (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2])
    p = el.get("pos")
    if p is None:
        return None
    L = el.get("length") or 0.0
    W = el.get("width") or el.get("depth") or 0.0
    D = el.get("depth") or el.get("width") or 0.0
    hx, hy, hz = L / 2.0, W / 2.0, D / 2.0
    x, y, z = p
    return (x - hx, y - hy, z - hz, x + hx, y + hy, z + hz)


def _overlap_1d(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


CELL = 1000.0          # mm: spatial-hash cell size
MAX_CELLS_PER_BOX = 4096  # guard against pathological coordinate ranges


def _cells_for_box(b, pad):
    """Grid cells an (optionally padded) box touches; None if it spans too many."""
    x0, y0, z0, x1, y1, z1 = b
    ix0, ix1 = int((x0 - pad) // CELL), int((x1 + pad) // CELL)
    iy0, iy1 = int((y0 - pad) // CELL), int((y1 + pad) // CELL)
    iz0, iz1 = int((z0 - pad) // CELL), int((z1 + pad) // CELL)
    n = (ix1 - ix0 + 1) * (iy1 - iy0 + 1) * (iz1 - iz0 + 1)
    if n > MAX_CELLS_PER_BOX:
        return None
    return [(cx, cy, cz)
            for cx in range(ix0, ix1 + 1)
            for cy in range(iy0, iy1 + 1)
            for cz in range(iz0, iz1 + 1)]


def detect_connections(elements):
    """Bbox-proximity connections via a uniform spatial hash (near-linear).

    Each box is registered in the grid cells its GAP-padded extent covers, so
    only spatially-near pairs are ever compared. Pathologically large boxes fall
    into an 'oversized' bucket compared against everything (rare)."""
    boxes = [(e, _bbox(e)) for e in elements]
    boxes = [(e, b) for e, b in boxes if b]

    grid = {}            # cell -> [index,...]
    oversized = []       # indices whose box spans too many cells
    for idx, (_, b) in enumerate(boxes):
        cells = _cells_for_box(b, GAP_TOL)
        if cells is None:
            oversized.append(idx)
            continue
        for c in cells:
            grid.setdefault(c, []).append(idx)

    candidates = set()   # unordered index pairs to test
    for members in grid.values():
        m = len(members)
        if m < 2:
            continue
        for i in range(m):
            for j in range(i + 1, m):
                a, c = members[i], members[j]
                candidates.add((a, c) if a < c else (c, a))
    for o in oversized:                       # compare oversized against all
        for k in range(len(boxes)):
            if k != o:
                candidates.add((o, k) if o < k else (k, o))

    conns = []
    for (i, j) in candidates:
        ei, bi = boxes[i]; ej, bj = boxes[j]
        # fasteners are joiners, not members that 'cross'; skip fastener-fastener
        if ei["cls"] == "Fastener" and ej["cls"] == "Fastener":
            continue
        if True:
            ox = _overlap_1d(bi[0], bi[3], bj[0], bj[3])
            oy = _overlap_1d(bi[1], bi[4], bj[1], bj[4])
            oz = _overlap_1d(bi[2], bi[5], bj[2], bj[5])
            # gap = separation on the most-separated axis (0 if boxes intersect)
            gx = max(0.0, max(bi[0], bj[0]) - min(bi[3], bj[3]))
            gy = max(0.0, max(bi[1], bj[1]) - min(bi[4], bj[4]))
            gz = max(0.0, max(bi[2], bj[2]) - min(bi[5], bj[5]))
            gap = max(gx, gy, gz)
            if gap > GAP_TOL:
                continue
            cx = (max(bi[0], bj[0]) + min(bi[3], bj[3])) / 2.0
            cy = (max(bi[1], bj[1]) + min(bi[4], bj[4])) / 2.0
            cz = (max(bi[2], bj[2]) + min(bi[5], bj[5])) / 2.0
            seg_pt, seg_gap = _segment_contact(ei, ej)
            if seg_pt is not None:
                cx, cy, cz = seg_pt
                gap = seg_gap
            ctype = _classify_connection(ei, ej, (cx, cy, cz), gap)
            kind = "fastening" if (ei["cls"] == "Fastener" or ej["cls"] == "Fastener") else "joint"
            conns.append({
                "id": f"conn_{ei['gid']}_{ej['gid']}",
                "a": ei["gid"], "b": ej["gid"],
                "overlapX": ox, "overlapY": oy, "overlapZ": oz,
                "gap": gap, "contactX": cx, "contactY": cy, "contactZ": cz,
                "ctype": ctype, "kind": kind,
            })

    # Double_Angled: any two Angled connections whose contact points coincide
    # within COLOCATE_TOL (regardless of shared member) -> retype both.
    angled = [c for c in conns if c["ctype"] == "Angled"]
    for m in range(len(angled)):
        for n in range(m + 1, len(angled)):
            ca, cb = angled[m], angled[n]
            d2 = ((ca["contactX"] - cb["contactX"]) ** 2 +
                  (ca["contactY"] - cb["contactY"]) ** 2 +
                  (ca["contactZ"] - cb["contactZ"]) ** 2)
            if d2 <= COLOCATE_TOL ** 2:
                ca["ctype"] = "Double_Angled"
                cb["ctype"] = "Double_Angled"

    conns.sort(key=lambda c: c["id"])
    return conns


# --------------------------------------------------------------------------- #
# main analysis
# --------------------------------------------------------------------------- #
def analyse(ifc_path):
    import ifcopenshell.util.placement  # noqa: ensures submodule import
    model = ifcopenshell.open(ifc_path)
    schema = model.schema

    elements = []
    for t in MEMBER_TYPES:
        try:
            insts = model.by_type(t)
        except Exception:
            continue
        for el in insts:
            name = getattr(el, "Name", None)
            if EXCLUDE_NAME.search(name or ""):
                continue
            gid = el.GlobalId if hasattr(el, "GlobalId") and el.GlobalId else f"{el.id()}"
            mats = _materials(el)
            q = _quantities(el)
            dims = _profile_dims(el)
            if not dims.get("width") and not dims.get("depth"):
                dims.update(_dims_from_name(name))
            length = q.get("Length") or dims.get("length")
            axis, p0, p1 = _axis_endpoints(el, length)
            if (length is None) and p0 and p1:
                import numpy as np
                length = float(np.linalg.norm(np.array(p1) - np.array(p0))) or None
            elements.append({
                "gid": _local(gid),
                "ifc_type": el.is_a(),
                "name": name,
                "materials": mats,
                "pos": _placement_point(el),
                "axis": axis, "p0": p0, "p1": p1,
                "length": length,
                "width": dims.get("width"),
                "depth": dims.get("depth"),
                "thickness": dims.get("thickness"),
                "area": q.get("CrossSectionArea") or q.get("Area"),
                "storey": _storey(el),
                "cls": None,
            })
    for e in elements:
        e["cls"] = classify(e["ifc_type"], e["name"])

    # ---- steel detection ----
    all_mats = [m for e in elements for m in e["materials"]]
    steel_mats = sorted({m for m in all_mats if STEEL_PAT.search(m or "")})
    framing = [e for e in elements if e["cls"] in {"Stud", "Track", "Joist", "Nogging", "Fastener"}]
    frac_framing = (len(framing) / len(elements)) if elements else 0.0
    is_steel = bool(steel_mats) or (len(framing) >= 2 and frac_framing >= 0.4)
    if steel_mats and framing:
        reason = f"steel materials present ({', '.join(steel_mats)}) and {len(framing)} framing members recognised"
    elif steel_mats:
        reason = f"steel materials present ({', '.join(steel_mats)})"
    elif framing:
        reason = f"no explicit steel material, but {len(framing)}/{len(elements)} members fit the light-gauge framing taxonomy"
    else:
        reason = "no steel materials and no recognisable framing members"

    connections = detect_connections(elements) if is_steel else []

    conn_types = {}      # geometric types over member-to-member joints only
    n_fastenings = 0
    for c in connections:
        if c["kind"] == "fastening":
            n_fastenings += 1
        else:
            conn_types[c["ctype"]] = conn_types.get(c["ctype"], 0) + 1

    notes = []
    if len(elements) > 20000:
        notes.append(f"large model ({len(elements)} members) — connection detection used a "
                     f"spatial index; review GAP_TOL/CELL if results look off")
    no_pos = sum(1 for e in elements if e["pos"] is None)
    if no_pos:
        notes.append(f"{no_pos} member(s) had no resolvable placement and were excluded from "
                     f"connection detection")
    no_axis = sum(1 for e in elements if not e.get("axis") and e["cls"] not in {"Fastener"})
    if no_axis:
        notes.append(f"{no_axis} member(s) had no resolvable axis (no extrusion body) — their "
                     f"connections are reported as generic Connection, not a sub-type")

    summary = {
        "file": os.path.basename(ifc_path),
        "schema": schema,
        "is_steel": is_steel,
        "reason": reason,
        "steel_materials": steel_mats,
        "counts": _class_counts(elements),
        "n_elements": len(elements),
        "n_connections": len(connections),
        "n_joints": sum(1 for c in connections if c["kind"] == "joint"),
        "n_fastenings": n_fastenings,
        "connection_types": conn_types,
        "n_crossings": conn_types.get("Crossing", 0),
        "notes": notes,
        "elements": elements,
        "connections": connections,
    }
    return summary, model


def _class_counts(elements):
    out = {}
    for e in elements:
        out[e["cls"]] = out.get(e["cls"], 0) + 1
    return out


# --------------------------------------------------------------------------- #
# ontology (ABox) emission
# --------------------------------------------------------------------------- #
def to_ttl(summary):
    g = Graph()
    g.parse(str(TBOX), format="turtle")   # TBox: classes, properties, disjointness, SWRL
    g.bind("", NS)

    def U(x): return URIRef(str(NS) + x)
    def f(v): return Literal(float(v), datatype=XSD.float)

    for e in summary["elements"]:
        s = U(e["gid"])
        g.add((s, RDF.type, OWL.NamedIndividual))
        g.add((s, RDF.type, U(e["cls"])))
        # reified Geometric_Information node
        geo_vals = {"hasWidth": e["width"], "hasThickness": e["thickness"],
                    "hasLength": e["length"], "hasNetCrossSectionalArea": e["area"]}
        if e["depth"] is not None:
            geo_vals["hasHeight"] = e["depth"]
        if e["pos"]:
            geo_vals["hasX"], geo_vals["hasY"], geo_vals["hasZ"] = e["pos"]
        geo_vals = {k: v for k, v in geo_vals.items() if v is not None}
        if geo_vals:
            gn = U(e["gid"] + "_geom")
            g.add((gn, RDF.type, OWL.NamedIndividual)); g.add((gn, RDF.type, U("Geometric_Information")))
            g.add((s, U("hasGeometricInformation"), gn))
            for k, v in geo_vals.items():
                g.add((gn, U(k), f(v)))
        # reified Project_information node
        pn_added = False
        pn = U(e["gid"] + "_proj")
        if e["name"]:
            g.add((pn, U("hasName"), Literal(e["name"], datatype=XSD.string))); pn_added = True
        if e["storey"]:
            g.add((pn, U("hasStorey"), Literal(e["storey"], datatype=XSD.string))); pn_added = True
        if pn_added:
            g.add((pn, RDF.type, OWL.NamedIndividual)); g.add((pn, RDF.type, U("Project_information")))
            g.add((s, U("hasProjectInformation"), pn))

    for c in summary["connections"]:
        cn = U(c["id"])
        g.add((cn, RDF.type, OWL.NamedIndividual)); g.add((cn, RDF.type, U("Connection")))
        if c["ctype"] != "Connection":
            g.add((cn, RDF.type, U(c["ctype"])))     # geometric classification
        g.add((cn, U("connectsElement"), U(c["a"])))
        g.add((cn, U("connectsElement"), U(c["b"])))
        g.add((U(c["a"]), U("hasIntersection"), cn))
        g.add((U(c["b"]), U("hasIntersection"), cn))
        for k, prop in (("overlapX", "hasOverlapX"), ("overlapY", "hasOverlapY"),
                        ("overlapZ", "hasOverlapZ"), ("gap", "hasGapDistance"),
                        ("contactX", "hasContactX"), ("contactY", "hasContactY"),
                        ("contactZ", "hasContactZ")):
            g.add((cn, U(prop), f(c[k])))

    return g.serialize(format="turtle")

def get_fasteners_table(summary):
    """
    Returns a pandas DataFrame containing all detected fasteners.
    Input:
        summary -> returned from analyse(ifc_path)
    """

    rows = []

    for e in summary["elements"]:
        if e["cls"] != "Fastener":
            continue

        rows.append({
            "GlobalId": e["gid"],
            "Name": e["name"],
            "IFC Type": e["ifc_type"],
            "Storey": e["storey"],
            "Material": ", ".join(e["materials"]) if e["materials"] else "",
            "Length (mm)": e["length"],
            "Width (mm)": e["width"],
            "Depth (mm)": e["depth"],
            "Thickness (mm)": e["thickness"],
            "Position": e["pos"]
        })

    return pd.DataFrame(rows)
