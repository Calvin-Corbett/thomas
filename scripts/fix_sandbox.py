from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
file_path = str(ROOT / "thomas" / "tools" / "sandbox.py")

with open(file_path, encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    # Fix 1: Wrapper Start
    if 'return f"""# Auto-generated Thomas sandbox wrapper' in line:
        line = line.replace('return f"""', "return f'''")

    # Fix 2: Wrapper End (approx line 756)
    # It is a line with just """ and maybe whitespace
    if line.strip() == '"""' and i > 750 and i < 760:
        line = line.replace('"""', "'''")

    # Fix 3: Harness Start
    if 'return f"""' in line and i > 930:
        # Check context
        if "# --- Thomas sandbox.test_snippet batch harness ---" in lines[i + 1]:
            line = line.replace('return f"""', "return f'''")

    # Fix 4: Harness End (approx line 989)
    if '"""' in line and i > 980:
        print(f"Found match at {i}: {line.strip()}")
        if line.strip() == '"""':
            print(f"Replacing at {i}")
            line = line.replace('"""', "'''")

    new_lines.append(line)

with open(file_path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Fixed sandbox.py")
