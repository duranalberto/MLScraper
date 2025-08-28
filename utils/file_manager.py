import json
import asyncio
import os
from pathlib import Path
from typing import Union, List, Dict

# Set up base path using Pathlib for cross-platform compatibility
DATA_PATH = Path("./data")

def ensure_data_dir():
    """Ensures the target directory exists before writing."""
    DATA_PATH.mkdir(parents=True, exist_ok=True)

def write_in_file_sync(file_name: str, content: str):
    """Synchronous write with directory and file creation fallback."""
    if not file_name or content is None:
        return
    
    ensure_data_dir()
    file_path = DATA_PATH / file_name
    
    # 'w' mode automatically creates the file if it doesn't exist
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)

async def write_in_file(file_name: str, content: str):
    """
    Asynchronous write. 
    Note: Standard 'open' is blocking. In a real production environment, 
    consider 'pip install aiofiles'. Here we use run_in_executor for true async.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, write_in_file_sync, file_name, content)

def read_json_file(file_name: str) -> Union[List, Dict]:
    """Reads JSON with fallback for missing files and invalid JSON."""
    file_path = DATA_PATH / file_name
    
    if not file_path.exists():
        # Optional: Initialize the file with an empty list if you want it created immediately
        # write_in_file_sync(file_name, "[]")
        return []

    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except json.JSONDecodeError:
        print(f"Error: {file_name} contains invalid JSON.")
        return []
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return []

