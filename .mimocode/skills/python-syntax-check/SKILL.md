---
name: python-syntax-check
description: "Use when validating Python code for syntax errors before deployment or after edits — covers py_compile, import checks, and common error patterns"
---

# Python Syntax Validation

Use this skill when you need to validate Python code for syntax errors before deploying or after making edits.

## When to Use

- After editing Python files
- Before restarting services
- When diagnosing import errors
- When validating code changes

## Procedure

### 1. Basic Syntax Check

```bash
# Check single file
cd /path/to/project && python -m py_compile main.py

# Check multiple files
cd /path/to/project && python -m py_compile main.py && python -m py_compile modules/file.py
```

### 2. Import Validation

```bash
# Check if module can be imported
cd /path/to/project && python -c "import main"

# Check specific imports
cd /path/to/project && python -c "from modules import device_manager; print('OK')"
```

### 3. Comprehensive Check

```bash
# Check all Python files in directory
cd /path/to/project && python -m py_compile *.py

# Check with error details
cd /path/to/project && python3 -c "
import py_compile
try:
    py_compile.compile('main.py', doraise=True)
    print('Syntax OK')
except py_compile.PyCompileError as e:
    print(f'Syntax error: {e}')
"
```

### 4. Virtual Environment Check

```bash
# Activate venv and check
source /path/to/venv/bin/activate && python -m py_compile main.py

# Or use venv Python directly
/path/to/venv/bin/python -m py_compile main.py
```

## Common Error Patterns

### IndentationError

```python
# Wrong
def func():
print("hello")  # Missing indent

# Correct
def func():
    print("hello")  # 4 spaces
```

### SyntaxError

```python
# Wrong
if x = 5:  # Assignment in condition
    pass

# Correct
if x == 5:  # Comparison
    pass
```

### ImportError

```bash
# Check if module exists
find /path/to/project -name "module_name.py"

# Check if module is installed
pip list | grep module_name
```

## Service-Specific Examples

### Himari Bot

```bash
cd /opt/himaryi && python -m py_compile main.py
cd /opt/himaryi && python -m py_compile modules/device_manager.py
cd /opt/himaryi && python3 -c "import py_compile; py_compile.compile('main.py', doraise=True)"
```

### With Virtual Environment

```bash
cd /opt/himaryi && /opt/himaryi/venv/bin/python -m py_compile main.py
```

## Stopping Condition

The workflow is complete when:
1. All modified Python files pass syntax check
2. No import errors for required modules
3. Code can be loaded without syntax errors
