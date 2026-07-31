import streamlit as st
import os
import sys
from PIL import Image
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL
from streamlit_echarts import st_echarts

# --- DYNAMIC PATH RESOLUTION (FOR NESTED PAGES) ---
# 1. Get the absolute path to the 'pages' folder
current_dir = os.path.dirname(os.path.abspath(__file__))

# 2. Go up TWO levels:
#    First ".." escapes the 'pages' folder.
#    Second ".." escapes 'Jose_Task_2.2_resumed' into 'DfMA_tool-Win_v0.1.0'
#    Then enter the 'Images' folder.
images_dir = os.path.join(current_dir, "..", "..", "Images")

# 3. Path hack to allow importing UI_Helpers from the parent directory
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import UI_Helpers

# --- PAGE SETUP ---
logo_path = os.path.join(images_dir, "smart_logo.jpeg")
try:
    logo_img = Image.open(logo_path)
except Exception:
    logo_img = None

# Side bar format (external to Streamlit)
st.markdown(
    """
    <style>
    /* Target the sidebar navigation menu items */
    [data-testid="stSidebarNav"] span {
        font-size: 30px !important; 
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.set_page_config(
    layout="wide",
    page_title="Ontology Display",
    page_icon=logo_img
)

lablogo_path = os.path.join(images_dir, "horizontal_smart.png")
try:
    UI_Helpers.add_floating_lab_logo(lablogo_path, url="https://rafiqahmads.com/")
except Exception:
    pass

st.title("Ontology Display")

# --- HELPER FUNCTION: EXTRACT LABELS ---
def get_label(g, node):
    """Try to find the rdfs:label; fallback to the URI ending."""
    if isinstance(node, URIRef):
        for label in g.objects(node, RDFS.label):
            return str(label)
        return node.split('#')[-1] if '#' in node else node.split('/')[-1]
    return "Unknown"

# --- ENGINE 1: CLASS TREE ---
def build_class_tree(g):
    classes = set(s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef))
    children_map = {}
    top_level_classes = set(classes)
    
    for cls in classes:
        for super_cls in g.objects(cls, RDFS.subClassOf):
            if isinstance(super_cls, URIRef):
                if super_cls not in children_map:
                    children_map[super_cls] = []
                children_map[super_cls].append(cls)
                if cls in top_level_classes:
                    top_level_classes.remove(cls)
                    
    def build_node(node):
        node_name = get_label(g, node)
        children = children_map.get(node, [])
        if not children:
            return {"name": node_name, "value": 1}
        return {"name": node_name, "children": [build_node(child) for child in children]}
        
    return {
        "name": "BIM Classes (Root)",
        "children": [build_node(top_node) for top_node in top_level_classes]
    }

# --- ENGINE 2: PROPERTY TREE ---
def build_property_tree(g):
    prop_types = {
        OWL.ObjectProperty: "Object Properties",
        OWL.DatatypeProperty: "Data Properties",
        OWL.AnnotationProperty: "Annotation Properties"
    }
    
    root_children = []
    
    for p_type, p_name in prop_types.items():
        props = set(g.subjects(RDF.type, p_type))
        children_map = {}
        top_level_props = set(props)
        
        for prop in props:
            for super_prop in g.objects(prop, RDFS.subPropertyOf):
                if isinstance(super_prop, URIRef) and super_prop in props:
                    if super_prop not in children_map:
                        children_map[super_prop] = []
                    children_map[super_prop].append(prop)
                    if prop in top_level_props:
                        top_level_props.remove(prop)
                        
        def build_node(node):
            node_name = get_label(g, node)
            children = children_map.get(node, [])
            if not children:
                return {"name": node_name, "value": 1}
            return {"name": node_name, "children": [build_node(child) for child in children]}
            
        type_children = [build_node(p) for p in top_level_props]
        
        if type_children:
            root_children.append({"name": p_name, "children": type_children})
            
    return {"name": "Ontology Properties", "children": root_children}

# --- ENGINE 3: INDIVIDUALS TREE (UPGRADED WITH DATA DIGGER) ---
def build_individual_tree(g):
    classes = set(s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef))
    root_children = []
    added_individuals = set() 
    
    # Recursive function to extract data/object properties from individuals
    def get_individual_properties(subject, depth=0, max_depth=2, seen=None):
        if seen is None:
            seen = set()
        # Prevent infinite loops in cyclical graphs
        if depth >= max_depth or subject in seen:
            return []
            
        seen.add(subject)
        prop_nodes = []
        
        for p, o in g.predicate_objects(subject=subject):
            # Skip the rdf:type declaration since the tree hierarchy already shows it
            if p == RDF.type:
                continue
                
            prop_name = get_label(g, p)
            
            if isinstance(o, Literal):
                # It's a raw value (e.g., hasLength: 0.1)
                val = str(o.value) if o.value is not None else str(o)
                prop_nodes.append({"name": f"{prop_name}: {val}", "value": 1})
                
            elif isinstance(o, URIRef):
                # It links to another Individual (e.g., hasGeometricInfo -> GeoInfo_1)
                obj_name = get_label(g, o)
                sub_props = get_individual_properties(o, depth + 1, max_depth, seen.copy())
                
                if sub_props:
                    prop_nodes.append({
                        "name": f"{prop_name} -> {obj_name}",
                        "children": sub_props
                    })
                else:
                    prop_nodes.append({"name": f"{prop_name} -> {obj_name}", "value": 1})
                    
        return prop_nodes

    for cls in classes:
        instances = list(g.subjects(RDF.type, cls))
        valid_instances = [inst for inst in instances if isinstance(inst, URIRef)]
        
        if valid_instances:
            class_name = get_label(g, cls)
            instance_nodes = []
            
            for inst in valid_instances:
                if inst not in added_individuals:
                    added_individuals.add(inst)
                    inst_name = get_label(g, inst)
                    
                    # Fetch the data inside this specific individual!
                    ind_props = get_individual_properties(inst)
                    
                    if ind_props:
                        instance_nodes.append({
                            "name": inst_name,
                            "children": ind_props
                        })
                    else:
                        instance_nodes.append({"name": inst_name, "value": 1})
            
            if instance_nodes:
                root_children.append({
                    "name": f"Instances of: {class_name}",
                    "children": instance_nodes
                })
                
    if not root_children:
         return {"name": "Ontology Individuals (Empty - Waiting for DfMA Data)", "children": []}
        
    return {
        "name": "Ontology Individuals (Root)",
        "children": root_children
    }

# --- PAGE LOGIC & UI LAYOUT ---
if 'current_ontology_path' in st.session_state and os.path.exists(st.session_state['current_ontology_path']):
    ttl_path = st.session_state['current_ontology_path']
    st.success(f"Loaded Ontology: {os.path.basename(ttl_path)}")
    
    g = Graph()
    try:
        g.parse(ttl_path, format="turtle")
        
        # 1. Add a Sidebar Control for Dynamic Stretching
        st.sidebar.markdown("### Graph Settings")
        graph_height = st.sidebar.slider("Vertical Canvas Size (px)", min_value=400, max_value=3000, value=800, step=100)
        st.sidebar.info("Increase this value to add more vertical breathing room between nodes.")

        # 2. ECharts Universal Configuration (Animations Restored)
        def get_echarts_options(data):
            return {
                "tooltip": {"trigger": "item", "triggerOn": "mousemove"},
                "animation": True, # <--- RESTORED: Let ECharts handle the fade-out
                "series": [
                    {
                        "type": "tree",
                        "data": [data],
                        "top": "2%", "left": "10%", "bottom": "2%", "right": "20%",
                        "symbolSize": 10, 
                        "initialTreeDepth": 1,
                        "roam": True, 
                        "label": {
                            "position": "left", 
                            "verticalAlign": "middle", 
                            "align": "right", 
                            "fontSize": 13 
                        },
                        "leaves": {
                            "label": {
                                "position": "right", 
                                "verticalAlign": "middle", 
                                "align": "left"
                            }
                        },
                        "expandAndCollapse": True,
                        "animationDuration": 500,       # <--- RESTORED: Smooth opening
                        "animationDurationUpdate": 500, # <--- RESTORED: Smooth collapsing
                    }
                ],
            }

        # 3. Create Streamlit Tabs for clean organization
        tab1, tab2, tab3 = st.tabs(["Classes", "Properties", "Individuals (Instances)"])
        
        with tab1:
            st.markdown("### Ontology Classes")
            st.markdown("Explore the structural blueprint of your assembly.")
            st_echarts(get_echarts_options(build_class_tree(g)), height=f"{graph_height}px", key="class_tree", renderer="svg")
            
        with tab2:
            st.markdown("### Ontology Properties")
            st.markdown("Explore the relationships and data attributes connecting the components.")
            st_echarts(get_echarts_options(build_property_tree(g)), height=f"{graph_height}px", key="prop_tree", renderer="svg")

        with tab3:
            st.markdown("### Ontology Individuals")
            st.markdown("Explore the physical items and generated connections currently stored in the file.")
            st_echarts(get_echarts_options(build_individual_tree(g)), height=f"{graph_height}px", key="ind_tree", renderer="svg")

    except Exception as e:
        st.error(f"Error parsing the ontology file: {e}")
        
else:
    st.warning("No .ttl file detected in memory. Please go to the Start page and upload your Ontology file.")