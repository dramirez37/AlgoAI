import os
import rdflib
import csv
import logging
import uuid
import json
import re
from rdflib.namespace import RDF, RDFS, SKOS
from rdflib.collection import Collection

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

FIBO_DIR = "/workspaces/AlgoAI/graphdb/fibo"  # Raw RDF files
PREPROCESS_DIR = "/workspaces/AlgoAI/graphdb/preprocessing2/"  # Processed CSV files
LOG_FILE = "/workspaces/AlgoAI/scripts/logs/rdf_to_csv_log2.txt"
SCHEMA_REPORT_FILE = os.path.join(PREPROCESS_DIR, "draft_schema_report.json")

# Ensure the log directory exists
log_dir = os.path.dirname(LOG_FILE)
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

IGNORE_FILES = {
    "AboutFIBODev.rdf",
    "AboutFIBOProd-IncludingReferenceData.rdf",
    "AboutFIBOProd-TBoxOnly.rdf",
    "AboutFIBOProd.rdf",
    "catalog-v001.xml"
}

IGNORED_NAMESPACES = {"http://www.w3.org/2002/07/owl#"}
IGNORED_PREDICATES = {"core#changeNote", "adaptedFrom"}

ADDITIONAL_ALLOWED_PROPERTIES = {
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2004/02/skos/core#definition",
    "https://www.omg.org/spec/Commons/AnnotationVocabulary/explanatoryNote",
    "https://www.omg.org/spec/Commons/AnnotationVocabulary/abbreviation",
    "http://purl.org/dc/terms/abstract"
}
ALLOWED_LOCAL_PROPERTY_NAMES = {"definition", "explanatoryNote", "abbreviation", "abstract"}

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,  # Set to DEBUG to capture detailed logs
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ---------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------

def ensure_directory_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def remove_urls(text):
    """Removes any URLs from the given text."""
    return re.sub(r'http[s]?://\S+', '', text).strip()

def get_local_name(uri):
    """Extracts the local name from a URI by splitting on '#' first, then ';' then '/'."""
    if '#' in uri:
        return uri.split('#')[-1]
    if ';' in uri:
        return uri.split(';')[-1]
    return uri.split('/')[-1]

def find_rdf_files(directory, filename_filter=None):
    """Recursively finds all .rdf and .xml files in a directory, skipping IGNORE_FILES."""
    rdf_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file in IGNORE_FILES:
                continue
            if file.startswith("All") and file.endswith(".rdf"):
                continue
            if filename_filter and filename_filter.lower() not in file.lower():
                continue
            if file.endswith(".rdf") or file.endswith(".xml"):
                rdf_files.append(os.path.join(root, file))
    return rdf_files

def build_property_mapping(directory):
    """
    Builds a mapping from property URIs to domain-specific names using
    metadata files (those containing 'Metadata' in their filenames).
    """
    mapping = {}
    metadata_files = find_rdf_files(directory, filename_filter="Metadata")
    logging.info(f"Found {len(metadata_files)} metadata files.")
    for meta_file in metadata_files:
        meta_graph = rdflib.Graph()
        try:
            meta_graph.parse(meta_file, format="xml")
            logging.info(f"Parsed metadata file: {meta_file}")
            for s, p, o in meta_graph:
                if p == RDFS.label:
                    mapping[str(s)] = remove_urls(str(o))
        except Exception as e:
            logging.error(f"Failed to parse metadata file {meta_file}: {e}")
    logging.info(f"Built property mapping with {len(mapping)} entries.")
    return mapping

def get_blank_node_label(graph, blank_node, allowed_properties=None):
    label = graph.value(blank_node, RDFS.label)
    if label:
        return remove_urls(str(label))
    if allowed_properties:
        for p, o in graph.predicate_objects(blank_node):
            if str(p) in allowed_properties and isinstance(o, rdflib.term.Literal):
                return remove_urls(str(o))
    literals = []
    for p, o in graph.predicate_objects(blank_node):
        if isinstance(o, rdflib.term.Literal):
            literals.append(remove_urls(str(o)))
    if literals:
        return "_".join(literals[:2])
    return None

