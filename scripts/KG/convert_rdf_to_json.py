import os
import rdflib
import logging
import json
import re
from rdflib.namespace import RDF, RDFS, SKOS
from rdflib.collection import Collection

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
FIBO_DIR = "/workspaces/AlgoAI/graphdb/fibo"  # Raw RDF files
PREPROCESS_DIR = "/workspaces/AlgoAI/graphdb/preprocessing3/"  # Output folder
LOG_FILE = "/workspaces/AlgoAI/scripts/logs/rdf_to_json_log.txt"
SCHEMA_REPORT_FILE = os.path.join(PREPROCESS_DIR, "draft_schema_report.json")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

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
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ---------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------
def ensure_directory_exists(path):
    os.makedirs(path, exist_ok=True)

def remove_urls(text):
    return re.sub(r'http[s]?://\S+', '', text).strip()

def get_local_name(uri):
    if '#' in uri:
        return uri.split('#')[-1]
    if ';' in uri:
        return uri.split(';')[-1]
    return uri.split('/')[-1]

def find_rdf_files(directory, filename_filter=None):
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
    literals = [remove_urls(str(o)) for p, o in graph.predicate_objects(blank_node)
                if isinstance(o, rdflib.term.Literal)]
    return "_".join(literals[:2]) if literals else None

def extract_blank_node_properties(blank_node, graph, allowed_properties=None, depth=0, max_depth=3):
    props = {}
    if depth > max_depth:
        return props
    for p, o in graph.predicate_objects(blank_node):
        pred_local = get_local_name(str(p))
        if isinstance(o, rdflib.BNode):
            props[pred_local] = extract_blank_node_properties(o, graph, allowed_properties, depth+1, max_depth)
        elif isinstance(o, rdflib.term.Literal):
            props[pred_local] = remove_urls(str(o))
        else:
            props[pred_local] = remove_urls(str(o))
    return props

def get_identifier(node, graph, bnode_map, allowed_properties=None):
    # Do not assign any ID for any blank node.
    if isinstance(node, rdflib.BNode):
        return None
    identifier = get_local_name(str(node))
    return identifier if identifier.strip() != "" else None

# ---------------------------------------------------------------------
# New Helper: Check for Invalid IDs
# ---------------------------------------------------------------------
def is_invalid_id(vertex_id):
    if vertex_id is None or vertex_id.strip() == "":
        return True
    # Match IDs that start with "N" or "n" followed by exactly 32 hexadecimal digits.
    if re.match(r'^[Nn][a-f0-9]{32}$', vertex_id):
        return True
    # Also match blank node patterns starting with "B_"
    if re.match(r'^B_[a-f0-9\-]+$', vertex_id, re.IGNORECASE):
        return True
    return False

