import ifcopenshell

# ==========================================================
# INPUT / OUTPUT
# ==========================================================


INPUT_IFC = r"C:\@Work\NRC\Arash\IFC\624McRobert.ifc"
OUTPUT_IFC = r"C:\@Work\NRC\Arash\IFC\Research_CaseStudy.ifc"

model = ifcopenshell.open(INPUT_IFC)

# ==========================================================
# Helper
# ==========================================================

def safe_set(entity, attribute, value):
    """Safely set an IFC attribute if it exists."""
    try:
        if hasattr(entity, attribute):
            setattr(entity, attribute, value)
    except Exception:
        pass


# ==========================================================
# Project
# ==========================================================

for project in model.by_type("IfcProject"):

    safe_set(project, "Name", "Research Case Study")
    safe_set(project, "LongName", None)
    safe_set(project, "Description", "Anonymized IFC dataset")


# ==========================================================
# Site
# ==========================================================

for site in model.by_type("IfcSite"):

    safe_set(site, "Name", "Research Site")
    safe_set(site, "LongName", None)
    safe_set(site, "Description", "Anonymized")
    safe_set(site, "LandTitleNumber", None)


# ==========================================================
# Building
# ==========================================================

for building in model.by_type("IfcBuilding"):

    safe_set(building, "Name", "Research Building")
    safe_set(building, "LongName", None)
    safe_set(building, "Description", "Anonymized")


# ==========================================================
# Persons
# ==========================================================

for person in model.by_type("IfcPerson"):

    safe_set(person, "FamilyName", "Research")
    safe_set(person, "GivenName", "User")

    try:
        person.MiddleNames = ()
    except:
        pass

    try:
        person.PrefixTitles = ()
    except:
        pass

    try:
        person.SuffixTitles = ()
    except:
        pass


# ==========================================================
# Organizations
# ==========================================================

for org in model.by_type("IfcOrganization"):

    safe_set(org, "Name", "Research Organization")
    safe_set(org, "Description", "Anonymized")


# ==========================================================
# Postal Addresses
# ==========================================================

for address in model.by_type("IfcPostalAddress"):

    safe_set(address, "InternalLocation", None)
    safe_set(address, "AddressLines", ())
    safe_set(address, "PostalBox", None)
    safe_set(address, "Town", None)
    safe_set(address, "Region", None)
    safe_set(address, "PostalCode", None)
    safe_set(address, "Country", None)


# ==========================================================
# Telecom Addresses
# ==========================================================

for telecom in model.by_type("IfcTelecomAddress"):

    safe_set(telecom, "TelephoneNumbers", ())
    safe_set(telecom, "FacsimileNumbers", ())
    safe_set(telecom, "ElectronicMailAddresses", ())
    safe_set(telecom, "WWWHomePageURL", None)


# ==========================================================
# Application
# ==========================================================

for app in model.by_type("IfcApplication"):

    safe_set(app, "ApplicationFullName", "IFC Research Preparation Tool")
    safe_set(app, "Version", "1.0")


# ==========================================================
# Owner History
# DO NOT REMOVE (mandatory in IFC2X3)
# Since Person and Organization have been anonymized,
# OwnerHistory references are already safe.
# ==========================================================


# ==========================================================
# Save
# ==========================================================

model.write(OUTPUT_IFC)

print("=" * 60)
print("IFC anonymization complete.")
print("Output:")
print(OUTPUT_IFC)
print("=" * 60)