import google.generativeai as genai
import pandas as pd
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm
import datetime
import time
import re # Added for filename parsing
import shutil # Added for optional cleanup

# --- Configuration ---
# Load environment variables from a .env file if it exists
load_dotenv() 

API_KEY_ENV_VAR = "GOOGLEAPI" 
INPUT_DIR = Path("/workspaces/AlgoAI/B_input")
OUTPUT_DIR = Path("/workspaces/AlgoAI/B_output")
MODEL_NAME = "gemini-2.5-pro-exp-03-25" # As requested

# Iterative Save Configuration
SAVE_INTERVAL = 100  # Save results every 100 prompts
CLEANUP_BATCH_FILES = True # Set to False to keep individual batch files and subdirs

# Ensure base output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Gemini Generation Configuration (Adjust as needed)
# Temperature=0.0 aims for deterministic output, suitable for zero-shot tests
GENERATION_CONFIG = {
    "temperature": 0.0,
    # "max_output_tokens": 2048, # Optional: Set max tokens if needed
    # "top_p": 0.95,            # Optional: Adjust Nucleus sampling
    # "top_k": 40,             # Optional: Adjust Top-k sampling
}

# Safety settings (Adjust if needed, default is often BLOCK_MEDIUM_AND_ABOVE)
# Refer to Google AI documentation for details
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# API Call Settings
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# --- Helper Functions ---

