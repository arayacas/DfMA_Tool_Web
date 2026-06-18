# list_ifc_elements_simple.py
import ifcopenshell
from collections import Counter
from pathlib import Path

# ✅ Use ONE of these safe forms:
# IFC_FILE = r"{file path}"
# IFC_FILE = "{file path}"
IFC_FILE = r"C:\Users\devan\OneDrive\Desktop\Devansh Artwani\2025 Summer Term (Co-op)\LGS files\beam-varying-cardinal-points.ifc"

def safe_get(obj, attr, default=""):
    try:
        return getattr(obj, attr)
    except Exception:
        return default

def main():
    p = Path(IFC_FILE)
    if not p.is_file():
        raise SystemExit(f"IFC file not found: {p}")

    model = ifcopenshell.open(p)

    elements = model.by_type("IfcElement")

    # Summary by class
    class_counts = Counter(e.is_a() for e in elements)
    print("\n=== IfcElement class summary ===")
    for cls, cnt in sorted(class_counts.items()):
        print(f"{cls:30s}  {cnt}")

    # Detailed list
    print("\n=== Detailed list (Class, GlobalId, Name) ===")
    for e in elements:
        print(f"{e.is_a():30s}  {safe_get(e, 'GlobalId'):22s}  {safe_get(e, 'Name')}")

if __name__ == "__main__":
    main()
