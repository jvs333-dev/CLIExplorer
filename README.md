```
 _____  _     _____ _____           _                     
/  __ \| |   |_   _|  ___|         | |                    
| /  \/| |     | | | |____  ___ __ | | ___  _ __ ___ _ __ 
| |    | |     | | |  __\ \/ / '_ \| |/ _ \| '__/ _ \ '__|
| \__/\| |_____| |_| |___>  <| |_) | | (_) | | |  __/ |   
 \____/\_____/\___/\____/_/\_\ .__/|_|\___/|_|  \___|_|   
                             | |                          
                             |_|    v 1.1.0 (beta)           
```

CLIExplorer is a lightweight terminal-based file browser for quick navigation and viewing file details directly from the command line.

## Version
**1.1.0** (beta)  
Released: 2026-05-15  
Type: Major update with improved UI and bug fixes

## Features
- Browse files and folders in a clean table format
- Sort by name, date, extension, or size
- Show file icons and descriptions via JSON configuration
- Open files or navigate folders directly from the CLI

## Known Issues
- **Right Border Rendering Bug**: The right border of the UI may not render correctly in certain terminal situations. This issue will be fixed in the next version.

## Requirements
- Python 3.6+

## Usage
1. Download the files
2. Run with optional arguments:
```bash
python navitest.py [--s START_DIR] [--d DESCRIPTIONS_PATH] [--i ICONS_PATH]
```
   - `--s` – Starting directory (default: script directory)
   - `--d` – Path to descriptions.json (default: script directory)
   - `--i` – Path to icons.json (default: script directory)

3. Commands in the terminal:
   - `open <number>` – Open the selected file/folder
   - `create <name>` – Create a new file
   - `delete <number>` – Delete a file/folder
   - `resize <width>` – Resize the name column (or `auto`/`max`)
   - `sort <mode>` – Change sorting
   - `rename <number>` – Rename a file
   - `quit` – Exit the program

## License
MIT License.
