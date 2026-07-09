import streamlit as st
import os
from rdflib import Graph
from streamlit_agraph import agraph, Node, Edge, Config

st.set_page_config(page_title="Ontology Display", layout="wide")
st.title("Semantic Connections & Ontology")
st.write("Interactive Force-Directed Knowledge Graph (Rain World Style)")

# Check if the TTL file was uploaded/saved in the Start.py page
if 'current_ontology_path' in st.session_state and os.path.exists(st.session_state['current_ontology_path']):
    ttl_path = st.session_state['current_ontology_path']
    
    with st.spinner("Loading Ontology Graph..."):
        try:
            # 1. Load the existing TTL file directly into RDFLib
            rdf_graph = Graph()
            rdf_graph.parse(ttl_path, format="turtle")
            
            # 2. Prepare nodes and edges for Agraph
            nodes_dict = {}
            edges = []
            
            # Helper function to clean up raw ontology URIs for display
            def clean_uri(uri):
                return str(uri).split("#")[-1]
            
            # Extract Triples (Subject -> Predicate -> Object)
            for subj, pred, obj in rdf_graph:
                s_id = clean_uri(subj)
                p_label = clean_uri(pred)
                o_id = clean_uri(obj)
                
                # --- PRO TIP: Clean up the "Hairball" ---
                # RDF files contain a lot of hidden background code (like defining that an object is a "NamedIndividual").
                # This skips those boring background nodes so you only see the actual structural parts!
                if p_label == "type" or "NamedIndividual" in o_id or "Class" in o_id:
                    continue 
                
                # Create Subject Node if it doesn't exist
                if s_id not in nodes_dict:
                    # Color coding: Gold for Fasteners, Red for Connections, Blue for Structural Parts
                    color = "#FFD700" if "Fastener" in s_id else ("#FF6347" if "Connection" in s_id else "#87CEFA")
                    size = 15 if "Fastener" in s_id else (20 if "Connection" in s_id else 25)
                    nodes_dict[s_id] = Node(id=s_id, label=s_id, size=size, color=color)
                    
                # Create Object Node if it doesn't exist
                if o_id not in nodes_dict:
                    # If the object is just a number/text property (like "3000mm"), make it a small grey dot
                    is_literal = not str(obj).startswith("http")
                    color = "#D3D3D3" if is_literal else ("#FF6347" if "Connection" in o_id else "#87CEFA")
                    size = 10 if is_literal else 20
                    nodes_dict[o_id] = Node(id=o_id, label=o_id, size=size, color=color)
                    
                # Create the Edge (The "Pipe" connecting the nodes)
                edges.append(Edge(source=s_id, label=p_label, target=o_id))
            
            # Convert dictionary to a flat list for the renderer
            nodes = list(nodes_dict.values())
            
            # 3. Configure the Physics Engine (Dark mode, Rain World vibes)
            config = Config(
                width=1000,
                height=750,
                directed=True,
                physics=True,
                hierarchical=False,
                nodeHighlightBehavior=True,
                highlightColor="#00FF00", # Glow green when clicked
                collapsible=True
            )
            
            # 4. Render the Interactive Graph!
            st.success(f"Ontology Loaded: {len(nodes)} Nodes, {len(edges)} Relationships")
            agraph(nodes=nodes, edges=edges, config=config)

        except Exception as e:
            st.error(f"An error occurred while building the graph: {e}")
            
else:
    st.warning("⚠️ No .ttl file detected in memory. Please go to the Start page and upload your Ontology file.")