def load_prompts(filepath):
    """Loads prompts from a JSONL file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    yield json.loads(line.strip())
                except json.JSONDecodeError:
                    print(f"Warning: Skipping invalid JSON line in {filepath}: {line.strip()}")
    except FileNotFoundError:
        print(f"Error: Prompt file not found at {filepath}")
        return None
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

def call_gemini_api_with_retry(model, prompt_text):
    """Calls the Gemini API with retry logic."""
    retries = 0
    while retries < MAX_RETRIES:
        try:
            # Attempt to generate content
            response = model.generate_content(prompt_text)
            
            # Check if response has text, handle potential blocks/empty responses
            if response.parts:
                 # Check if response might be blocked
                 if not response.parts[0].text and response.prompt_feedback.block_reason:
                     # print(f"Warning: Response blocked. Reason: {response.prompt_feedback.block_reason}") # Reduced verbosity
                     return None, f"Blocked: {response.prompt_feedback.block_reason}"
                 # Access text safely
                 return response.text, None
            elif response.prompt_feedback.block_reason:
                 # print(f"Warning: Response blocked. Reason: {response.prompt_feedback.block_reason}") # Reduced verbosity
                 return None, f"Blocked: {response.prompt_feedback.block_reason}"
            else:
                 # Handle cases where response might be empty without explicit block reason
                 # print("Warning: Received empty response without explicit block reason.") # Reduced verbosity
                 return None, "Empty Response"

        except Exception as e:
            retries += 1
            print(f"API Error: {e}. Retrying ({retries}/{MAX_RETRIES})...")
            if retries >= MAX_RETRIES:
                print(f"Error: Max retries reached for prompt. Skipping.")
                return None, f"API Error after retries: {e}"
            # Exponential backoff, but add jitter
            delay = (RETRY_DELAY_SECONDS * (2 ** (retries - 1))) + (time.time() % 1.0) 
            time.sleep(delay) 
    return None, "Max retries exceeded"

def save_batch(batch_results, output_subdir, batch_counter):
    """Saves a batch of results to a Parquet file."""
    if not batch_results:
        return
    try:
        batch_df = pd.DataFrame(batch_results)
        batch_filepath = output_subdir / f"batch_{batch_counter:04d}.parquet" # Padded for sorting
        batch_df.to_parquet(batch_filepath, index=False, engine='pyarrow')
        # print(f"    Saved batch {batch_counter} to {batch_filepath.name}") # Optional: Verbose logging
    except Exception as e:
        print(f"Error saving batch {batch_counter} to Parquet: {e}")

def combine_batch_files(run_output_subdir, base_output_dir, filename_stem):
    """Combines batch Parquet files into a single file."""
    combined_output_path = base_output_dir / f"{filename_stem}_combined.parquet"
    all_batch_files = sorted(list(run_output_subdir.glob("batch_*.parquet"))) # Sort ensures order

    if not all_batch_files:
        print(f"  -> No batch files found in {run_output_subdir} to combine.")
        return

    print(f"  -> Combining {len(all_batch_files)} batch files into {combined_output_path.name}...")
    try:
        # Read all batch files into a list of DataFrames
        list_of_dfs = [pd.read_parquet(f) for f in all_batch_files]
        # Concatenate them
        combined_df = pd.concat(list_of_dfs, ignore_index=True)
        # Save the combined DataFrame
        combined_df.to_parquet(combined_output_path, index=False, engine='pyarrow')
        print(f"  -> Successfully combined results saved to: {combined_output_path}")

        # Optional: Cleanup batch files and subdirectory
        if CLEANUP_BATCH_FILES:
            try:
                shutil.rmtree(run_output_subdir)
                print(f"  -> Cleaned up batch directory: {run_output_subdir}")
            except Exception as e:
                print(f"  -> Warning: Could not clean up batch directory {run_output_subdir}: {e}")

    except Exception as e:
        print(f"  -> Error combining batch files for {filename_stem}: {e}")


def process_file(input_filepath, base_output_dir, model):
    """Processes a single JSONL prompt file, saves batches, and combines them."""
    filename_stem = input_filepath.stem
    # Create a specific subdirectory for this run's temporary batch results
    run_output_subdir = base_output_dir / f".{filename_stem}_batches" # Hidden dir for batches
    run_output_subdir.mkdir(parents=True, exist_ok=True)
    
    print(f"\nProcessing file: {input_filepath.name}...")
    # print(f"  -> Saving batches to: {run_output_subdir}") # Less verbose
    
    current_batch_results = []
    prompt_generator = load_prompts(input_filepath)
    prompt_counter = 0
    batch_counter = 0

    if prompt_generator is None:
        print(f"Could not load prompts from {input_filepath.name}. Skipping.")
        return

    # Use tqdm for progress bar if available
    try:
       # Count lines efficiently without reading whole file into memory twice unnecessarily
       with open(input_filepath, 'rb') as f:
           line_count = sum(1 for _ in f)
       # Re-initialize generator after counting
       prompt_generator = load_prompts(input_filepath) 
       pbar = tqdm(prompt_generator, total=line_count, desc=f"  -> {filename_stem}")
    except Exception as e:
        print(f"tqdm not available or error counting lines ({e}). Processing without progress bar.")
        pbar = tqdm(prompt_generator, desc=f"  -> {filename_stem}") # tqdm without total

    for prompt_data in pbar:
        prompt_counter += 1
        prompt_id = prompt_data.get("prompt_id", f"L{prompt_counter}") # Use line number if ID missing
        prompt_text = prompt_data.get("prompt_text")
        strategy_category = prompt_data.get("strategy_category", "N/A")

        result_data = {
            'prompt_id': prompt_id,
            'strategy_category': strategy_category,
            'prompt_text': prompt_text,
            'model_name_used': MODEL_NAME,
            'timestamp': datetime.datetime.now().isoformat(),
            'response_text': None,
            'error_message': None
        }

        if not prompt_text:
            # print(f"Warning: Skipping prompt with empty text (ID: {prompt_id}).") # Less verbose
            result_data['error_message'] = "Empty prompt text"
            current_batch_results.append(result_data)
        else:
            response_text, error_msg = call_gemini_api_with_retry(model, prompt_text)
            result_data['response_text'] = response_text
            result_data['error_message'] = error_msg
            current_batch_results.append(result_data)
        
        # Check if it's time to save a batch
        if prompt_counter % SAVE_INTERVAL == 0 and current_batch_results:
            save_batch(current_batch_results, run_output_subdir, batch_counter)
            batch_counter += 1
            current_batch_results = [] # Reset batch list

        # Optional: Add a small delay to avoid hitting rate limits too quickly
        # time.sleep(0.05) 

    # Save any remaining results after the loop finishes
    if current_batch_results:
        save_batch(current_batch_results, run_output_subdir, batch_counter)
        # print(f"  -> Saved final batch {batch_counter}.") # Less verbose
    
    print(f"  -> Finished generating responses for {input_filepath.name}.")
    
    # --- Combine batch files for this run ---
    combine_batch_files(run_output_subdir, base_output_dir, filename_stem)


def combine_results_by_category(output_dir):
    """Combines results from different difficulty files into category summaries."""
    print("\nCombining results by strategy category...")
    combined_files = list(output_dir.glob("*_combined.parquet"))
    
    if not combined_files:
        print("No combined files found to aggregate by category.")
        return

    category_data = {} # {category_name: [list_of_dfs]}

    # Regex to parse category and difficulty (adjust if needed)
    # Assumes filenames like: prompts_{category_short}_{difficulty}_combined.parquet
    # Example: prompts_fa_easy_combined.parquet -> category='fa', difficulty='easy'
    # Example: prompts_TechnicalAnalysis_medium_combined.parquet -> category='TechnicalAnalysis', difficulty='medium'
    pattern = re.compile(r"prompts_([a-zA-Z0-9]+)_([a-zA-Z]+)_combined\.parquet")

    print("Identifying categories from combined files...")
    for f in combined_files:
        match = pattern.match(f.name)
        if match:
            category_short = match.group(1)
            # Map short code to full name if needed (example)
            category_name = {
                'fa': 'Fundamental_Analysis', 
                'ta': 'Technical_Analysis',
                 # Add other mappings here
            }.get(category_short.lower(), category_short) # Default to short code if no map
            
            difficulty = match.group(2)
            print(f"  - Found: {f.name} (Category: {category_name}, Difficulty: {difficulty})")

            try:
                df = pd.read_parquet(f)
                if category_name not in category_data:
                    category_data[category_name] = []
                category_data[category_name].append(df)
            except Exception as e:
                print(f"  - Warning: Could not read or process file {f.name}: {e}")
        else:
            print(f"  - Warning: Could not parse category/difficulty from filename: {f.name}")

    if not category_data:
        print("No data grouped by category.")
        return
        
    print("\nAggregating difficulties for each category...")
    for category, dfs in category_data.items():
        if dfs:
            print(f"  - Combining {len(dfs)} file(s) for category: {category}")
            try:
                final_category_df = pd.concat(dfs, ignore_index=True)
                final_output_path = output_dir / f"{category}_ALL_results.parquet"
                final_category_df.to_parquet(final_output_path, index=False, engine='pyarrow')
                print(f"  -> Saved final results for {category} to: {final_output_path.name}")
            except Exception as e:
                print(f"  -> Error combining or saving final results for category {category}: {e}")
        else:
             print(f"  - No valid dataframes found for category: {category}")


# --- Main Execution ---

if __name__ == "__main__":
    start_time = time.time()
    print("Starting Zero-Shot Benchmark Script (Iterative Save & Combine)...")
    
    api_key = os.getenv(API_KEY_ENV_VAR)
    if not api_key:
        print(f"Error: API Key environment variable '{API_KEY_ENV_VAR}' not set.")
        exit(1)
        
    try:
        # Configure the Google AI client
        genai.configure(api_key=api_key)
        
        # Initialize the Generative Model
        model = genai.GenerativeModel(
            MODEL_NAME,
            generation_config=GENERATION_CONFIG,
            safety_settings=SAFETY_SETTINGS 
        )
        print(f"Successfully initialized model: {MODEL_NAME}")
        
    except Exception as e:
        print(f"Error initializing Google AI Model: {e}")
        exit(1)

    print(f"Input directory: {INPUT_DIR}")
    print(f"Output directory (for combined & final files): {OUTPUT_DIR}")
    print(f"Save interval: {SAVE_INTERVAL} prompts per batch file.")

    # Find all .jsonl files in the input directory
    prompt_files = sorted(list(INPUT_DIR.glob("*.jsonl"))) # Sort for consistent processing order

    if not prompt_files:
        print(f"Error: No .jsonl files found in {INPUT_DIR}")
        exit(1)
        
    print(f"\nFound {len(prompt_files)} prompt files to process: {[f.name for f in prompt_files]}")

    # --- Process each input file (generate responses, save batches, combine batches) ---
    for filepath in prompt_files:
        process_file(filepath, OUTPUT_DIR, model)

    # --- Combine results by strategy category ---
    combine_results_by_category(OUTPUT_DIR)
    
    end_time = time.time()
    total_time = end_time - start_time
    print(f"\nBenchmark Script Finished. Total execution time: {total_time:.2f} seconds.")
    print(f"Combined difficulty files (*_combined.parquet) and final category files (*_ALL_results.parquet) are in {OUTPUT_DIR}")