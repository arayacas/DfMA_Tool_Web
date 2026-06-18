# mapped_min_check.py
import ifcopenshell

# 🔧 Set these two:
IFC_FILE = r"C:/Users/devan/OneDrive/Desktop/Devansh Artwani/2025 Summer Term (Co-op)/LGS files/LGS_wall.ifc"
GUID     = "0Mxc9hiKT5IhDB2THdcnh$"

def safe(obj, attr, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default

def vec(obj):
    if not obj:
        return None
    return list(getattr(obj, "Coordinates", None) or getattr(obj, "DirectionRatios", None) or [])

def axis3_info(ax):
    if not ax:
        return {}
    return {
        "Origin": vec(safe(ax, "Location")),
        "XDir":   vec(safe(ax, "RefDirection")),
        "Axis":   vec(safe(ax, "Axis")),
    }

def transform_info(op):
    if not op:
        return {}
    return {
        "Type": op.is_a(),
        "Scale": safe(op, "Scale", 1.0),
        "LocalOrigin": vec(safe(op, "LocalOrigin")),
        "Axis1": vec(safe(op, "Axis1")),
        "Axis2": vec(safe(op, "Axis2")),
        "Axis3": vec(safe(op, "Axis3")),
    }

# --- richer hints for common non-parametric items (BReps/Curves) -------------
def profile_summary(p):
    if not p:
        return None
    t = p.is_a()
    d = {"Profile": t}
    for k in ("XDim","YDim","Radius","Depth","FlangeWidth","WebThickness","LipDepth",
              "Thickness","FilletRadius"):
        if hasattr(p, k):
            d[k] = getattr(p, k)
    return d

def brep_hint(brep):
    """Basic stats for IfcFacetedBrep / IfcAdvancedBrep."""
    h = {"Item": brep.is_a()}
    closed_shell = safe(brep, "Outer") or safe(brep, "OuterShell")
    # AdvancedBrep uses Outer; FacetedBrep uses Outer as well (IfcClosedShell)
    if closed_shell and hasattr(closed_shell, "CfsFaces"):
        faces = closed_shell.CfsFaces or []
        h["FaceCount"] = len(faces)
    # If there are inner shells (rare)
    inner = safe(brep, "Inner") or safe(brep, "InnerShells")
    if inner:
        h["InnerShellCount"] = len(inner)
    return h

def curve_hint(curve):
    """Details for IfcTrimmedCurve and common basis curves."""
    t = curve.is_a()
    if t == "IfcTrimmedCurve":
        basis = safe(curve, "BasisCurve")
        trims1 = safe(curve, "Trim1") or []
        trims2 = safe(curve, "Trim2") or []
        def trim_desc(tlist):
            out = []
            for tr in tlist:
                # a trim can be parameter value (IfcParameterValue) or a point (IfcCartesianPoint)
                if hasattr(tr, "wrappedValue"):   # parameter value
                    out.append(("Param", tr.wrappedValue))
                elif hasattr(tr, "Coordinates"):   # point
                    out.append(("Point", list(tr.Coordinates)))
                else:
                    out.append(("Other", str(tr)))
            return out
        return {
            "Item": t,
            "SenseAgreement": safe(curve, "SenseAgreement"),
            "MasterRepresentation": str(safe(curve, "MasterRepresentation")),
            "BasisCurve": basis.is_a() if basis else None,
            "Trim1": trim_desc(trims1),
            "Trim2": trim_desc(trims2),
        }
    # Plain curves
    if t == "IfcPolyline":
        pts = curve.Points or []
        return {"Item": t, "PointCount": len(pts)}
    if t == "IfcCircle":
        return {"Item": t, "Radius": safe(curve, "Radius")}
    if t == "IfcLine":
        return {"Item": t, "Dir": vec(safe(curve, "Dir"))}
    # Fallback
    return {"Item": t}

def item_hint(it):
    """Combined hint handler for solids, breps, tessellations & curves."""
    t = it.is_a()
    if t in ("IfcFacetedBrep","IfcAdvancedBrep"):
        return brep_hint(it)
    if t in ("IfcTriangulatedFaceSet","IfcPolygonalFaceSet"):
        return {"Item": t, "HasNormals": bool(safe(it, "Normals"))}
    if t == "IfcExtrudedAreaSolid":
        return {
            "Item": t,
            "Depth": safe(it, "Depth"),
            "ExtrudedDirection": vec(safe(it, "ExtrudedDirection")),
            "Profile": profile_summary(safe(it, "SweptArea")),
        }
    if t in ("IfcRevolvedAreaSolid","IfcSweptDiskSolid","IfcSurfaceCurveSweptAreaSolid"):
        return {"Item": t, "Profile": profile_summary(safe(it, "SweptArea"))}
    # Curves (often seen in Axis reps)
    if t.startswith("Ifc"):  # includes IfcTrimmedCurve etc.
        # Try known curve types
        try:
            return curve_hint(it)
        except Exception:
            pass
    return {"Item": t}
# -----------------------------------------------------------------------------

def mappedIdentifier():
    model = ifcopenshell.open(IFC_FILE)
    elem = model.by_guid(GUID)
    if not elem:
        print(f"❌ No element with GUID: {GUID}")
        return
    if not elem.Representation:
        print(f"ℹ️  {elem.is_a()}({GUID}) has no product-level Representation.")
        return

    found = False
    print(f"=== {elem.is_a()}  GUID={elem.GlobalId}  Name={safe(elem,'Name','')} ===\n")
    for rep in elem.Representation.Representations or []:
        mapped_items = [it for it in (rep.Items or []) if it.is_a("IfcMappedItem")]
        if not mapped_items:
            continue

        found = True
        print(f"- ShapeRepresentation: Identifier='{safe(rep,'RepresentationIdentifier')}', "
              f"Type='{safe(rep,'RepresentationType')}'")
        for mi in mapped_items:
            src_map = safe(mi, "MappingSource")
            mapped_rep = safe(src_map, "MappedRepresentation")
            inner_items = safe(mapped_rep, "Items") or []
            item_classes = [it.is_a() for it in inner_items]

            print("    • IfcMappedItem")
            print(f"        Source RepMap id  : #{src_map.id() if src_map else 'None'}")
            print(f"        Mapped Identifier : {safe(mapped_rep,'RepresentationIdentifier')}")
            print(f"        Mapped Type       : {safe(mapped_rep,'RepresentationType')}")
            print(f"        Mapped Items      : {item_classes}")

            # Instance transform + map origin
            mapping_target = safe(mi, "MappingTarget")
            print(f"        MappingTarget     : {transform_info(mapping_target)}")
            print(f"        Map.MappingOrigin : {axis3_info(safe(src_map,'MappingOrigin'))}")

            # 🔎 NEW: richer, type-specific hints for each mapped item
            for inner in inner_items:
                hint = item_hint(inner)
                if hint:
                    print(f"        -> {hint}")

            owners = safe(src_map, "OfProductRepresentation") or []
            if owners:
                for owner in owners:
                    tp = owner[0] if owner and len(owner) > 0 else None
                    if tp:
                        print(f"        From Type        : {tp.is_a()}  Name='{safe(tp,'Name','')}'  GUID={safe(tp,'GlobalId','')}")

        print()

    if not found:
        print("ℹ️  No IfcMappedItem found in this element's product-level representations.")

if __name__ == '__main__':
    mappedIdentifier()
