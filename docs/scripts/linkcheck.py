import subprocess
from pathlib import Path

# Define folders you want to skip entirely
IGNORED_DIRS = {"node_modules", "_book", ".git"}

# Find all markdown files, filtering out ignored directories at any level
md_files = [
    p for p in Path().resolve().glob("**/*.md")
    if not any(ignored in p.parts for ignored in IGNORED_DIRS)
]

for file_path in md_files:
    # Pass as a list, remove shell=True to prevent injection.
    # Set cwd to file_path.parent so relative links inside the markdown file resolve correctly.
    result = subprocess.run(
        ["npx", "markdown-link-check", file_path.name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,  # Automatically handles decoding to string, skipping .decode()
        cwd=file_path.parent
    )
    
    # Clean up output lines
    lines = result.stdout.replace("\r", "").split("\n")
    
    # Filter lines
    filtered_lines = [
        line for line in lines 
        if ("FILE: " in line or " → Status: " in line) and " → Status: 429" not in line
    ]
    
    # Clean printing
    for line in filtered_lines:
        print(line)
