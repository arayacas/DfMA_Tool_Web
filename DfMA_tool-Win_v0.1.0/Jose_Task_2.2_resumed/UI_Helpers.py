import streamlit as st
import base64
import os

def add_floating_lab_logo(image_path, url="https://rafiqahmads.com/"):
    """Adds a sticky, clickable logo to the bottom right of the screen."""
    
    # Safety check: if the image isn't there, silently skip drawing it
    if not os.path.exists(image_path):
        return 

    try:
        # Convert the image to base64 so HTML can render it directly
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode()
        
        # Inject the CSS and HTML
        st.markdown(
            f"""
            <style>
            .floating-logo {{
                position: fixed;
                bottom: 30px;
                right: 30px;
                z-index: 9999;
                width: 350px; /* Adjust this to make the logo bigger/smaller */
                opacity: 0.6; /* Slight transparency so it doesn't block data */
                transition: opacity 0.3s ease-in-out;
            }}
            .floating-logo:hover {{
                opacity: 1.0; /* Lights up to 100% visibility when hovered */
            }}
            </style>
            <a href="{url}" target="_blank">
                <img src="data:image/png;base64,{encoded_string}" class="floating-logo">
            </a>
            """,
            unsafe_allow_html=True
        )
    except Exception as e:
        pass