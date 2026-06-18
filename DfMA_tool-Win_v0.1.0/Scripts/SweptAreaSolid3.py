# swept_sweptarea_and_disksolid_from_guid.py
# PURPOSE
#   Inspect geometry for a single IfcProduct occurrence (provided by GUID) and report any:
#     - IfcSweptAreaSolid (and subtypes such as IfcExtrudedAreaSolid, IfcRevolvedAreaSolid, etc.)
#     - IfcSweptDiskSolid (and polygonal variant)
#
#   The script walks the product’s shape representations (prioritizing "Body"),
#   follows mapped geometry (IfcMappedItem → MappingSource → MappedRepresentation),
#   and summarizes sweep parameters, profile parameters (for area sweeps), and
#   placement ("Position") resolved according to the IFC spec fallback rules.
#
#   Output is a human-readable TXT plus an optional JSON “mirror” with the same content.
#
# POSITION RESOLUTION (spec-aligned)
#   For IfcSweptAreaSolid family:
#     1) Use solid.Position (IfcAxis2Placement3D) if present.
#     2) Else use solid.SweptArea.Position (IfcAxis2Placement2D) lifted to 3D.
#     3) Else if curve-guided (IfcSurfaceCurveSweptAreaSolid): build a simple frame from Directrix.
#     4) Else default to representation identity frame.
#   For IfcSweptDiskSolid family:
#     1) Use solid.Position (if exporter provided).
#     2) Else build a simple frame from Directrix.
#     3) Else default to identity.
#
# NOTES
#   - We do not compute global coordinates here. Reported placements are within the
#     representation’s local coordinate system (i.e., before ObjectPlacement aggregation).
#   - “PositionSource” is included so you can see which fallback was used.
#   - Curve summaries are intentionally light-weight: we only capture enough to validate inputs.

import ifcopenshell
import json
from datetime import datetime
from pathlib import Path
import math

# ===================== USER SETTINGS =====================
# Absolute/relative path to your IFC file.
IFC_FILE      = r"C:\Users\devan\OneDrive\Desktop\Devansh Artwani\2025 Summer Term (Co-op)\LGS files\beam-varying-cardinal-points.ifc"

# The IfcProduct occurrence to inspect, by GlobalId (GUID string).
ELEMENT_GUID  = "39IDqhhC14BxCj_Ryk$esj"

# Directory where TXT and JSON reports will be written (filenames are auto-generated).
OUT_DIR       = r"C:\Users\devan\OneDrive\Desktop\Devansh Artwani\2025 Summer Term (Co-op)\LGS files"

# Also write a machine-readable JSON mirror of the TXT report.
WRITE_JSON    = True

# Optional verbosity knobs for curve-heavy profiles/directrices.
INCLUDE_POINTS     = True     # If True, include polyline point coordinates where available.
MAX_POINTS_TO_SHOW = 200      # Truncate very long point lists in TXT for readability.
# =========================================================


# ---------- small utilities ----------
def safe(o, name, default=None):
    """
    Robust attribute getter.
    IFC entities differ across schema versions/tools; some attributes may be absent.
    This avoids AttributeError and returns `default` instead.
    """
    try:
        return getattr(o, name)
    except Exception:
        return default

def is_a(o, *kinds):
    """Convenience: True if object `o` is an instance of ANY of the IFC types listed in `kinds`."""
    return o and any(o.is_a(t) for t in kinds)

def vec(o):
    """
    Normalize IFC directions/points:
      - IfcCartesianPoint.Coordinates  -> [x, y, z?]
      - IfcDirection.DirectionRatios   -> [dx, dy, dz?]
    Returns a Python list[float] or None.
    """
    if not o:
        return None
    return list(getattr(o, "Coordinates", None) or getattr(o, "DirectionRatios", None) or [])

def pt(o):
    """
    Convert an IFC point/direction into a tuple (stable for display/JSON keys).
    Returns None if `o` has neither Coordinates nor DirectionRatios.
    """
    v = vec(o)
    return tuple(v) if v is not None else None