# ---------------------------------------------------------------------
# Recursive Processing of Restriction Blocks
# ---------------------------------------------------------------------
def process_restriction(blank_node, graph, bnode_map, allowed_property_uris, subject_id):
    """
    Recursively processes an owl:Restriction block.
    Returns (attributes_list, values_list, target_id).
    """
    attributes = []
    values = []
    
    on_prop_val = graph.value(blank_node, rdflib.URIRef("http://www.w3.org/2002/07/owl#onProperty"))
    if not on_prop_val:
        return (attributes, values, subject_id)
    attributes.append("onProperty")
    outer_val = get_local_name(str(on_prop_val))
    values.append(outer_val)
    target = outer_val if not is_invalid_id(outer_val) else subject_id
    
    for prop_uri, key in [
         (rdflib.URIRef("http://www.w3.org/2002/07/owl#someValuesFrom"), "someValuesFrom"),
         (rdflib.URIRef("http://www.w3.org/2002/07/owl#allValuesFrom"), "allValuesFrom"),
         (rdflib.URIRef("http://www.w3.org/2002/07/owl#onClass"), "onClass")
         ]:
        value = graph.value(blank_node, prop_uri)
        if value:
            attributes.append(key)
            if isinstance(value, rdflib.BNode):
                union_node = graph.value(value, rdflib.URIRef("http://www.w3.org/2002/07/owl#unionOf"))
                if union_node:
                    try:
                        col = Collection(graph, union_node)
                        union_members = [get_local_name(str(m)) for m in col]
                        joined_union_str = ", ".join(union_members)
                        values.append(union_members)  # structured as array in restriction data
                        target = joined_union_str if not is_invalid_id(joined_union_str) else subject_id
                    except Exception as e:
                        logging.error(f"Error processing owl:unionOf: {e}")
                        val = get_local_name(str(value))
                        values.append(val)
                        target = val if not is_invalid_id(val) else subject_id
                elif graph.value(value, rdflib.URIRef("http://www.w3.org/2002/07/owl#onProperty")):
                    inner_attrs, inner_vals, inner_target = process_restriction(value, graph, bnode_map, allowed_property_uris, subject_id)
                    attributes.extend(inner_attrs)
                    values.extend(inner_vals)
                    target = inner_target if not is_invalid_id(inner_target) else subject_id
                else:
                    val = get_local_name(str(value))
                    values.append(val)
                    target = val if not is_invalid_id(val) else subject_id
            else:
                val = get_local_name(str(value))
                values.append(val)
                target = val if not is_invalid_id(val) else subject_id
            break
    return (attributes, values, target)

# ---------------------------------------------------------------------
# Handling subClassOf with Restrictions Embedded in Edges
# ---------------------------------------------------------------------
def parse_subclassof_blank_node(subject_id, blank_node, graph, edges, vertices, bnode_map,
                                processed_restriction_nodes, default_type, schema_info, allowed_property_uris):
    obj_key = blank_node.n3()
    logging.debug(f"Processing blank node for subClassOf: {obj_key}")
    
    if graph.value(blank_node, rdflib.URIRef("http://www.w3.org/2002/07/owl#onProperty")):
        attrs, vals, target_id = process_restriction(blank_node, graph, bnode_map, allowed_property_uris, subject_id)
        restriction_data = {"attributes": attrs, "values": vals}
        if not target_id or is_invalid_id(target_id):
            target_id = subject_id
        edge = {
            "source_id": subject_id,
            "target_id": target_id,
            "relationship": "subClassOf",
            "restriction": restriction_data
        }
        logging.debug(f"Appending restriction edge: {edge}")
        edges.append(edge)
        if schema_info is not None:
            vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
            if not isinstance(vt, set):
                vt = set(vt)
                schema_info["vertex_types"][default_type] = vt
            vt.update(["id", "name"])
            schema_info.setdefault("edge_types", {}).setdefault("subClassOf", {"from": set(), "to": set()})
            schema_info["edge_types"]["subClassOf"]["from"].add(vertices.get(subject_id, {"type": default_type})["type"])
            schema_info["edge_types"]["subClassOf"]["to"].add(default_type)
        return

    found_nested = False
    for p, o in graph.predicate_objects(blank_node):
        if get_local_name(str(p)) == "subClassOf":
            found_nested = True
            if isinstance(o, rdflib.BNode):
                parse_subclassof_blank_node(subject_id, o, graph, edges, vertices, bnode_map,
                                            processed_restriction_nodes, default_type, schema_info, allowed_property_uris)
            else:
                obj_id = get_identifier(o, graph, bnode_map, allowed_property_uris)
                if not obj_id or is_invalid_id(obj_id):
                    continue
                if subject_id not in vertices:
                    vertices[subject_id] = {"id": subject_id, "type": default_type, "name": subject_id}
                    vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
                    if not isinstance(vt, set):
                        vt = set(vt)
                        schema_info["vertex_types"][default_type] = vt
                    vt.update(["id", "name"])
                if obj_id not in vertices:
                    vertices[obj_id] = {"id": obj_id, "type": default_type, "name": obj_id}
                    vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
                    if not isinstance(vt, set):
                        vt = set(vt)
                        schema_info["vertex_types"][default_type] = vt
                    vt.update(["id", "name"])
                edge = {
                    "source_id": subject_id,
                    "target_id": obj_id,
                    "relationship": "subClassOf",
                    "restriction": None
                }
                logging.debug(f"Appending nested plain subClassOf edge: {edge}")
                edges.append(edge)
                schema_info.setdefault("edge_types", {}).setdefault("subClassOf", {"from": set(), "to": set()})
                schema_info["edge_types"]["subClassOf"]["from"].add(vertices[subject_id]["type"])
                schema_info["edge_types"]["subClassOf"]["to"].add(vertices[obj_id]["type"])
    if not found_nested:
        target_id = get_identifier(blank_node, graph, bnode_map, allowed_property_uris)
        if not target_id or is_invalid_id(target_id):
            target_id = subject_id
        if subject_id not in vertices:
            vertices[subject_id] = {"id": subject_id, "type": default_type, "name": subject_id}
            vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
            if not isinstance(vt, set):
                vt = set(vt)
                schema_info["vertex_types"][default_type] = vt
            vt.update(["id", "name"])
        if target_id not in vertices:
            vertices[target_id] = {"id": target_id, "type": default_type, "name": target_id}
            vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
            if not isinstance(vt, set):
                vt = set(vt)
                schema_info["vertex_types"][default_type] = vt
            vt.update(["id", "name"])
        edge = {
            "source_id": subject_id,
            "target_id": target_id,
            "relationship": "subClassOf",
            "restriction": None
        }
        logging.debug(f"Appending plain blank node subClassOf edge: {edge}")
        edges.append(edge)
        schema_info.setdefault("edge_types", {}).setdefault("subClassOf", {"from": set(), "to": set()})
        schema_info["edge_types"]["subClassOf"]["from"].add(vertices[subject_id]["type"])
        schema_info["edge_types"]["subClassOf"]["to"].add(vertices[target_id]["type"])

