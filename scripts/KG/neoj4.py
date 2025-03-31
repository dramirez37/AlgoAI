from py2neo import Graph
import os
import rdflib
from rdflib import Graph as RDFGraph

# Neo4j connection details
neo4j_uri = "neo4j+s://864ac9ae.databases.neo4j.io"
neo4j_username = "neo4j"
neo4j_password = "1rp0cEUQRSuwbKfK5GlT3zmjP_CcsdnDQoxdeqHI6_4"

# Files and predicates to ignore
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

# Find RDF files recursively
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

# Filter RDF triples based on namespaces and predicates
def filter_rdf_graph(rdf_graph):
    filtered_graph = RDFGraph()
    
    # Add relevant namespaces
    for prefix, namespace in rdf_graph.namespaces():
        filtered_graph.bind(prefix, namespace)
    
    # Filter triples
    for s, p, o in rdf_graph:
        # Skip if predicate is in ignored namespaces
        skip = False
        p_str = str(p)
        
        for ns in IGNORED_NAMESPACES:
            if p_str.startswith(ns):
                skip = True
                break
        
        # Skip if predicate contains ignored terms
        for term in IGNORED_PREDICATES:
            if term in p_str:
                skip = True
                break
        
        # Keep if predicate is in allowed properties
        if p_str in ADDITIONAL_ALLOWED_PROPERTIES:
            skip = False
        
        # Keep if predicate local name is in allowed local property names
        for name in ALLOWED_LOCAL_PROPERTY_NAMES:
            if p_str.endswith(name):
                skip = False
                break
        
        if not skip:
            filtered_graph.add((s, p, o))
    
    return filtered_graph

# Connect to Neo4j
graph = Graph(neo4j_uri, auth=(neo4j_username, neo4j_password))

# Check if n10s is installed
try:
    graph.run("CALL n10s.version()")
    print("neosemantics (n10s) plugin is installed")
except Exception:
    print("neosemantics plugin is not available - check your Neo4j Aura instance")
    exit(1)

# Drop any existing configuration and data
try:
    graph.run("MATCH (n) DETACH DELETE n")
    graph.run("CALL n10s.graphconfig.drop()")
    print("Dropped existing graph config and data")
except Exception:
    print("No existing graph config to drop")

# Initialize fresh graph configuration
graph.run("""
CALL n10s.graphconfig.init({
  handleVocabUris: 'MAP',
  handleMultival: 'ARRAY',
  keepLangTag: true,
  handleRDFTypes: 'NODES'
})
""")
print("Initialized neosemantics graph configuration")

# Path to FIBO directory
fibo_directory = "/workspaces/AlgoAI/graphdb/fibo"

# Get all RDF files
rdf_files = find_rdf_files(fibo_directory)
print(f"Found {len(rdf_files)} RDF files")

# Import each file
success_count = 0
failed_files = []

for i, file_path in enumerate(rdf_files):
    try:
        print(f"Processing {i+1}/{len(rdf_files)}: {file_path}")
        
        # Parse RDF file
        rdf_graph = RDFGraph()
        rdf_graph.parse(file_path, format="xml")
        
        # Filter the graph
        filtered_graph = filter_rdf_graph(rdf_graph)
        
        # Serialize to string
        rdf_content = filtered_graph.serialize(format="xml")
        
        # Import to Neo4j
        query = """
        CALL n10s.rdf.import.inline($content, $format)
        """
        result = graph.run(query, parameters={"content": rdf_content, "format": "RDF/XML"}).data()
        
        # Print import stats
        if result and len(result) > 0:
            print(f"  Triples imported: {result[0].get('triplesLoaded', 0)}")
            success_count += 1
        
    except Exception as e:
        print(f"Error importing {file_path}: {str(e)}")
        failed_files.append(file_path)

# Create indexes for better performance
try:
    graph.run("CREATE INDEX n10s_uri_index FOR (r:Resource) ON (r.uri)")
    print("Created index on Resource.uri")
except Exception as e:
    print(f"Error creating index: {str(e)}")

# Print summary
print(f"\nImported {success_count} out of {len(rdf_files)} files")
if failed_files:
    print(f"Failed to import {len(failed_files)} files")

# Print node statistics
result = graph.run("""
MATCH (n)
RETURN labels(n) as label, count(*) as count
ORDER BY count DESC
LIMIT 10
""").data()

print("\nTop 10 node labels:")
for row in result:
    print(f"{row['label']}: {row['count']}")

print("\nFIBO ontology has been loaded!")