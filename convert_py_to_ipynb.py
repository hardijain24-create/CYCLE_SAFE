import json
import re

def py_to_notebook(py_path, ipynb_path):
    with open(py_path, 'r', encoding='utf-8') as f:
        code = f.read()

    # Split on '# %%' or '# CELL' lines
    raw_cells = re.split(r'\n# %%\n|\n# CELL |\n# ======================================================================\n# CELL ', code)
    
    nb_cells = []
    for cell in raw_cells:
        cell_str = cell.strip()
        if not cell_str:
            continue
        
        # Check if cell is pure markdown comment block
        lines = cell_str.splitlines()
        is_markdown = False
        if lines and lines[0].startswith('"""') and lines[-1].endswith('"""'):
            is_markdown = True
            md_content = "\n".join(lines[1:-1])
        
        if is_markdown:
            nb_cells.append({
                "cell_type": "markdown",
                "metadata": {},
                "source": [line + "\n" for line in md_content.splitlines()]
            })
        else:
            nb_cells.append({
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [line + "\n" for line in cell_str.splitlines()]
            })

    notebook = {
        "cells": nb_cells,
        "metadata": {
            "language_info": {
                "name": "python"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 2
    }

    with open(ipynb_path, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=1)
    print(f"Successfully converted {py_path} to {ipynb_path} ({len(nb_cells)} cells)")

if __name__ == '__main__':
    py_to_notebook('cycle_safe.py', 'cycle_safe.ipynb')
    py_to_notebook('cycle_safe.py', 'cycle_safe (1).ipynb')
