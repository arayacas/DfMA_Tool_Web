import ifcopenshell
from collections import Counter

ifc = ifcopenshell.open(r"LGS_wall.ifc")

# Count every instance by its IFC class name
counts = Counter(instance.is_a() for instance in ifc)

# Print each type along with its count, sorted alphabetically
for entity_type in sorted(counts):
    print(f"{entity_type}: {counts[entity_type]}")
