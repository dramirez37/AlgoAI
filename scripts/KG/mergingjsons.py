import os
import json
import glob

def merge_json_files(input_dir, pattern, output_file):
    merged_data = []
    # Recursively find all JSON files matching the pattern.
    file_paths = glob.glob(os.path.join(input_dir, '**', pattern), recursive=True)
    print(f"Found {len(file_paths)} files matching pattern '{pattern}'")
    for file_path in file_paths:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                # If the JSON is a list (as expected for vertices/edges), extend the merged list.
                if isinstance(data, list):
                    merged_data.extend(data)
                # Otherwise, if it's a dict, append it.
                elif isinstance(data, dict):
                    merged_data.append(data)
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
    # Write merged data to the output file.
    with open(output_file, 'w') as f_out:
        json.dump(merged_data, f_out, indent=4)
    print(f"Merged data written to: {output_file}")

def main():
    # Update this to the root folder where your preprocessing3 folder resides.
    input_dir = "/workspaces/AlgoAI/graphdb/preprocessing3"
    
    # Output file paths (you can change the location or names as needed)
    output_vertices = os.path.join(input_dir, "merged_vertices.json")
    output_edges = os.path.join(input_dir, "merged_edges.json")
    
    merge_json_files(input_dir, '*_vertices.json', output_vertices)
    merge_json_files(input_dir, '*_edges.json', output_edges)

if __name__ == "__main__":
    main()