def extract_blank_node_properties(blank_node, graph, allowed_properties=None, depth=0, max_depth=3):
    props = {}
    if depth > max_depth:
        return props
    for p, o in graph.predicate_objects(blank_node):
        pred_local = get_local_name(str(p))
        if isinstance(o, rdflib.BNode):
            nested = extract_blank_node_properties(o, graph, allowed_properties, depth+1, max_depth)
            props[pred_local] = nested
        elif isinstance(o, rdflib.term.Literal):
            props[pred_local] = remove_urls(str(o))
        else:
            props[pred_local] = remove_urls(str(o))
    return props

def get_identifier(node, graph, bnode_map, allowed_properties=None):
    if isinstance(node, rdflib.BNode):
        if node not in bnode_map:
            label = get_blank_node_label(graph, node, allowed_properties)
            if label:
                bnode_map[node] = f"BN_{label.replace(' ', '_')}"
            else:
                bnode_map[node] = "B_" + str(uuid.uuid4())
        return bnode_map[node]
    return get_local_name(str(node))

# ---------------------------------------------------------------------
# Handling Nested subClassOf
# ---------------------------------------------------------------------

def parse_subclassof_blank_node(subject_id, blank_node, graph, edges, vertices, bnode_map,
                                processed_restriction_nodes, default_type, schema_info, allowed_property_uris):
    obj_key = blank_node.n3()
    logging.debug(f"Processing blank node for subClassOf: {obj_key}")

    # Check if this blank node is an owl:Restriction block.
    on_prop_val = graph.value(blank_node, rdflib.URIRef("http://www.w3.org/2002/07/owl#onProperty"))
    if on_prop_val:
        attributes = []
        values = []
        # onProperty is mandatory in a restriction.
        attributes.append("onProperty")
        values.append(get_local_name(str(on_prop_val)))

        # Check for owl:someValuesFrom.
        some_val_val = graph.value(blank_node, rdflib.URIRef("http://www.w3.org/2002/07/owl#someValuesFrom"))
        if some_val_val:
            attributes.append("someValuesFrom")
            if isinstance(some_val_val, rdflib.BNode):
                union_node = graph.value(some_val_val, rdflib.URIRef("http://www.w3.org/2002/07/owl#unionOf"))
                if union_node:
                    try:
                        col = Collection(graph, union_node)
                        union_locals = [get_local_name(str(m)) for m in col]
                        val = ", ".join(union_locals)
                    except Exception as e:
                        logging.error(f"Error processing owl:unionOf: {e}")
                        val = get_local_name(str(some_val_val))
                else:
                    val = get_local_name(str(some_val_val))
            else:
                val = get_local_name(str(some_val_val))
            values.append(val)
        # Else, check for owl:allValuesFrom.
        else:
            all_val_val = graph.value(blank_node, rdflib.URIRef("http://www.w3.org/2002/07/owl#allValuesFrom"))
            if all_val_val:
                attributes.append("allValuesFrom")
                if isinstance(all_val_val, rdflib.BNode):
                    union_node = graph.value(all_val_val, rdflib.URIRef("http://www.w3.org/2002/07/owl#unionOf"))
                    if union_node:
                        try:
                            col = Collection(graph, union_node)
                            union_locals = [get_local_name(str(m)) for m in col]
                            val = ", ".join(union_locals)
                        except Exception as e:
                            logging.error(f"Error processing owl:unionOf in allValuesFrom: {e}")
                            val = get_local_name(str(all_val_val))
                    else:
                        val = get_local_name(str(all_val_val))
                else:
                    val = get_local_name(str(all_val_val))
                values.append(val)
            else:
                # Check for owl:onClass.
                on_class_val = graph.value(blank_node, rdflib.URIRef("http://www.w3.org/2002/07/owl#onClass"))
                if on_class_val:
                    attributes.append("onClass")
                    values.append(get_local_name(str(on_class_val)))
                else:
                    values.append("")

        # Form the outputs.
        restrictionType = ", ".join(attributes)
        restrictionData = ", ".join(values)

        # Mark as processed.
        processed_restriction_nodes.add(obj_key)
        # Ensure subject vertex exists.
        if subject_id not in vertices:
            vertices[subject_id] = {"id": subject_id, "type": default_type, "name": subject_id}
            if schema_info is not None:
                schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])

        # Create the restriction edge. Note that the relationship is still "subClassOf".
        edge = {
            "source_id": subject_id,
            "target_id": restrictionData,
            "relationship": "subClassOf",
            "restrictionType": restrictionType,
            "restrictionData": restrictionData
        }
        logging.debug(f"Appending restriction edge: {edge}")
        edges.append(edge)
        if schema_info is not None:
            schema_info.setdefault("edge_types", {}).setdefault("subClassOf", {"from": set(), "to": set()})
            schema_info["edge_types"]["subClassOf"]["from"].add(vertices[subject_id]["type"])
            schema_info["edge_types"]["subClassOf"]["to"].add(default_type)
        return

    # If not a restriction block, look for nested subClassOf statements.
    found_nested_subclassof = False
    for p, o in graph.predicate_objects(blank_node):
        if get_local_name(str(p)) == "subClassOf":
            found_nested_subclassof = True
            if isinstance(o, rdflib.BNode):
                parse_subclassof_blank_node(subject_id, o, graph, edges, vertices, bnode_map,
                                            processed_restriction_nodes, default_type, schema_info, allowed_property_uris)
            else:
                obj_id = get_identifier(o, graph, bnode_map, allowed_property_uris)
                if subject_id not in vertices:
                    vertices[subject_id] = {"id": subject_id, "type": default_type, "name": subject_id}
                    if schema_info is not None:
                        schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])
                if obj_id not in vertices:
                    vertices[obj_id] = {"id": obj_id, "type": default_type, "name": obj_id}
                    if schema_info is not None:
                        schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])
                edge = {
                    "source_id": subject_id,
                    "target_id": obj_id,
                    "relationship": "subClassOf",
                    "restrictionType": "",
                    "restrictionData": ""
                }
                logging.debug(f"Appending nested subClassOf edge: {edge}")
                edges.append(edge)
                if schema_info is not None:
                    schema_info.setdefault("edge_types", {}).setdefault("subClassOf", {"from": set(), "to": set()})
                    schema_info["edge_types"]["subClassOf"]["from"].add(vertices[subject_id]["type"])
                    schema_info["edge_types"]["subClassOf"]["to"].add(vertices[obj_id]["type"])
    # If no nested subClassOf was found, treat the blank node as a plain one.
    if not found_nested_subclassof:
        target_id = get_identifier(blank_node, graph, bnode_map, allowed_property_uris)
        if subject_id not in vertices:
            vertices[subject_id] = {"id": subject_id, "type": default_type, "name": subject_id}
            if schema_info is not None:
                schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])
        if target_id not in vertices:
            vertices[target_id] = {"id": target_id, "type": default_type, "name": target_id}
            if schema_info is not None:
                schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])
        edge = {
            "source_id": subject_id,
            "target_id": target_id,
            "relationship": "subClassOf",
            "restrictionType": "",
            "restrictionData": ""
        }
        logging.debug(f"Appending plain blank node subClassOf edge: {edge}")
        edges.append(edge)
        if schema_info is not None:
            schema_info.setdefault("edge_types", {}).setdefault("subClassOf", {"from": set(), "to": set()})
            schema_info["edge_types"]["subClassOf"]["from"].add(vertices[subject_id]["type"])
            schema_info["edge_types"]["subClassOf"]["to"].add(vertices[target_id]["type"])

