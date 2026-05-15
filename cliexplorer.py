from pathlib import Path
from datetime import datetime
import json
import os
import sys
import send2trash
import curses
import argparse


# ==========================
# Constants & Logo
# ==========================

LOGO = r"""
 _____  _     _____ _____           _                     
/  __ \│ │   │_   _│  ___│         │ │                    
│ /  \/│ │     │ │ │ │____  ___ __ │ │ ___  _ __ ___ _ __ 
│ │    │ │     │ │ │  __\ \/ / '_ \│ │/ _ \│ '__/ _ \ '__│
│ \__/\│ │_____│ │_│ │___>  <│ │_) │ │ (_) │ │ │  __/ │   
\_____/\_____/\___/\____/_/\_\ .__/│_│\___/│_│  \___│_│   
                             │ │                          
                             │_│    v 1.1.0 (beta)        
"""

# Allowed characters for the command input field
ALLOWED_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._-"

# Maximum length of the typed command string
MAX_TYPED_LEN = 86

# Available commands shown in autocomplete
COMMAND_NAMES = ["open", "create", "delete", "resize", "sort", "rename", "quit"]


# ==========================
# Sorting & File Utilities
# ==========================

def parse_sort(sort: str):
    """
    Parse a sort string into (folders_first, mode, descending).

    Sort string format: <folders><mode><order>
      folders : 's' = folders first  |  'n' = no preference
      mode    : 'n' = name  |  't' = time  |  'e' = extension  |  's' = size
      order   : 'l' = descending  |  'h' = ascending
    """
    folders_first = sort[0] == "s"
    mode = {"n": 1, "t": 2, "e": 3, "s": 4}.get(sort[1], 1)
    descending = sort[2] == "l"
    return folders_first, mode, descending


def sort_key(f: Path, sort: str):
    """
    Return a (group, key) tuple used when sorting directory entries.
    group = 0 for folders (when folders_first is on), 1 otherwise.
    """
    folders_first, mode, _ = parse_sort(sort)

    group = 0 if folders_first and f.is_dir() else 1

    if mode == 1:       # Sort by name
        key = f.stem.lower()
    elif mode == 2:     # Sort by last-modified time
        key = f.stat().st_mtime
    elif mode == 3:     # Sort by file extension
        key = f.suffix.lower().lstrip(".")
    elif mode == 4:     # Sort by file size
        key = f.stat().st_size
    else:
        key = f.stem.lower()

    return (group, key)


def get_files(folder: Path, sort: str, prev_folder: Path, log_msg: str, log_type: int):
    """
    Return a sorted list of entries in folder.
    Falls back to prev_folder and sets an error log on PermissionError.
    """
    try:
        files = sorted(
            folder.iterdir(),
            key=lambda x: sort_key(x, sort),
            reverse=parse_sort(sort)[2],
        )
    except PermissionError:
        folder = prev_folder
        files = sorted(
            folder.iterdir(),
            key=lambda x: sort_key(x, sort),
            reverse=parse_sort(sort)[2],
        )
        log_msg, log_type = "Access denied.", 1

    return files, folder, log_msg, log_type


def sizeof_fmt(num, suffix="B"):
    """Convert a byte count to a human-readable string (e.g. 1.23 MB)."""
    if num == -1:
        return "N/A"
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1024.0:
            return f"{num:.2f} {unit}{suffix}"
        num /= 1024.0
    return f"{num:.2f} Y{suffix}"


def console_too_small():
    """
    Warn the user that the console window is too small.
    Uses a Windows MessageBox when available; falls back to a plain print.
    """
    msg = "Your console is too small!\nPlease resize your console."
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "CLIExplorer", 0x30)
            return
        except Exception:
            pass
    # Fallback for non-Windows or if ctypes fails
    print(msg, file=sys.stderr)


# ==========================
# Configuration & JSON Loading
# ==========================