# ---------------------------------------------------------------------
# Schema Validation and Self-Correction
# ---------------------------------------------------------------------
def validate_and_fix_schema(vertices, edges, schema_info):
    valid_vertices = [v for v in vertices if v.get("id") and not is_invalid_id(v.get("id"))]
    valid_ids = set(v["id"] for v in valid_vertices)
    valid_edges = [edge for edge in edges if edge["source_id"] in valid_ids and edge["target_id"] in valid_ids]
    
    if "vertex_types" in schema_info:
        cleaned_types = {}
        for type_key, props in schema_info["vertex_types"].items():
            if not is_invalid_id(type_key):
                cleaned_types[type_key] = list(props)
            else:
                logging.debug(f"Removing invalid vertex type from schema: {type_key}")
        schema_info["vertex_types"] = cleaned_types
    return valid_vertices, valid_edges, schema_info

# ---------------------------------------------------------------------
# Main Conversion Logic with JSON Output
# ---------------------------------------------------------------------
def parse_rdf_to_json(rdf_path, vertices_json, edges_json, default_type="Entity", schema_info=None, property_mapping=None):
    graph = rdflib.Graph()
    try:
        graph.parse(rdf_path, format="xml")
        logging.info(f"Successfully parsed {rdf_path} with {len(graph)} triples")
    except Exception as e:
        logging.error(f"Failed to parse {rdf_path}: {str(e)}")
        return

    vertices = {}
    edges = []
    bnode_map = {}
    processed_restriction_nodes = set()

    allowed_property_uris = set()
    if property_mapping:
        allowed_property_uris.update(property_mapping.keys())
    allowed_property_uris.update(ADDITIONAL_ALLOWED_PROPERTIES)

    subclass_triples = {}
    other_triples = []
    triple_count = 0
    for subj, pred, obj in graph:
        triple_count += 1
        if pred == RDF.type and str(obj) == "http://www.w3.org/2002/07/owl#Ontology":
            continue
        pred_local = get_local_name(str(pred))
        if pred_local == "subClassOf":
            subclass_triples.setdefault(subj, []).append(obj)
        else:
            other_triples.append((subj, pred, obj))

    for subj, obj_list in subclass_triples.items():
        subj_id = get_identifier(subj, graph, bnode_map, allowed_property_uris)
        if not subj_id or is_invalid_id(subj_id):
            continue
        if subj_id not in vertices:
            vertices[subj_id] = {"id": subj_id, "type": default_type, "name": subj_id}
            vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
            if not isinstance(vt, set):
                vt = set(vt)
                schema_info["vertex_types"][default_type] = vt
            vt.update(["id", "name"])
        for obj in obj_list:
            if isinstance(obj, rdflib.BNode):
                if graph.value(obj, rdflib.URIRef("http://www.w3.org/2002/07/owl#onProperty")):
                    parse_subclassof_blank_node(
                        subj_id, obj, graph, edges, vertices, bnode_map,
                        processed_restriction_nodes, default_type, schema_info, allowed_property_uris
                    )
                else:
                    obj_id = get_identifier(obj, graph, bnode_map, allowed_property_uris)
                    if not obj_id or is_invalid_id(obj_id):
                        continue
                    if obj_id not in vertices:
                        vertices[obj_id] = {"id": obj_id, "type": default_type, "name": obj_id}
                        vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
                        if not isinstance(vt, set):
                            vt = set(vt)
                            schema_info["vertex_types"][default_type] = vt
                        vt.update(["id", "name"])
                    edge = {
                        "source_id": subj_id,
                        "target_id": obj_id,
                        "relationship": "subClassOf",
                        "restriction": None
                    }
                    logging.debug(f"Appending plain subClassOf edge (blank node): {edge}")
                    edges.append(edge)
            else:
                obj_id = get_local_name(str(obj))
                if not obj_id or is_invalid_id(obj_id):
                    continue
                if obj_id not in vertices:
                    vertices[obj_id] = {"id": obj_id, "type": default_type, "name": obj_id}
                    vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
                    if not isinstance(vt, set):
                        vt = set(vt)
                        schema_info["vertex_types"][default_type] = vt
                    vt.update(["id", "name"])
                edge = {
                    "source_id": subj_id,
                    "target_id": obj_id,
                    "relationship": "subClassOf",
                    "restriction": None
                }
                logging.debug(f"Appending plain subClassOf edge: {edge}")
                edges.append(edge)
    for subj, pred, obj in other_triples:
        subj_id = get_identifier(subj, graph, bnode_map, allowed_property_uris)
        if not subj_id or is_invalid_id(subj_id):
            continue
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
            vt = schema_info.setdefault("vertex_types", {}).setdefault(type_name, set())
            if not isinstance(vt, set):
                vt = set(vt)
                schema_info["vertex_types"][type_name] = vt
            vt.update(["id", "name"])
        elif property_mapping and pred_uri in property_mapping:
            prop_key = property_mapping[pred_uri]
            if subj_id not in vertices:
                vertices[subj_id] = {"id": subj_id, "type": default_type, "name": subj_id}
                vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
                if not isinstance(vt, set):
                    vt = set(vt)
                    schema_info["vertex_types"][default_type] = vt
                vt.update(["id", "name"])
            if isinstance(obj, rdflib.BNode):
                nested = extract_blank_node_properties(obj, graph, allowed_property_uris)
                vertices[subj_id][prop_key] = json.dumps(nested)
            else:
                vertices[subj_id][prop_key] = remove_urls(str(obj))
            schema_info.setdefault("vertex_properties", {}).setdefault(prop_key, set()).add("string")
        elif pred_uri in ADDITIONAL_ALLOWED_PROPERTIES or pred_local in ALLOWED_LOCAL_PROPERTY_NAMES:
            prop_key = property_mapping[pred_uri] if (property_mapping and pred_uri in property_mapping) else pred_local
            if subj_id not in vertices:
                vertices[subj_id] = {"id": subj_id, "type": default_type, "name": subj_id}
                vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
                if not isinstance(vt, set):
                    vt = set(vt)
                    schema_info["vertex_types"][default_type] = vt
                vt.update(["id", "name"])
            if isinstance(obj, rdflib.BNode):
                nested = extract_blank_node_properties(obj, graph, allowed_property_uris)
                vertices[subj_id][prop_key] = json.dumps(nested)
            else:
                vertices[subj_id][prop_key] = remove_urls(str(obj))
            schema_info.setdefault("vertex_properties", {}).setdefault(prop_key, set()).add("string")
        else:
            obj_id = get_local_name(str(obj))
            if not obj_id or is_invalid_id(obj_id):
                continue
            if subj_id not in vertices:
                vertices[subj_id] = {"id": subj_id, "type": default_type, "name": subj_id}
                vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
                if not isinstance(vt, set):
                    vt = set(vt)
                    schema_info["vertex_types"][default_type] = vt
                vt.update(["id", "name"])
            if obj_id not in vertices:
                vertices[obj_id] = {"id": obj_id, "type": default_type, "name": obj_id}
                vt = schema_info.setdefault("vertex_types", {}).setdefault(default_type, set())
                if not isinstance(vt, set):
                    vt = set(vt)
                    schema_info["vertex_types"][default_type] = vt
                vt.update(["id", "name"])
            edge = {
                "source_id": subj_id,
                "target_id": obj_id,
                "relationship": pred_local,
                "restriction": None
            }
            logging.debug(f"Appending generic edge: {edge}")
            edges.append(edge)
            schema_info.setdefault("edge_types", {}).setdefault(pred_local, {"from": set(), "to": set()})
            schema_info["edge_types"][pred_local]["from"].add(vertices[subj_id]["type"])
            schema_info["edge_types"][pred_local]["to"].add(vertices[obj_id]["type"])

    logging.info(f"Processed {triple_count} triples in {rdf_path}")
    valid_vertices, valid_edges, schema_info = validate_and_fix_schema(list(vertices.values()), edges, schema_info)
    with open(vertices_json, "w") as v_file:
        json.dump(valid_vertices, v_file, indent=4)
    with open(edges_json, "w") as e_file:
        json.dump(valid_edges, e_file, indent=4)
    logging.info(f"Converted {rdf_path} -> {vertices_json}, {edges_json}")