# ---------- placement helpers ----------
def axis3_to_dict(ax3):
    """
    IfcAxis2Placement3D → canonical dict.
    Keys mirror schema terminology so it’s easy to compare with IFC docs:
      - 'Location'     : (x,y,z) origin of the local 3D frame
      - 'Axis'         : local Z (IfcDirection), optional → None if omitted in STEP
      - 'RefDirection' : local X (IfcDirection), optional → None if omitted in STEP
    """
    if not ax3:
        return {}
    return {
        "Location": pt(safe(ax3, "Location")),
        "Axis": vec(safe(ax3, "Axis")),
        "RefDirection": vec(safe(ax3, "RefDirection")),
    }

def axis2_to_dict(ax2):
    """
    IfcAxis2Placement2D → canonical dict.
    We keep 2D fields distinct and convert later when we “lift” to a 3D plane.
    """
    if not ax2:
        return {}
    loc2d = safe(ax2, "Location")
    ref2d = safe(ax2, "RefDirection")
    return {
        "Location2D": tuple((getattr(loc2d, "Coordinates", [0,0]) or [0,0])[:2]) if loc2d else None,
        "RefDirection2D": list((getattr(ref2d, "DirectionRatios", [1,0]) or [1,0])[:2]) if ref2d else None,
    }

def axis2d_to_3d(ax2_dict):
    """
    Lift a 2D profile placement into a 3D plane used by swept area solids.
    - 2D origin → (x, y, 0)
    - Plane normal (Axis) → +Z
    - RefDirection → (rx, ry, 0)
    """
    if not ax2_dict:
        return {}
    x, y = ax2_dict.get("Location2D") or (0.0, 0.0)
    rx, ry = (ax2_dict.get("RefDirection2D") or [1.0, 0.0])[:2]
    return {
        "Location": (float(x), float(y), 0.0),
        "Axis": [0.0, 0.0, 1.0],
        "RefDirection": [float(rx), float(ry), 0.0],
    }

def identity_axis3():
    """
    Identity placement within the representation coordinate system.
    Useful final fallback when neither solid.Position nor profile/directrix frames are given.
    """
    return {"Location": (0.0,0.0,0.0), "Axis": [0.0,0.0,1.0], "RefDirection": [1.0,0.0,0.0]}

def directrix_frame3d(solid):
    """
    Build a simple local 3D frame from the start of a directrix.
    This is sufficient for reporting context (not a full Frenet frame computation):
      - IfcPolyline: use start point and first segment tangent. Normal = +Z unless collinear with +Z.
      - IfcTrimmedCurve with IfcLine: use line's location/direction; Normal = +Z.
    Returns {'Location','Axis','RefDirection'} or {} if not derivable.
    """
    directrix = safe(solid, "Directrix")
    if not directrix:
        return {}

    if directrix.is_a("IfcPolyline"):
        pts = safe(directrix, "Points") or []
        if len(pts) >= 2:
            p0, p1 = pt(pts[0]), pt(pts[1])
            if p0 and p1:
                tx, ty, tz = p1[0]-p0[0], p1[1]-p0[1], (p1[2]-p0[2] if len(p1)>2 else 0.0)
                L = math.sqrt(tx*tx + ty*ty + tz*tz) or 1.0
                t = [tx/L, ty/L, tz/L]             # unit tangent (sweep direction along the path)
                n = [0.0, 0.0, 1.0]               # choose a stable normal
                # If tangent is already +Z, pick a different normal to avoid degeneracy
                if abs(t[0])<1e-9 and abs(t[1])<1e-9 and abs(t[2]-1.0)<1e-9:
                    n = [1.0, 0.0, 0.0]
                # RefDirection := n × t (right-handed frame)
                x = [ n[1]*t[2]-n[2]*t[1], n[2]*t[0]-n[0]*t[2], n[0]*t[1]-n[1]*t[0] ]
                return {"Location": p0, "Axis": n, "RefDirection": x}

    if directrix.is_a("IfcTrimmedCurve"):
        basis = safe(directrix, "BasisCurve")
        if basis and basis.is_a("IfcLine"):
            pnt = pt(safe(basis, "Pnt"))
            dir3 = vec(safe(basis, "Dir"))   # direction ratios of the line
            if pnt and dir3:
                return {"Location": pnt, "Axis": [0.0,0.0,1.0], "RefDirection": dir3}

    return {}