def load_files(args):
    """
    Resolve paths for icons.json, descriptions.json, and the start directory.

    Priority:
      1. CLI arguments (--i, --d, --s)
      2. config.txt next to the script
      3. Defaults: script directory for all three
    """
    script_dir = Path(__file__).resolve().parent
    config_file = script_dir / "config.txt"

    # Persist all three paths when all CLI args are supplied
    if args.i and args.d and args.s:
        with open(config_file, "w", encoding="utf-8") as f:
            f.write(f"{args.i}\n{args.d}\n{args.s}\n")

    # Persist only the start path when only --s is supplied
    elif args.s and config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        while len(lines) < 3:
            lines.append("\n")
        lines[2] = f"{args.s}\n"
        with open(config_file, "w", encoding="utf-8") as f:
            f.writelines(lines)

    # Load saved paths from config if it exists
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        if len(lines) >= 3:
            args.i, args.d, args.s = lines[:3]
        else:
            args.i = script_dir / "icons.json"
            args.d = script_dir / "descriptions.json"
            args.s = str(script_dir)
    else:
        args.i = script_dir / "icons.json"
        args.d = script_dir / "descriptions.json"
        args.s = str(script_dir)

    # Load icons mapping  {".ext": "emoji"}
    try:
        with Path(args.i).open("r", encoding="utf-8") as f:
            icons = json.load(f)
    except Exception:
        icons = {}

    # Load descriptions mapping  {".ext": "human-readable label"}
    try:
        with Path(args.d).open("r", encoding="utf-8") as f:
            descriptions = json.load(f)
    except Exception:
        descriptions = {}

    return icons, descriptions


# ==========================
# Rendering (curses)
# ==========================

