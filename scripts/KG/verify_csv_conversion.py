import os
import csv
import logging

# Paths
FIBO_DIR = "/workspaces/FinRAG/graphdb/fibo/"  # Raw RDF files
PREPROCESS_DIR = "/workspaces/FinRAG/graphdb/preprocessing/"  # Processed CSV files
LOG_FILE = "logs/csv_verification_log.txt"

# Setup logging
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def verify_csv_structure(vertices_csv, edges_csv):
    """Checks that CSV files are properly structured and contain expected data."""
    nodes = set()
    edges = []
    
    # Verify vertices.csv
    if not os.path.exists(vertices_csv):
        logging.error(f"Missing file: {vertices_csv}")
        return False
    
    with open(vertices_csv, "r", encoding="utf-8") as v_file:
        reader = csv.reader(v_file)
        headers = next(reader, None)
        if headers != ["id", "type", "name"]:
            logging.error(f"Incorrect header in {vertices_csv}: {headers}")
            return False
        
        for row in reader:
            if len(row) != 3:
                logging.error(f"Malformed row in {vertices_csv}: {row}")
                return False
            nodes.add(row[0])
    
    # Verify edges.csv
    if not os.path.exists(edges_csv):
        logging.error(f"Missing file: {edges_csv}")
        return False
    
    with open(edges_csv, "r", encoding="utf-8") as e_file:
        reader = csv.reader(e_file)
        headers = next(reader, None)
        if headers != ["source_id", "target_id", "relationship"]:
            logging.error(f"Incorrect header in {edges_csv}: {headers}")
            return False
        
        for row in reader:
            if len(row) != 3:
                logging.error(f"Malformed row in {edges_csv}: {row}")
                return False
            edges.append((row[0], row[1]))
    
    # Verify all edges reference valid nodes
    for source, target in edges:
        if source not in nodes:
            logging.error(f"Edge reference error: {source} not found in {vertices_csv}")
            return False
        if target not in nodes:
            logging.error(f"Edge reference error: {target} not found in {vertices_csv}")
            return False
    
    logging.info(f"Verification passed for: {vertices_csv} and {edges_csv}")
    return True

def verify_all_csv():
    """Verifies all ontology CSV files in the preprocessing directory."""
    all_passed = True
    
    for ontology_name in os.listdir(PREPROCESS_DIR):
        ontology_path = os.path.join(PREPROCESS_DIR, ontology_name)
        
        if not os.path.isdir(ontology_path):
            continue
        
        logging.info(f"Verifying ontology: {ontology_name}")
        
        # Find all unique RDF-based CSV file pairs
        rdf_files = set()
        for file in os.listdir(ontology_path):
            if file.endswith("_vertices.csv"):
                rdf_files.add(file.replace("_vertices.csv", ""))
        
        for rdf_base in rdf_files:
            vertices_csv = os.path.join(ontology_path, f"{rdf_base}_vertices.csv")
            edges_csv = os.path.join(ontology_path, f"{rdf_base}_edges.csv")
            
            if not verify_csv_structure(vertices_csv, edges_csv):
                all_passed = False
    
    if all_passed:
        logging.info("All CSV files passed verification.")
    else:
        logging.warning("Some CSV files failed verification. Check logs for details.")
    
if __name__ == "__main__":
    verify_all_csv()