# ---------- Position resolvers ----------
def resolve_profile_plane(solid):
    """
    Apply IFC fallback for IfcSweptAreaSolid family:
      1) solid.Position (IfcAxis2Placement3D)
      2) solid.SweptArea.Position (IfcAxis2Placement2D) → lift to 3D
      3) curve-guided (IfcSurfaceCurveSweptAreaSolid) → frame from Directrix
      4) identity (representation CS)
    Returns: (axis3_dict, source_label)
    """
    pos3 = safe(solid, "Position")
    if pos3:
        return axis3_to_dict(pos3), "Solid.Position"

    prof = safe(solid, "SweptArea")
    if prof:
        pos2 = safe(prof, "Position")
        if pos2:
            return axis2d_to_3d(axis2_to_dict(pos2)), "SweptArea.Position"

    if solid.is_a("IfcSurfaceCurveSweptAreaSolid"):
        frm = directrix_frame3d(solid)
        if frm:
            return frm, "Directrix"

    return identity_axis3(), "Default"

def resolve_disk_plane(solid):
    """
    Position for IfcSweptDiskSolid family:
      1) solid.Position (if provided by exporter)
      2) Directrix-derived frame
      3) identity
    """
    pos3 = safe(solid, "Position")
    if pos3:
        return axis3_to_dict(pos3), "Solid.Position"

    frm = directrix_frame3d(solid)
    if frm:
        return frm, "Directrix"

    return identity_axis3(), "Default"


# ---------- profile helpers ----------
def profile_common(p):
    """
    Extract common scalar parameters across many IfcProfileDef subtypes.
    We intentionally include both generic fields (Depth/Width/Thickness) and
    section-specific ones (OverallDepth, FlangeThickness, etc.) so this works for
    I/C/U/L shapes and more arbitrary parametric families.
    """
    keys = [
        "ProfileType","ProfileName",
        "OverallDepth","OverallWidth","Depth","Height","Width","Thickness",
        "WebThickness","FlangeThickness","BottomFlangeWidth","TopFlangeWidth",
        "FilletRadius","InnerFilletRadius","OuterFilletRadius","EdgeRadius","ToeRadius",
        "Radius","MajorDiameter","MinorDiameter",
        "LipLength","Girth","RidgeHeight","RidgeWidth",
        "LegSlope","Slope",
        "CentreOfGravityInX","CentreOfGravityInY"
    ]
    out = {"Class": p.is_a()}
    for k in keys:
        v = safe(p, k)
        if v is not None:
            out[k] = float(v) if isinstance(v,(int,float)) else v
    return out

def curve_summary(curve):
    """
    Light description of a curve used in profiles or as a directrix.
    For polylines we include points (truncated). For trimmed curves we report the basis.
    """
    if not curve:
        return {"Class": None}
    c = {"Class": curve.is_a()}
    if curve.is_a("IfcPolyline"):
        pts = safe(curve, "Points") or []
        c["PointCount"] = len(pts)
        if INCLUDE_POINTS:
            arr = [pt(x) for x in pts]
            if MAX_POINTS_TO_SHOW and len(arr) > MAX_POINTS_TO_SHOW:
                c["Points"] = arr[:MAX_POINTS_TO_SHOW] + [("…", f"{len(arr)-MAX_POINTS_TO_SHOW} more")]
            else:
                c["Points"] = arr
    elif curve.is_a("IfcTrimmedCurve"):
        basis = safe(curve, "BasisCurve")
        c["Basis"] = basis.is_a() if basis else None
    return c

