# DfMA Tool Readme Manual:

Welcome to the DfMA tool user and development manual!

This readme file is meant to guide you on how the tool works, how to make new additions/features and explain what and how the tool analyzes LGS steel panels.

## Table of Contents

1. [Getting started (dev)](#getting-started-(dev))
    -[Developer installation Guide](#dev-installation-guide)
2. [Getting started (user)](#getting-started-(user))
    -[User installation Guide](#user-installation-guide)
3. [How to add a new DfMA rule](#adding-a-DfMA-Rule)
    -[How to modify the design parameters](#modifying-design-parameters)

## Getting Started (dev)

Welcome to the Developer Guide for the SMART Lab DfMA (Design for Manufacturing and Assembly) Tool. This app uses Streamlit for the frontend UI, ifcopenshell for BIM parsing, and PyVista for 3D visualization and a bunch of additional libraries to run.

**IMPORTANT:** This software was developed on Linux (Ubuntu Distro). It is highly recommended to modify it using Linux if possible. However, the tool is also modifiable in Windows. 

For Linux users the DfMA Tool uses:
- Trame = 3.13.2

For Windows Users the DfMA Tool uses:

- Panel >= 1.4.1

### Prerequisites (dependencies):

- Streamlit
- Python 3
- ifcopenshell==0.8.5
- numpy==2.4.6
- pandas==3.0.3
- pillow==12.2.0
- pyvista==0.48.4
- stpyvista==0.2.1
- streamlit==1.57.0
- trame==3.13.2
- trame-client==3.12.2
- trame-common==1.2.3
- trame-server==3.12.4
- trame-vtk==2.11.8
- trame-vuetify==3.2.2
- vtk==9.6.2
- panel>=1.4.1
- nest_asyncio2
- redflib==7.0.0

### The Requirements.txt and the packages.txt file:

Both of these files are necessary for the Streamlit web version to run and requirements.txt is necessary for users to install of those Prerequisites dependencies on their computers.

**Requirements.txt**

```
ifcopenshell==0.8.5
numpy==2.4.6
pandas==3.0.3
pillow==12.2.0
pyvista==0.48.4
stpyvista==0.2.1
streamlit==1.57.0
trame==3.13.2
trame-client==3.12.2
trame-common==1.2.3
trame-server==3.12.4
trame-vtk==2.11.8
trame-vuetify==3.2.2
vtk==9.6.2
panel>=1.4.1
nest_asyncio2
redflib==7.0.0
```

**Packages.txt **



## Adding a DfMA Rule

Because the app is distributed across multiple pages and utilizes a centralized cloud memory system (st.session_state), a streamlit function to keep session memory of the design parameters used. Adding a new DfMA Rule requires updates in four specific locations.

Follow this 4-step checklist to ensure a new rule is integrated successfully without breaking the app.

Step 1: Initialize the Parameter (Global Memory)
File to Edit: Start.py (or your main entry point)
Purpose: Ensure the variable exists in the cloud before any page tries to read it.

Locate the # --- INITIALIZE WEB-SAFE PARAMETERS --- block.

Add your new constraint's default value to the st.session_state["design_params"] dictionary.

Python
# Example: Adding a new "max_joist_depth" rule
if "design_params" not in st.session_state:
    st.session_state["design_params"] = {
        "max_length": 6.00,
        "max_height": 3.00,
        "max_joist_depth": 200.0, # <-- NEW PARAMETER ADDED HERE
        # ... other parameters ...
    }
Step 2: Build the Control UI (The Sliders)
File to Edit: pages/2_Design_Parameters.py
Purpose: Give the user a way to change the parameter and optionally "pin" it to the main dashboard.

Decide which Tab the rule belongs in (e.g., Dimensional Limits, Tolerances).

Create the Streamlit input widget and bind it directly to the params dictionary.

Call the pin_control() helper function so it can be pushed to the Quick Access dashboard.

Python
# Example: Adding the slider under the Dimensional Limits tab
with col1:
    params["max_joist_depth"] = st.number_input("Max Joist Depth (mm)", value=params["max_joist_depth"], step=5.0)
    pin_control("max_joist_depth") # Enable dashboard pinning
Step 3: Write the Math Engine
File to Edit: Constraints.py
Purpose: The actual geometric or semantic evaluation of the IFC elements.

Write a new function following the standard signature: def check_rulename(elements, constraint1=val):

The function must return a dictionary with exactly three keys:

"passed": Boolean (True/False)

"message": A string explaining the result (include the part count!)

"violating_elements": A list of the specific ifcopenshell elements that failed.

Python
# Example Template
def check_joist_depth(elements, max_depth_mm=200.0):
    violating_elements = []
    
    # 1. Filter elements
    joists = [e for e in elements if "joist" in e.Name.lower()]
    
    # 2. Run the math...
    # (If math fails, add element to violating_elements list)
    
    passed = len(violating_elements) == 0
    return {
        "passed": passed,
        "message": f"Passed all {len(joists)} joists." if passed else "Failed joist depth limits.",
        "violating_elements": violating_elements
    }
Step 4: Wire it into the Display Page
File to Edit: pages/1_DfMA_Display.py
Purpose: Run the engine, paint the bad parts red, and print the text report.

This step requires three separate edits within the 1_DfMA_Display.py file:

A. Add to Quick Access (Optional but recommended):
If the user pins the rule, the app needs to know how to draw it on Page 1. Add an elif to the pinning loop.

Python
elif rule_id == "max_joist_depth":
    params["max_joist_depth"] = st.number_input("Joist Depth", value=params["max_joist_depth"])
B. Run the Rule & Paint the Parts:
Locate the Rules Engine block, run your new function from Step 3, and add the result to the red_parts list.

Python
# 1. Run the engine using the params dictionary
joist_depth_report = Constraints.check_joist_depth(all_elements, max_depth_mm=params["max_joist_depth"])

# 2. Add to the paint bucket
red_parts = (size_rule_report.get("violating_elements", []) 
             + alignedhole_rule_report.get("violating_elements", [])
             + joist_depth_report.get("violating_elements", []) # <-- ADDED HERE
             # ... other rules ...
            )
C. Print the Report UI:
Scroll to the very bottom of the script to the ### DfMA Report section and print the message.

Python
if not joist_depth_report["passed"]: 
    st.error(joist_depth_report["message"])
else: 
    st.success(joist_depth_report["message"])
🎉 Done! You have successfully added a new DfMA feature.

I highly recommend creating a new file in your project folder called README.md and pasting that directly into it. Do you feel like this checklist accurately maps out the architecture we've built?