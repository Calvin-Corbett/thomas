#!/usr/bin/env python3
"""
Extract JS parts from string array format into real .js module files.

This script:
1. Reads each part file (part-001.js through part-033.js)
2. Extracts the string array content (the actual JS code)
3. Writes clean .js files to thomas/server/web/js/modules/
4. Removes string array wrapping and escaping
5. Names files based on content inspection (function names, comments)
"""

import os
import re
from pathlib import Path

# Configuration
PARTS_DIR = Path(__file__).parent.parent / "thomas" / "server" / "web" / "js" / "app_parts"
OUTPUT_DIR = Path(__file__).parent.parent / "thomas" / "server" / "web" / "js" / "modules"
PART_FILES = [f"part-{i:03d}.js" for i in range(1, 34)]
PART_FILES.extend([f"part-{i:03d}b.js" for i in range(1, 34) if (PARTS_DIR / f"part-{i:03d}b.js").exists()])


def extract_string_array(content: str) -> list[str]:
    """Extract the string array from a part file."""
    # Try array format first: export default [ ... ]; or export default [ ... ].join("\n");
    match = re.search(r"export\s+default\s*\[\s*(.*?)\s*\](?:\.join\([^)]*\))?;", content, re.DOTALL)

    if match:
        array_content = match.group(1)

        # Parse the array - each element is a quoted string
        lines = []
        in_string = False
        current_string = []
        i = 0

        while i < len(array_content):
            char = array_content[i]

            # Handle string literals
            if char == '"' and (i == 0 or array_content[i - 1] != "\\"):
                if not in_string:
                    in_string = True
                    current_string = []
                else:
                    # End of string
                    in_string = False
                    lines.append("".join(current_string))
                    current_string = []
            elif in_string:
                if char == "\\" and i + 1 < len(array_content):
                    next_char = array_content[i + 1]
                    if next_char == '"':
                        current_string.append('"')
                        i += 1
                    elif next_char == "n":
                        current_string.append("\n")
                        i += 1
                    elif next_char == "t":
                        current_string.append("\t")
                        i += 1
                    elif next_char == "\\":
                        current_string.append("\\")
                        i += 1
                    elif next_char == "r":
                        current_string.append("\r")
                        i += 1
                    else:
                        current_string.append(char)
                else:
                    current_string.append(char)

            i += 1

        return lines

    # Try template literal format: export default `...`;
    template_match = re.search(r"export\s+default\s*`(.*?)`\s*;", content, re.DOTALL)
    if template_match:
        code = template_match.group(1)
        return code.split("\n")

    raise ValueError("Could not find 'export default [...]' or 'export default `...`' pattern")


def extract_metadata(lines: list[str]) -> tuple[str, str]:
    """Extract a good filename from the code content."""
    # Look for comments indicating function names or sections
    code = "\n".join(lines[:100])  # Check first 100 lines

    # Try to find major section comments or function definitions
    section_match = re.search(r"//\s*[╔═╚║]*\s*([A-Z][A-Z0-9\s&]+?)(?:\s*[║╗╚═]*)?", code)
    if section_match:
        section_name = section_match.group(1).strip().lower()
        section_name = re.sub(r"[^\w\s]", "", section_name).replace(" ", "_")
        return section_name[:40], section_match.group(0)

    # Look for function definitions
    func_match = re.search(r"(?:function|const|let)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*[=\(]", code)
    if func_match:
        func_name = func_match.group(1).lower()
        return func_name[:50], f"From {func_name}"

    # Look for class definitions
    class_match = re.search(r"class\s+([a-zA-Z_$][a-zA-Z0-9_$]*)", code)
    if class_match:
        class_name = class_match.group(1).lower()
        return class_name[:50], f"From {class_name}"

    # Fallback: use generic name
    return "generic_module", "Generic module content"


def write_module_file(part_name: str, lines: list[str], index: int) -> str:
    """Write extracted content to a module file."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Generate filename
    base_name, description = extract_metadata(lines)
    filename = f"{index:03d}_{base_name}.js"
    filepath = OUTPUT_DIR / filename

    # Reconstruct the code
    code = "\n".join(lines)

    # Add header
    header = f"// Extracted from {part_name}\n// {description}\n\n"
    full_content = header + code

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_content)

    return str(filepath)


def main():
    print(f"Extracting JS parts from {PARTS_DIR}")
    print(f"Output directory: {OUTPUT_DIR}")

    # Clean output directory
    if OUTPUT_DIR.exists():
        import shutil

        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    extracted_files = []
    errors = []

    # Sort part files numerically
    sorted_parts = sorted(
        PART_FILES, key=lambda x: (int(re.match(r"part-(\d+)", x).group(1)), 0 if not x.endswith("b.js") else 1)
    )

    for idx, part_name in enumerate(sorted_parts, 1):
        part_path = PARTS_DIR / part_name

        if not part_path.exists():
            print(f"⊘ {part_name:20} - FILE NOT FOUND")
            continue

        try:
            with open(part_path, encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                print(f"⊘ {part_name:20} - EMPTY FILE")
                continue

            lines = extract_string_array(content)
            output_path = write_module_file(part_name, lines, idx)

            print(f"✓ {part_name:20} -> {Path(output_path).name:40} ({len(lines)} lines)")
            extracted_files.append(output_path)

        except Exception as e:
            error_msg = f"✗ {part_name:20} - ERROR: {str(e)[:60]}"
            print(error_msg)
            errors.append((part_name, str(e)))

    print(f"\n{'='*80}")
    print("Extraction Complete")
    print(f"  Extracted files: {len(extracted_files)}")
    print(f"  Errors: {len(errors)}")
    print(f"  Output directory: {OUTPUT_DIR}")

    if errors:
        print("\nErrors encountered:")
        for part_name, error in errors:
            print(f"  {part_name}: {error}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