def profile_info(p):
    """
    Summarize an IfcProfileDef:
      - Flat scalar properties (profile_common)
      - Composite / arbitrary profile composition
      - Outer curve / void counts for freeform profiles
    """
    if not p:
        return {"Class": None}
    info = profile_common(p)
    if p.is_a("IfcCompositeProfileDef"):
        children = safe(p, "Profiles") or []
        info["CompositeCount"] = len(children)
        info["Children"] = [profile_common(ch) for ch in children]
    elif p.is_a("IfcArbitraryClosedProfileDef"):
        info["OuterCurve"] = curve_summary(safe(p, "OuterCurve"))
    elif p.is_a("IfcArbitraryProfileDefWithVoids"):
        info["OuterCurve"] = curve_summary(safe(p, "OuterCurve"))
        voids = safe(p, "InnerCurves") or []
        info["VoidCount"] = len(voids)
    return info


# ---------- summarizers ----------
def summarize_swept_area_solid(s):
    """
    Produce a dictionary for an IfcSweptAreaSolid instance:
      - Position (with source label)
      - Sweep parameters (extrude, revolve, etc.)
      - Profile parameters (IfCProfileDef)
    """
    pos, pos_src = resolve_profile_plane(s)
    d = {"Class": s.is_a(), "Position": pos, "PositionSource": pos_src, "Profile": profile_info(safe(s, "SweptArea"))}

    if s.is_a("IfcExtrudedAreaSolid"):
        d["Sweep"] = {
            "Kind": "Extrude",
            "Direction": {"Dir": vec(safe(s, "ExtrudedDirection"))},
            "Depth": float(s.Depth) if safe(s,"Depth") is not None else None
        }
    elif s.is_a("IfcRevolvedAreaSolid"):
        axis = safe(s, "Axis")  # IfcAxis1Placement controls revolve axis (location + direction)
        d["Sweep"] = {
            "Kind": "Revolve",
            "Axis": {"Location": pt(safe(axis,"Location")), "Direction": vec(safe(axis,"Axis"))} if axis else None,
            "Angle": float(safe(s,"Angle")) if safe(s,"Angle") is not None else None
        }
    elif s.is_a("IfcSurfaceCurveSweptAreaSolid"):
        # Profile follows a curve on a surface; directrix is essential here.
        d["Sweep"] = {"Kind": "SurfaceCurve", "Directrix": curve_summary(safe(s,"Directrix"))}
    elif s.is_a("IfcFixedReferenceSweptAreaSolid"):
        d["Sweep"] = {"Kind": "FixedReference", "FixedReference": vec(safe(s,"FixedReference"))}
    else:
        d["Sweep"] = {"Kind": "Other"}  # Future-proofing for additional subtypes
    return d

def summarize_swept_disk_solid(s):
    """
    Produce a dictionary for an IfcSweptDiskSolid instance:
      - Position (with source label)
      - Directrix (curve summary)
      - Radii and parameter range
    """
    pos, pos_src = resolve_disk_plane(s)
    return {
        "Class": s.is_a(),
        "Position": pos,
        "PositionSource": pos_src,
        "Directrix": curve_summary(safe(s, "Directrix")),
        "Radius": float(s.Radius) if safe(s,"Radius") is not None else None,
        "InnerRadius": float(s.InnerRadius) if safe(s,"InnerRadius") is not None else None,
        "FilletRadius": float(s.FilletRadius) if safe(s,"FilletRadius") is not None else None,
        "StartParam": float(s.StartParam) if safe(s,"StartParam") is not None else None,
        "EndParam": float(s.EndParam) if safe(s,"EndParam") is not None else None,
    }


# ---------- formatting ----------
def pad(s, n): 
    """Fixed-width label alignment for pretty TXT output."""
    return (s + " " * n)[:n]