def render(
    folder: Path,
    icons: dict,
    descriptions: dict,
    name_width: int,
    selected: int,
    stdscr: curses.window,
    files: list,
    start: int,
    typed: str,
    log_msg: str,
    log_type: int,
):
    """
    Draw the full file-explorer UI for the current frame.
    Returns the updated (start, typed) values after layout adjustments.
    """
    max_height, max_width = stdscr.getmaxyx()

    # Require at least 12 rows to render anything meaningful
    if max_height <= 11:
        stdscr.clear()
        stdscr.refresh()
        console_too_small()
        return start, typed

    # Number of file rows that fit between the header and footer
    visible_height = max_height - 11

    # ---------------------
    # Scroll position logic
    # ---------------------
    if selected < start + 1:
        start = selected - 1
    elif selected > start + visible_height:
        start = selected - visible_height
    start = max(0, min(start, max(0, len(files) - visible_height)))

    end = start + visible_height
    files_to_show = files[start:end]

    # Pad with None so every row in the visible area is always rendered
    if len(files_to_show) != visible_height:
        files_to_show += [None] * (visible_height - len(files_to_show))

    # ---------------------
    # Column width calculation
    # ---------------------
    type_width = max(max((len(f.suffix if f.is_file() else "fld") for f in files), default=3), 4)
    des_width = max(max((len(descriptions.get(f.suffix, f"{f.suffix.lstrip('.').upper()} file")if f.suffix.lstrip(".")else ("File" if f.is_file() else "File folder"))for f in files),default=11),11)
    no_width = max(len(str(len(files))), 2)

    # name_width sentinel values:  -1 = auto (fit longest name)  |  -2 = stretch to terminal
    if name_width == -1:
        name_width = max((len(f.name) for f in files), default=14)
    elif name_width == -2:
        name_width = max_width - 46 + no_width + type_width + des_width

    # Shrink name column until the table fits the terminal width
    table_width = 46 + no_width + name_width + type_width + des_width
    while table_width + 2 > max_width and name_width > 4:
        name_width -= 1
        table_width = 46 + no_width + name_width + type_width + des_width

    # If it still doesn't fit, bail out with a warning
    if table_width + 2 > max_width:
        stdscr.clear()
        stdscr.refresh()
        console_too_small()
        return start, typed

    # Truncate current path if it is wider than the table
    path = str(folder.absolute())
    if len(path) > table_width - 2:
        path = "..." + path[-(table_width - 5):]

    # ---------------------
    # Autocomplete prediction
    # ---------------------
    prediction = ""
    last_word = typed.split(" ")[-1] if typed.split(" ")[-1] else " "
    for cmd in COMMAND_NAMES:
        if last_word == cmd[: len(last_word)]:
            prediction = cmd
            break

    # Clamp typed string so the log message always fits on the same row
    typed = typed[: table_width - (len(log_msg) + 19)]

    # ---------------------
    # Draw header
    # ---------------------
    stdscr.clear()

    stdscr.addstr(0, 0, f"┌{'─' * table_width}┐")
    stdscr.addstr(1, 0, f"│ {path:^{table_width - 2}} │")

    in_width = len(f"{'CMD: ' + typed + chr(0x2588):<{table_width - (len(log_msg) + 6)}}")
    stdscr.addstr(2, 0, f"├{'─' * in_width}┬{'─' * (len(log_msg) + 5)}┤")
    stdscr.addstr(3, 0, f"│{'CMD: ' + typed + chr(0x2588):<{table_width - (len(log_msg) + 6)}}│LOG: ")

    # Autocomplete hint shown in blue, right-aligned inside the CMD field
    stdscr.addstr(
        3,
        table_width - (len(log_msg) + 11),
        f"{prediction:>{(table_width - (len(log_msg) + 6)) - (table_width - (len(log_msg) + 11))}}",
        curses.color_pair(4),
    )

    # Log message shown in its colour (1=red, 2=green, 3=yellow)
    stdscr.addstr(3, (table_width - len(log_msg)) + 1, log_msg, curses.color_pair(log_type))
    stdscr.addstr(3, table_width + 1, "│")

    # Column header row
    stdscr.addstr(
        4,
        0,
        f"├{'─' * (no_width + 2)}┬{'─' * (name_width + 5)}┬{'─' * 18}┬{'─' * 12}┬{'─' * (type_width + 2)}┬{'─' * (des_width + 2)}┤",
    )

    # Fix the junction character where the CMD/LOG divider meets the column header
    junction = "┴" if stdscr.instr(4, in_width + 1, 1).decode() == "─" else "┼"
    stdscr.addstr(4, in_width + 1, junction)

    stdscr.addstr(
        5,
        0,
        f"│{'No':^{no_width + 2}}│{'Name':^{name_width + 5}}│    Last edit     │    Size    │{'Type':^{type_width + 2}}│ {'Description':^{des_width}} │",
    )
    stdscr.addstr(
        6,
        0,
        f"├{'─' * (no_width + 2)}┼{'─' * (name_width + 5)}┼{'─' * 18}┼{'─' * 12}┼{'─' * (type_width + 2)}┼{'─' * (des_width + 2)}┤",
    )

    # ---------------------
    # Draw file rows
    # ---------------------
    for idx, f in enumerate(files_to_show, start=start + 1):
        if f:
            icon     = icons.get(f.suffix, "📃") if f.is_file() else "📁"
            name     = (f.name[: name_width - 3] + "...") if len(f.name) > name_width else f.name
            mtime    = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d-%m-%Y %H:%M")
            size_str = sizeof_fmt(f.stat().st_size) if f.is_file() else "N/A"
            type_str = f.suffix if f.is_file() else "fld"
            des_str  = (
                descriptions.get(f.suffix, f"{f.suffix.lstrip('.').upper()} file")
                if f.suffix.lstrip(".")
                else ("File" if f.is_file() else "File folder")
            )

            row_y = idx - start + 6

            if idx == selected:
                # Highlighted (selected) row — rendered as reversed video
                stdscr.addstr(
                    row_y, 1,
                    f" {idx:0>{no_width}}   {icon} {name:<{name_width}}   {mtime}   {size_str:<10}   {type_str:<{type_width}}   {des_str:<{des_width}} ",
                    curses.A_REVERSE,
                )
                # Restore the border characters that A_REVERSE would overwrite
                stdscr.addstr(row_y, 0, "│")
                stdscr.addstr(row_y, table_width + 1, "│")
            else:
                stdscr.addstr(
                    row_y, 0,
                    f"│ {idx:0>{no_width}} │ {icon} {name:<{name_width}} │ {mtime} │ {size_str:<10} │ {type_str:<{type_width}} │ {des_str:<{des_width}} │",
                )
        else:
            # Empty padding row (no file entry)
            stdscr.addstr(
                idx - start + 6, 0,
                f"│ {' ' * no_width} │   {' ' * name_width}  │ {' ' * 16} │ {' ' * 10} │ {' ' * type_width} │ {' ' * des_width} │",
            )

    # ---------------------
    # Draw footer
    # ---------------------
    footer_y = min(visible_height, len(files_to_show)) + 7
    stdscr.addstr(
        footer_y, 0,
        f"├{'─' * (no_width + 2)}┴{'─' * (name_width + 5)}┴{'─' * 18}┴{'─' * 12}┴{'─' * (type_width + 2)}┴{'─' * (des_width + 2)}┤",
    )
    info_text = (
        "CLIExplorer v1.1.0  |  visit https://github.com/jvs333-dev/CLIExplorer for more info."
        if table_width >= 90
        else "CLIExplorer v1.1.0"
    )
    stdscr.addstr(footer_y + 1, 0, f"│{info_text:^{table_width}}│")
    stdscr.addstr(footer_y + 2, 0, f"└{'─' * table_width}┘")

    stdscr.refresh()
    return start, typed


