import os
import rdflib
import csv
import logging

# Paths
FIBO_DIR = "/workspaces/FinRAG/graphdb/fibo"  # Raw RDF files
PREPROCESS_DIR = "/workspaces/FinRAG/graphdb/preprocessing/"  # Processed CSV files
LOG_FILE = "logs/rdf_to_csv_log.txt"

# Setup logging
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def ensure_directory_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def find_rdf_files(directory):
    """Recursively finds all .rdf files in a directory and its subdirectories."""
    rdf_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".rdf"):
                rdf_files.append(os.path.join(root, file))
    return rdf_files

def parse_rdf_to_csv(rdf_path, vertices_csv, edges_csv):
    """Parses an RDF file and converts it into TigerGraph-compatible CSVs."""
    graph = rdflib.Graph()
    try:
        graph.parse(rdf_path, format="xml")
        logging.info(f"Successfully parsed {rdf_path}")
    except Exception as e:
        logging.error(f"Failed to parse {rdf_path}: {str(e)}")
        return

    vertices = set()
    edges = set()

    for subj, pred, obj in graph:
        subj_id = str(subj).split("/")[-1]  # Extract last part of URI as ID
        obj_id = str(obj).split("/")[-1]  # Extract last part of URI as ID
        pred_name = str(pred).split("/")[-1]  # Relationship type

        # Add subjects and objects as vertices
        vertices.add((subj_id, "Entity", subj_id))
        vertices.add((obj_id, "Entity", obj_id))

        # Add the edge (relationship)
        edges.add((subj_id, obj_id, pred_name))

    # Write vertices.csv
    with open(vertices_csv, "w", newline="") as v_file:
        writer = csv.writer(v_file)
        writer.writerow(["id", "type", "name"])  # CSV header
        writer.writerows(vertices)

    # Write edges.csv
    with open(edges_csv, "w", newline="") as e_file:
        writer = csv.writer(e_file)
        writer.writerow(["source_id", "target_id", "relationship"])  # CSV header
        writer.writerows(edges)

    logging.info(f"Converted {rdf_path} -> {vertices_csv}, {edges_csv}")

def convert_all_rdf_to_csv():
    """Processes all RDF files under FIBO_DIR and converts them to CSV."""
    for ontology_name in os.listdir(FIBO_DIR):
        ontology_folder = os.path.join(FIBO_DIR, ontology_name)
        output_folder = os.path.join(PREPROCESS_DIR, ontology_name)
        
        if not os.path.isdir(ontology_folder):
            continue  # Skip if not a valid directory
        
        ensure_directory_exists(output_folder)
        logging.info(f"Processing ontology: {ontology_name}")
        
        rdf_files = find_rdf_files(ontology_folder)  # Recursively find RDF files
        
        if not rdf_files:
            logging.warning(f"No RDF files found in {ontology_folder}")
            continue
        
        for rdf_path in rdf_files:
            rdf_filename = os.path.basename(rdf_path).replace(".rdf", "")
            vertices_csv = os.path.join(output_folder, f"{rdf_filename}_vertices.csv")
            edges_csv = os.path.join(output_folder, f"{rdf_filename}_edges.csv")
            
            parse_rdf_to_csv(rdf_path, vertices_csv, edges_csv)
        
    logging.info("RDF to CSV conversion completed for all ontologies.")

if __name__ == "__main__":
    convert_all_rdf_to_csv()