# ---------------------------------------------------------------------
# Main Conversion Routine with JSON Output
# ---------------------------------------------------------------------
def convert_all_rdf_to_json():
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
        default_type = "Entity"
        for rdf_path in rdf_files:
            rdf_filename = os.path.basename(rdf_path).replace(".rdf", "").replace(".xml", "")
            vertices_json = os.path.join(output_folder, f"{rdf_filename}_vertices.json")
            edges_json = os.path.join(output_folder, f"{rdf_filename}_edges.json")
            parse_rdf_to_json(rdf_path, vertices_json, edges_json, default_type=default_type,
                             schema_info=draft_schema, property_mapping=property_map)
    # Convert sets in schema_info to lists
    for vtype in draft_schema.get("vertex_types", {}):
        draft_schema["vertex_types"][vtype] = list(draft_schema["vertex_types"][vtype])
    for prop in draft_schema.get("vertex_properties", {}):
        draft_schema["vertex_properties"][prop] = list(draft_schema["vertex_properties"][prop])
    for etype in draft_schema.get("edge_types", {}):
        draft_schema["edge_types"][etype]["from"] = list(draft_schema["edge_types"][etype]["from"])
        draft_schema["edge_types"][etype]["to"] = list(draft_schema["edge_types"][etype]["to"])
    with open(SCHEMA_REPORT_FILE, "w") as schema_file:
        json.dump(draft_schema, schema_file, indent=4)
    logging.info("RDF to JSON conversion completed for all ontologies. Schema report generated.")

if __name__ == "__main__":
    convert_all_rdf_to_json()
