import os
import json
import re

# Define the directories
output_dir = "output"
debug_dir = "debug"
debug_file = "RDFS1"

def analyze_parsed_files(output_dir, debug_dir, debug_file):
    """
    Analyze the output directory for .pdf.jsonld files and their corresponding .png files, check for failures,
    compare page counts, and ensure proper source distribution.
    """
    # Ensure the debug directory exists
    os.makedirs(debug_dir, exist_ok=True)

    # List to store debug information
    debug_info = []

    # Iterate through files in the output directory
    for file_name in os.listdir(output_dir):
        if file_name.endswith(".pdf.jsonld"):
            file_path = os.path.join(output_dir, file_name)
            root_name = file_name.replace(".pdf.jsonld", "")  # Extract the root name without extension

            # Find matching .png files
            png_files = [f for f in os.listdir(output_dir) if f.startswith(root_name) and f.endswith(".png")]

            try:
                # Open and parse the JSON-LD file
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Check if @graph is empty
                if "@graph" in data and not data["@graph"]:
                    debug_info.append({"file": file_name, "status": "@graph is empty"})

                # Count the number of .png files (pages)
                page_count = len(png_files)
                if page_count == 0:
                    debug_info.append({"file": file_name, "status": "No corresponding PNG files found"})
                    continue

                # Validate sources per page
                sources = []
                if "@graph" in data and isinstance(data["@graph"], list):
                    for graph_entry in data["@graph"]:
                        if "source" in graph_entry:
                            source = graph_entry["source"]
                            # Extract valid sources with page numbers
                            if isinstance(source, str) and re.search(r"\(Page \d+\)", source):
                                sources.append(source)

                source_count = len(sources)
                sources_per_page = source_count / page_count if page_count > 0 else 0
                if sources_per_page < 0.5 or sources_per_page > 1.0:
                    debug_info.append({
                        "file": file_name,
                        "status": "Invalid sources per page",
                        "pages": page_count,
                        "sources": source_count,
                        "sources_per_page": sources_per_page
                    })

            except Exception as e:
                # Log files that fail to open or parse
                debug_info.append({"file": file_name, "status": "Failed to open/parse", "error": str(e)})

    # Write debug information to the debug file
    debug_file_path = os.path.join(debug_dir, debug_file)
    with open(debug_file_path, "w", encoding="utf-8") as debug_f:
        json.dump(debug_info, debug_f, indent=4)

    print(f"Analysis complete. Debug information written to {debug_file_path}")

# Execute the function
analyze_parsed_files(output_dir, debug_dir, debug_file)