# ==========================
# Main Program
# ==========================

def main(stdscr: curses.window):

    # --------------------------
    # Argument parsing
    # --------------------------
    parser = argparse.ArgumentParser(description="CLIExplorer – terminal file browser")
    parser.add_argument("--s", type=str, help="Starting directory path")
    parser.add_argument("--d", type=str, help="Path to descriptions.json")
    parser.add_argument("--i", type=str, help="Path to icons.json")
    args = parser.parse_args()

    # --------------------------
    # Load configuration & JSON data
    # --------------------------
    icons, descriptions = load_files(args)
    folder = Path(args.s)

    # --------------------------
    # State variables
    # --------------------------
    sort       = "snh"   # Default: folders first, sort by name, ascending
    name_width = -2      # -2 = stretch name column to fill terminal width
    selected   = 1       # 1-based index of the highlighted row
    start      = 0       # Index of the first visible row (scroll offset)
    typed      = ""      # Current command input buffer
    log_msg    = "" if (icons and descriptions) else "Warning: error with icons or descriptions file."
    log_type   = 3       # 3 = yellow warning colour

    files = sorted(
        folder.iterdir(),
        key=lambda x: sort_key(x, sort),
        reverse=parse_sort(sort)[2],
    )

    # --------------------------
    # Command handler functions
    # Each receives (cmd, folder, file, name_width, sort) and returns
    # (new_folder, new_name_width, log_msg, log_type).
    # --------------------------

    def cmd_open(cmd: str, folder: Path, file: Path, name_width: int, sort: str):
        """
        open .        – go up to the parent directory
        open <path>   – navigate into a directory or launch a file
        open          – (no argument) open the currently selected entry
        """
        target = Path(cmd) if cmd.strip() else file

        if cmd.strip() == ".":
            return folder.parent, name_width, "Changed to parent directory.", 2

        if target.is_file():
            try:
                os.startfile(target)   # Windows; on other OS use subprocess
            except AttributeError:
                import subprocess
                subprocess.Popen(["xdg-open", str(target)])
            except Exception as e:
                return folder, name_width, f"Error opening {target.name}: {e}", 1
            return folder, name_width, f"Opened {target.name}.", 2

        if target.is_dir():
            return target, name_width, f"Entered {target.name}.", 2

        return folder, name_width, f"Not found: {cmd}", 1


    def cmd_create(cmd: str, folder: Path, file: Path, name_width: int, sort: str):
        """
        create fld <name>   – create a new directory
        create <name>       – create a new empty file
        """
        parts = cmd.split(" ", 1)

        if parts[0] == "fld":
            # Folder creation: requires a name after 'fld'
            if len(parts) < 2 or not parts[1].strip():
                return folder, name_width, "Usage: create fld <name>", 3
            new_path = folder / parts[1].strip()
            try:
                new_path.mkdir()
            except FileExistsError:
                return folder, name_width, f"{new_path.name} already exists.", 1
            except Exception as e:
                return folder, name_width, f"Error: {e}", 1
        else:
            # File creation
            if not cmd.strip():
                return folder, name_width, "Usage: create <name>", 3
            new_path = folder / cmd.strip()
            try:
                new_path.touch()
            except Exception as e:
                return folder, name_width, f"Error: {e}", 1

        return folder, name_width, f"Created {new_path.name}.", 2


    def cmd_delete(cmd: str, folder: Path, file: Path, name_width: int, sort: str):
        """
        delete .   – send the current folder to the recycle bin / trash
        delete     – send the selected file/folder to the recycle bin / trash
        """
        target = folder if cmd.strip() == "." else file

        if not target.exists():
            return folder, name_width, f"{target.name} does not exist.", 1

        try:
            send2trash.send2trash(str(target))
        except Exception as e:
            return folder, name_width, f"Error deleting {target.name}: {e}", 1

        # Navigate up if the current folder was deleted
        new_folder = target.parent if target.is_dir() else folder
        return new_folder, name_width, f"Deleted {target.name}.", 2


    def cmd_resize(cmd: str, folder: Path, file: Path, name_width: int, sort: str):
        """
        resize max    – stretch name column to terminal width
        resize auto   – fit name column to the longest filename
        resize <n>    – set name column to exactly n characters (min 13)
        """
        cmd = cmd.strip()
        if cmd == "max":
            return folder, -2, "Name column: max width.", 2
        if cmd == "auto":
            return folder, -1, "Name column: auto width.", 2
        try:
            width = int(cmd)
            if width >= 13:
                return folder, width, f"Name column: {width} chars.", 2
            return folder, name_width, "Width must be ≥ 13.", 3
        except ValueError:
            return folder, name_width, f"Invalid width: {cmd}", 3


    def cmd_sort(cmd: str, folder: Path, file: Path, name_width: int, sort: str):
        """
        sort <string>   – apply a new sort string (e.g. 'snh', 'ntl')
        See parse_sort() for the format.
        """
        cmd = cmd.strip()
        if len(cmd) == 3 and cmd[0] in "sn" and cmd[1] in "ntes" and cmd[2] in "lh":
            # Return the new sort string via a nonlocal-friendly side channel:
            # the caller (main loop) reads sort from the return value indirectly,
            # so we embed it in the log and update it in the main loop.
            return folder, name_width, f"Sort: {cmd}", 2
        return folder, name_width, f"Invalid sort string: {cmd}", 3


    def cmd_rename(cmd: str, folder: Path, file: Path, name_width: int, sort: str):
        """rename <new_name>   – rename the currently selected file or folder"""
        cmd = cmd.strip()
        if not cmd:
            return folder, name_width, "Usage: rename <new name>", 3
        try:
            file.rename(folder / cmd)
            return folder, name_width, f"Renamed to {cmd}.", 2
        except FileExistsError:
            return folder, name_width, f"{cmd} already exists.", 1
        except Exception as e:
            return folder, name_width, f"Error: {e}", 1


    def cmd_quit(*_):
        """quit   – exit CLIExplorer"""
        raise KeyboardInterrupt


    # Map command names to their handler functions
    COMMANDS = {
        "open":   cmd_open,
        "create": cmd_create,
        "delete": cmd_delete,
        "resize": cmd_resize,
        "sort":   cmd_sort,
        "rename": cmd_rename,
        "quit":   cmd_quit,
    }

    # --------------------------
    # curses initialisation
    # --------------------------
    stdscr.keypad(True)   # Enable special-key constants (arrows, etc.)
    curses.curs_set(0)    # Hide the hardware cursor

    # Colour pairs:  1=red (error)  2=green (success)  3=yellow (warning)  4=blue (hint)
    curses.init_pair(1, curses.COLOR_RED,    curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN,  curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_BLUE,   curses.COLOR_BLACK)

    # --------------------------
    # Welcome / splash screen
    # --------------------------
    stdscr.clear()
    stdscr.addstr(0, 0, "Welcome to:")
    stdscr.addstr(1, 0, LOGO)
    stdscr.addstr(11, 16, "Press any key to continue")
    stdscr.refresh()
    stdscr.getch()
    stdscr.nodelay(True)   # Non-blocking key reads from here on

    # --------------------------
    # Main event loop
    # --------------------------
    while True:
        key = stdscr.getch()

        # --- Arrow key navigation ---
        if key == curses.KEY_DOWN:
            # Move selection down, wrapping to the top
            selected = 1 if selected >= len(files) else selected + 1

        elif key == curses.KEY_UP:
            # Move selection up, wrapping to the bottom
            selected = len(files) if selected <= 1 else selected - 1

        elif key == curses.KEY_RIGHT:
            # Enter selected directory or open selected file
            prev_folder = folder
            current_file = files[selected - 1] if files else folder
            folder, name_width, log_msg, log_type = cmd_open("", folder, current_file, name_width, sort)
            files, folder, log_msg, log_type = get_files(folder, sort, prev_folder, log_msg, log_type)
            if folder != prev_folder:
                selected = 1

        elif key == curses.KEY_LEFT:
            # Navigate up to the parent directory
            prev_folder = folder
            folder, name_width, log_msg, log_type = cmd_open(".", folder, folder, name_width, sort)
            files, folder, log_msg, log_type = get_files(folder, sort, prev_folder, log_msg, log_type)
            selected = 1

        # --- Tab: autocomplete the current word ---
        elif key == 9:
            last_word = typed.split(" ")[-1]
            if last_word:
                for cmd in COMMAND_NAMES:
                    if cmd.startswith(last_word):
                        typed = typed[: -len(last_word)] + cmd + " "
                        break

        # --- Enter: execute the typed command ---
        elif key in (curses.KEY_ENTER, 10):
            parts    = typed.strip().split(" ", 1)
            cmd_name = parts[0]
            cmd_arg  = parts[1] if len(parts) > 1 else ""
            handler  = COMMANDS.get(cmd_name)

            if handler:
                prev_folder = folder
                current_file = files[selected - 1] if files else folder
                folder, name_width, log_msg, log_type = handler(
                    cmd_arg, folder, current_file, name_width, sort
                )

                # If the sort command succeeded, update the sort variable
                if cmd_name == "sort" and log_type == 2:
                    sort = cmd_arg.strip()

                files, folder, log_msg, log_type = get_files(
                    folder, sort, prev_folder, log_msg, log_type
                )
                if folder != prev_folder:
                    selected = 1

            typed = ""   # Clear the command buffer after execution

        # --- Backspace: delete last character ---
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if typed:
                typed = typed[:-1]

        # --- Regular character input ---
        else:
            try:
                letter = chr(key)
                if letter in ALLOWED_CHARS and len(typed) < MAX_TYPED_LEN:
                    typed += letter
            except (ValueError, OverflowError):
                pass   # Ignore non-character keys

        # Redraw the UI and apply any layout adjustments
        start, typed = render(
            folder, icons, descriptions, name_width,
            selected, stdscr, files, start, typed, log_msg, log_type,
        )

        # Poll for input every 200 ms (keeps CPU usage low)
        stdscr.timeout(200)


# ==========================
# Entry Point
# ==========================

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        # Clean exit: clear screen and show the logo
        os.system("cls" if os.name == "nt" else "clear")
        print("Thanks for using:")
        print(LOGO)
        raise SystemExit