# ---------------------------------------------------------------------
# Main Conversion Logic
# ---------------------------------------------------------------------

def parse_rdf_to_csv(rdf_path, vertices_csv, edges_csv, default_type="Entity", schema_info=None, property_mapping=None):
    graph = rdflib.Graph()
    try:
        graph.parse(rdf_path, format="xml")
        logging.info(f"Successfully parsed {rdf_path} with {len(graph)} triples")
    except Exception as e:
        logging.error(f"Failed to parse {rdf_path}: {str(e)}")
        return

    vertices = {}  # vertex id -> dict of properties
    edges = []     # list of edge dictionaries
    bnode_map = {}
    processed_restriction_nodes = set()

    # Combine property mapping keys with additional allowed properties.
    allowed_property_uris = set()
    if property_mapping:
        allowed_property_uris.update(property_mapping.keys())
    allowed_property_uris.update(ADDITIONAL_ALLOWED_PROPERTIES)

    # --- Group subClassOf triples by subject ---
    subclass_triples = {}  # subject -> list of objects for rdfs:subClassOf
    other_triples = []     # all other triples

    triple_count = 0
    for subj, pred, obj in graph:
        triple_count += 1
        # Skip owl:Ontology declaration triples.
        if pred == RDF.type and str(obj) == "http://www.w3.org/2002/07/owl#Ontology":
            continue

        pred_local = get_local_name(str(pred))
        if pred_local == "subClassOf":
            subclass_triples.setdefault(subj, []).append(obj)
        else:
            other_triples.append((subj, pred, obj))

    # --- Process all subClassOf triples for each subject ---
    for subj, obj_list in subclass_triples.items():
        subj_id = get_identifier(subj, graph, bnode_map, allowed_property_uris)
        if subj_id not in vertices:
            vertices[subj_id] = {"id": subj_id, "type": default_type, "name": subj_id}
            if schema_info is not None:
                schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])

        for obj in obj_list:
            if isinstance(obj, rdflib.BNode):
                parse_subclassof_blank_node(
                    subj_id, obj, graph, edges, vertices, bnode_map,
                    processed_restriction_nodes, default_type, schema_info, allowed_property_uris
                )
            else:
                obj_id = get_identifier(obj, graph, bnode_map, allowed_property_uris)
                if obj_id not in vertices:
                    vertices[obj_id] = {"id": obj_id, "type": default_type, "name": obj_id}
                    if schema_info is not None:
                        schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])
                edge = {
                    "source_id": subj_id,
                    "target_id": obj_id,
                    "relationship": "subClassOf",
                    "restrictionType": "",
                    "restrictionData": ""
                }
                logging.debug(f"Appending plain subClassOf edge: {edge}")
                edges.append(edge)
                if schema_info is not None:
                    schema_info.setdefault("edge_types", {}).setdefault("subClassOf", {"from": set(), "to": set()})
                    schema_info["edge_types"]["subClassOf"]["from"].add(vertices[subj_id]["type"])
                    schema_info["edge_types"]["subClassOf"]["to"].add(vertices[obj_id]["type"])

    # --- Process all other triples ---
    for subj, pred, obj in other_triples:
        subj_id = get_identifier(subj, graph, bnode_map, allowed_property_uris)
        pred_uri = str(pred)
        pred_local = get_local_name(pred_uri)

        if any(pred_uri.startswith(ns) for ns in IGNORED_NAMESPACES):
            if not (property_mapping and pred_uri in property_mapping):
                continue
        if pred_local in IGNORED_PREDICATES:
            continue
        if pred != RDF.type and (pred_uri not in allowed_property_uris and pred_local not in ALLOWED_LOCAL_PROPERTY_NAMES):
            continue

        if pred == RDF.type:
            type_name = get_local_name(str(obj))
            if type_name == "Ontology":
                continue
            if subj_id in vertices:
                vertices[subj_id]["type"] = type_name
            else:
                vertices[subj_id] = {"id": subj_id, "type": type_name, "name": subj_id}
            if schema_info is not None:
                schema_info.setdefault("vertex_types", {}).setdefault(type_name, set()).update(["id", "name"])
        elif property_mapping and pred_uri in property_mapping:
            prop_key = property_mapping[pred_uri]
            if subj_id not in vertices:
                vertices[subj_id] = {"id": subj_id, "type": default_type, "name": subj_id}
                if schema_info is not None:
                    schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])
            if isinstance(obj, rdflib.BNode):
                nested = extract_blank_node_properties(obj, graph, allowed_property_uris)
                vertices[subj_id][prop_key] = json.dumps(nested)
            else:
                vertices[subj_id][prop_key] = remove_urls(str(obj))
            if schema_info is not None:
                schema_info.setdefault("vertex_properties", {}).setdefault(prop_key, set()).add("string")
        elif pred_uri in ADDITIONAL_ALLOWED_PROPERTIES or pred_local in ALLOWED_LOCAL_PROPERTY_NAMES:
            prop_key = property_mapping[pred_uri] if (property_mapping and pred_uri in property_mapping) else pred_local
            if subj_id not in vertices:
                vertices[subj_id] = {"id": subj_id, "type": default_type, "name": subj_id}
                if schema_info is not None:
                    schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])
            if isinstance(obj, rdflib.BNode):
                nested = extract_blank_node_properties(obj, graph, allowed_property_uris)
                vertices[subj_id][prop_key] = json.dumps(nested)
            else:
                vertices[subj_id][prop_key] = remove_urls(str(obj))
            if schema_info is not None:
                schema_info.setdefault("vertex_properties", {}).setdefault(prop_key, set()).add("string")
        else:
            obj_id = get_identifier(obj, graph, bnode_map, allowed_property_uris)
            if subj_id not in vertices:
                vertices[subj_id] = {"id": subj_id, "type": default_type, "name": subj_id}
                if schema_info is not None:
                    schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])
            if obj_id not in vertices:
                vertices[obj_id] = {"id": obj_id, "type": default_type, "name": obj_id}
                if schema_info is not None:
                    schema_info.setdefault("vertex_types", {}).setdefault(default_type, set()).update(["id", "name"])
            edge = {
                "source_id": subj_id,
                "target_id": obj_id,
                "relationship": pred_local,
                "restrictionType": "",
                "restrictionData": ""
            }
            logging.debug(f"Appending generic edge: {edge}")
            edges.append(edge)
            if schema_info is not None:
                schema_info.setdefault("edge_types", {}).setdefault(pred_local, {"from": set(), "to": set()})
                schema_info["edge_types"][pred_local]["from"].add(vertices[subj_id]["type"])
                schema_info["edge_types"][pred_local]["to"].add(vertices[obj_id]["type"])

    logging.info(f"Processed {triple_count} triples in {rdf_path}")

    # Write vertices CSV.
    all_keys = set()
    for vertex_data in vertices.values():
        all_keys.update(vertex_data.keys())
    all_keys = list(all_keys)
    with open(vertices_csv, "w", newline="") as v_file:
        writer = csv.DictWriter(v_file, fieldnames=all_keys)
        writer.writeheader()
        for vertex_data in vertices.values():
            writer.writerow(vertex_data)

    # Write edges CSV.
    edge_headers = ["source_id", "target_id", "relationship", "restrictionType", "restrictionData"]
    with open(edges_csv, "w", newline="") as e_file:
        writer = csv.DictWriter(e_file, fieldnames=edge_headers)
        writer.writeheader()
        for edge_data in edges:
            writer.writerow(edge_data)

    logging.info(f"Converted {rdf_path} -> {vertices_csv}, {edges_csv}")

