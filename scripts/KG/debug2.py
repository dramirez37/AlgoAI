import os
import fitz  # PyMuPDF

# Input directories
input_dir = "FinPapers"
rerun_file = "debug/files_to_rerun.txt"

# Output directory
output_dir = "output2"
os.makedirs(output_dir, exist_ok=True)

# Scale factors for ~600 DPI (600/72 ≈ 8.33)
zoom_x = 8.33
zoom_y = 8.33
matrix = fitz.Matrix(zoom_x, zoom_y)

def render_pdf_at_600dpi(pdf_path, output_dir):
    doc = fitz.open(pdf_path)
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    for page_num, page in enumerate(doc):
        image_name = f"{base_name}_page_{page_num + 1}.png"
        image_path = os.path.join(output_dir, image_name)
        pix = page.get_pixmap(matrix=matrix)
        pix.save(image_path)
    doc.close()

# Read the list of PDFs to re-run
with open(rerun_file, "r") as f:
    pdf_files = [line.strip() for line in f if line.strip()]

# Process each PDF and generate high-res images
for pdf_name in pdf_files:
    pdf_path = os.path.join(input_dir, pdf_name)
    if not os.path.exists(pdf_path):
        print(f"PDF not found: {pdf_path}")
        continue
    
    print(f"Processing {pdf_name} at 600 DPI...")
    render_pdf_at_600dpi(pdf_path, output_dir)

print("Reprocessing complete.")
