import os
import json
import re

# Define the directories
output_dir = "output"
debug_dir = "debug"
debug_file = "RDFS1"
rerun_list_file = "files_to_rerun.txt"

def analyze_parsed_files(output_dir, debug_dir, debug_file):
    """
    Analyze the output directory for .pdf.jsonld files and their corresponding .png files, check for failures,
    compare page counts, and ensure proper source distribution.
    """
    # Ensure the debug directory exists
    os.makedirs(debug_dir, exist_ok=True)

    # Dictionary to avoid duplicate entries
    debug_files_status = {}

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

                # Initialize status flags
                graph_empty = False
                no_png = len(png_files) == 0
                invalid_sources = False

                # Check if @graph is empty
                if "@graph" in data and not data["@graph"]:
                    graph_empty = True

                # Validate sources per page
                sources = []
                if not no_png and "@graph" in data and isinstance(data["@graph"], list):
                    for graph_entry in data["@graph"]:
                        if "source" in graph_entry:
                            source = graph_entry["source"]
                            # Extract valid sources with page numbers
                            if isinstance(source, str) and re.search(r"\(Page \d+\)", source):
                                sources.append(source)

                    source_count = len(sources)
                    sources_per_page = source_count / len(png_files) if len(png_files) > 0 else 0
                    if sources_per_page < 0.5 or sources_per_page > 1.0:
                        invalid_sources = True

                # Log issues uniquely
                if graph_empty and file_name not in debug_files_status:
                    debug_files_status[file_name] = "@graph is empty"
                if no_png and file_name not in debug_files_status:
                    debug_files_status[file_name] = "No corresponding PNG files found"
                if invalid_sources and file_name not in debug_files_status:
                    debug_files_status[file_name] = "Invalid sources per page"

            except Exception as e:
                # Log files that fail to open or parse
                if file_name not in debug_files_status:
                    debug_files_status[file_name] = f"Failed to open/parse: {str(e)}"

    # Write unique debug information to the debug file
    debug_file_path = os.path.join(debug_dir, debug_file)
    with open(debug_file_path, "w", encoding="utf-8") as debug_f:
        debug_info = [{"file": file, "status": status} for file, status in debug_files_status.items()]
        json.dump(debug_info, debug_f, indent=4)

    print(f"Analysis complete. Debug information written to {debug_file_path}")

def create_rerun_list(debug_dir, debug_file, rerun_list_file):
    """
    Create a list of file names from the debug file for re-parsing.
    """
    debug_file_path = os.path.join(debug_dir, debug_file)
    rerun_list_path = os.path.join(debug_dir, rerun_list_file)
    rerun_files = set()

    try:
        # Load the debug file
        with open(debug_file_path, "r", encoding="utf-8") as f:
            debug_data = json.load(f)

        # Extract file names for rerun
        for entry in debug_data:
            if "file" in entry:
                rerun_files.add(entry["file"])

        # Write the rerun file list
        with open(rerun_list_path, "w", encoding="utf-8") as rerun_f:
            for file_name in rerun_files:
                rerun_f.write(file_name + "\n")

        print(f"Rerun file list created at {rerun_list_path}")

    except Exception as e:
        print(f"Failed to create rerun list: {str(e)}")

# Execute the functions
analyze_parsed_files(output_dir, debug_dir, debug_file)
create_rerun_list(debug_dir, debug_file, rerun_list_file)
