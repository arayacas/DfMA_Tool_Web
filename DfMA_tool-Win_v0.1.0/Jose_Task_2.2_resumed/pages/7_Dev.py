import streamlit as st

# -----------------------------------------
# 1. THE DEBUG TOGGLE
# Place this at the top of your sidebar
# -----------------------------------------
st.sidebar.markdown("---")
DEBUG_MODE = st.sidebar.toggle("🛠️ Developer Mode")

# -----------------------------------------
# 2. THE VISUAL DEBUGGER
# -----------------------------------------
if DEBUG_MODE:
    st.sidebar.markdown("### 🧠 App Brain (Session State)")
    
    # We create a 'safe' dictionary to display.
    # If we try to render a massive PyVista mesh as text, the app will crash.
    safe_state = {}
    for key, value in st.session_state.items():
        # Add any variable names here that hold massive data (like your IFC graph)
        if "mesh" in key.lower() or "graph" in key.lower() or "ifc" in key.lower():
            safe_state[key] = f"[Heavy Object: {type(value).__name__}]"
        else:
            safe_state[key] = value
            
    # Dump the safe state to the screen
    st.sidebar.json(safe_state)
    
    # Optional: You can also use this toggle to show hidden error messages in your main app
    # Example:
    # if error_occurred and DEBUG_MODE:
    #     st.error(f"Detailed trace: {actual_error}")