def convert_all_rdf_to_csv():
    draft_schema = {"vertex_types": {}, "edge_types": {}, "vertex_properties": {}}
    property_map = build_property_mapping(FIBO_DIR)

    for ontology_name in os.listdir(FIBO_DIR):
        if ontology_name in ["etc", ".github"]:
            logging.info(f"Ignoring folder: {ontology_name}")
            continue

        ontology_folder = os.path.join(FIBO_DIR, ontology_name)
        if not os.path.isdir(ontology_folder):
            continue

        output_folder = os.path.join(PREPROCESS_DIR, ontology_name)
        ensure_directory_exists(output_folder)
        logging.info(f"Processing ontology: {ontology_name}")

        rdf_files = find_rdf_files(ontology_folder)
        rdf_files = [f for f in rdf_files if "metadata" not in os.path.basename(f).lower()]
        if not rdf_files:
            logging.warning(f"No RDF files found in {ontology_folder}")
            continue

        default_type = ontology_name
        for rdf_path in rdf_files:
            rdf_filename = os.path.basename(rdf_path).replace(".rdf", "").replace(".xml", "")
            vertices_csv = os.path.join(output_folder, f"{rdf_filename}_vertices.csv")
            edges_csv = os.path.join(output_folder, f"{rdf_filename}_edges.csv")
            parse_rdf_to_csv(rdf_path, vertices_csv, edges_csv, default_type=default_type,
                             schema_info=draft_schema, property_mapping=property_map)

    for vtype in draft_schema.get("vertex_types", {}):
        draft_schema["vertex_types"][vtype] = list(draft_schema["vertex_types"][vtype])
    for prop in draft_schema.get("vertex_properties", {}):
        draft_schema["vertex_properties"][prop] = list(draft_schema["vertex_properties"][prop])
    for etype in draft_schema.get("edge_types", {}):
        draft_schema["edge_types"][etype]["from"] = list(draft_schema["edge_types"][etype]["from"])
        draft_schema["edge_types"][etype]["to"] = list(draft_schema["edge_types"][etype]["to"])

    with open(SCHEMA_REPORT_FILE, "w") as schema_file:
        json.dump(draft_schema, schema_file, indent=4)

    logging.info("RDF to CSV conversion completed for all ontologies. Schema report generated.")

if __name__ == "__main__":
    convert_all_rdf_to_csv()