def fmt_profile(info, lines, indent="    "):
    """Append a formatted profile summary to `lines`."""
    lines.append(indent + f"Profile: {info.get('Class')}")
    keys = [k for k in info.keys() if k not in ("Class","Children","CompositeCount","OuterCurve","VoidCount")]
    for k in sorted(keys):
        lines.append(indent + f"  {pad(k+':', 20)} {info[k]}")
    if info.get("CompositeCount"):
        lines.append(indent + f"  CompositeCount: {info['CompositeCount']}")
    if info.get("OuterCurve"):
        lines.append(indent + f"  OuterCurve: {info['OuterCurve']}")
    if info.get("Children"):
        lines.append(indent + f"  Children:")
        for ch in info["Children"]:
            lines.append(indent + "    - " + ch.get("Class","?"))
    return lines

def fmt_axis3(ax, src_label=None, indent="    "):
    """
    Pretty-print an Axis2Placement3D-like dict.
    When Position is derived via fallback, we include a “(source: …)” tag.
    """
    if not ax:
        return [indent + "Position: (not provided)"]
    head = f"Position (source: {src_label})" if src_label else "Position"
    return [
        indent + head,
        indent + f"  Location      : {ax.get('Location')}",
        indent + f"  Axis (local Z): {ax.get('Axis')}",
        indent + f"  RefDirection  : {ax.get('RefDirection')}",
    ]


# ---------- traversal ----------
def iter_mapped_representation(rep, visited_ids):
    """
    Yield all items under a shape representation, **following mapping chains**.
    - IfcMappedItem → MappingSource → MappedRepresentation (recurse)
    - Non-mapped geometry items are yielded directly.
    `visited_ids` guards against cycles or repeated subgraphs.
    """
    if not rep:
        return
    for it in rep.Items or []:
        if not it:
            continue
        if it.id() in visited_ids:
            continue
        visited_ids.add(it.id())

        if it.is_a("IfcMappedItem"):
            src = safe(it, "MappingSource")
            mapped = safe(src, "MappedRepresentation")
            if mapped:
                # Recurse into the mapped shape to reach the “actual” geometry items.
                yield from iter_mapped_representation(mapped, visited_ids)
        else:
            # Raw geometry item: swept solid, brep, tessellation, etc.
            yield it

def collect_swept_from_rep(rep):
    """
    Scan one IfcShapeRepresentation (with mapping resolved) and classify items into:
      - area  : IfcSweptAreaSolid family
      - disk  : IfcSweptDiskSolid family
      - skipped: everything else (breps, polylines for Axis, tessellations, etc.)
    """
    area, disk, skipped, visited = [], [], [], set()
    for it in iter_mapped_representation(rep, visited):
        if is_a(it, "IfcSweptAreaSolid","IfcExtrudedAreaSolid","IfcRevolvedAreaSolid",
                   "IfcSurfaceCurveSweptAreaSolid","IfcFixedReferenceSweptAreaSolid"):
            area.append(it)
        elif is_a(it, "IfcSweptDiskSolid","IfcSweptDiskSolidPolygonal"):
            disk.append(it)
        else:
            skipped.append(it)
    return area, disk, skipped


