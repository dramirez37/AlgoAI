import dropbox

# Replace 'YOUR_ACCESS_TOKEN' with your Dropbox access token
ACCESS_TOKEN = 'TEST'

def connect_to_dropbox():
    """Connect to Dropbox using the provided access token."""
    try:
        dbx = dropbox.Dropbox(ACCESS_TOKEN)
        print("Connected to Dropbox!")
        return dbx
    except Exception as e:
        print(f"Error connecting to Dropbox: {e}")
        return None

def list_folder_contents(dbx, path=''):
    """
    Recursively list all files and folders in the given Dropbox folder.

    Args:
        dbx (dropbox.Dropbox): Authenticated Dropbox instance.
        path (str): Path to the folder to list. Defaults to root ('').
    """
    try:
        # List entries in the folder
        entries = dbx.files_list_folder(path).entries
        for entry in entries:
            if isinstance(entry, dropbox.files.FolderMetadata):
                print(f"📁 Folder: {entry.path_display}")
                # Recursively list contents of the folder
                list_folder_contents(dbx, entry.path_display)
            elif isinstance(entry, dropbox.files.FileMetadata):
                print(f"📄 File: {entry.path_display}")
    except dropbox.exceptions.ApiError as e:
        print(f"Error accessing {path}: {e}")

if __name__ == "__main__":
    # Connect to Dropbox
    dbx_instance = connect_to_dropbox()
    if dbx_instance:
        print("\nNavigating Dropbox root folder...\n")
        # Start from the root folder
        list_folder_contents(dbx_instance)