# ---------- main ----------
def main():
    # Open IFC model and resolve the target element by its GlobalId (GUID).
    model = ifcopenshell.open(IFC_FILE)
    elem = model.by_guid(ELEMENT_GUID)
    if not elem:
        print(f"No element with GUID: {ELEMENT_GUID}")
        return

    # Prepare output paths (auto-named using GUID); ensure directory exists.
    out_dir = Path(OUT_DIR); out_dir.mkdir(parents=True, exist_ok=True)
    txt_path  = out_dir / f"swept_from_guid_{ELEMENT_GUID}.txt"
    json_path = out_dir / f"swept_from_guid_{ELEMENT_GUID}.json"

    # Gather this element’s product-level shape representations.
    reps = list(safe(safe(elem, "Representation"), "Representations") or [])

    # TXT header (context for the report)
    header = [
        f"IFC file     : {IFC_FILE}",
        f"Element      : {elem.is_a()}  GUID={safe(elem,'GlobalId','')}  Name='{safe(elem,'Name','')}'",
        f"Generated    : {datetime.utcnow().isoformat()}Z",
        f"Reps found   : {len(reps)}",
        ""
    ]
    lines = []

    # JSON payload skeleton mirrors the TXT content (useful for QA/analytics).
    payload = {
        "ifc_file": IFC_FILE,
        "element": {"guid": safe(elem,"GlobalId",""), "class": elem.is_a(), "name": safe(elem,"Name","")},
        "generated": datetime.utcnow().isoformat()+"Z",
        "representations": []
    }

    # Prioritize Body representations; scan remaining reps afterwards.
    bodies = [r for r in reps if safe(r,"RepresentationIdentifier") == "Body"]
    scan_order = bodies + [r for r in reps if r not in bodies]

    item_idx = 0
    total_found = 0

    for rep in scan_order:
        rep_info = {
            "id": rep.id(),
            "identifier": safe(rep,"RepresentationIdentifier"),
            "type": safe(rep,"RepresentationType"),
            "items": []
        }
        lines.append(f"Rep #{rep.id()}  Identifier='{rep_info['identifier']}'  Type='{rep_info['type']}'")

        # Resolve mapped geometry and classify swept items.
        area_items, disk_items, _skipped = collect_swept_from_rep(rep)
        total_found += len(area_items) + len(disk_items)

        if not area_items and not disk_items:
            lines.append("  (no SweptAreaSolid / SweptDiskSolid found)")

        # --- Report area sweeps (IfcSweptAreaSolid family) ---
        for it in area_items:
            item_idx += 1
            info = summarize_swept_area_solid(it)
            rep_info["items"].append({"kind":"SweptAreaSolid", "id": it.id(), **info})

            lines.append(f"\n== Item {item_idx}: {it.is_a()}  #{it.id()} ==")
            lines.extend(fmt_axis3(info.get("Position"), info.get("PositionSource")))
            lines.append("  Sweep:")
            for k,v in (info.get("Sweep") or {}).items():
                lines.append(f"    {pad(k+':', 14)} {v}")
            fmt_profile(info["Profile"], lines, indent="  ")

        # --- Report disk sweeps (IfcSweptDiskSolid family) ---
        for it in disk_items:
            item_idx += 1
            info = summarize_swept_disk_solid(it)
            rep_info["items"].append({"kind":"SweptDiskSolid", "id": it.id(), **info})

            lines.append(f"\n== Item {item_idx}: {it.is_a()}  #{it.id()} ==")
            lines.extend(fmt_axis3(info.get("Position"), info.get("PositionSource")))
            lines.append(f"  Radius       : {info.get('Radius')}")
            if info.get("InnerRadius") is not None:
                lines.append(f"  InnerRadius  : {info.get('InnerRadius')}")
            if info.get("FilletRadius") is not None:
                lines.append(f"  FilletRadius : {info.get('FilletRadius')}")
            if info.get("StartParam") is not None or info.get("EndParam") is not None:
                lines.append(f"  ParamRange   : {info.get('StartParam')} .. {info.get('EndParam')}")
            lines.append(f"  Directrix    : {info.get('Directrix')}")

        payload["representations"].append(rep_info)
        lines.append("")

    if total_found == 0:
        lines.append("No IfcSweptAreaSolid / IfcSweptDiskSolid were found for this element.")

    # Persist TXT/JSON.
    report = "\n".join(header + lines)
    txt_path.write_text(report, encoding="utf-8")
    print(f"Saved report: {txt_path}")

    if WRITE_JSON:
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Saved JSON  : {json_path}")

if __name__ == "__main__":
    main()
