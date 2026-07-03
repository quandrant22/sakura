---
name: dependency-install
description: "Use when installing or reinstalling Python dependencies and restarting the service — covers venv creation, pip install, and service restart"
---

# Dependency Installation and Service Restart

Use this skill when you need to install or reinstall Python dependencies and restart the service.

## When to Use

- After changing requirements.txt
- When dependencies are corrupted or missing
- When setting up a new environment
- After updating Python version

## Procedure

### 1. Check Current Environment

```bash
# Check if venv exists
ls -la /path/to/project/venv/

# Check Python version
python3 --version

# Check installed packages
/path/to/project/venv/bin/pip list
```

### 2. Recreate Virtual Environment (if needed)

```bash
# Remove existing venv
rm -rf /path/to/project/venv

# Create new venv
python3 -m venv /path/to/project/venv

# Upgrade pip
/path/to/project/venv/bin/pip install --upgrade pip
```

### 3. Install Dependencies

```bash
# Install from requirements.txt
/path/to/project/venv/bin/pip install -r requirements.txt

# Or install specific packages
/path/to/project/venv/bin/pip install package1 package2 package3
```

### 4. Verify Installation

```bash
# Check installed packages
/path/to/project/venv/bin/pip list

# Test imports
cd /path/to/project && /path/to/project/venv/bin/python -c "import module_name; print('OK')"
```

### 5. Restart Service

```bash
# Restart service
systemctl restart <service_name>.service

# Wait for startup
sleep 2

# Verify service is running
systemctl status <service_name>.service
```

## Common Issues

### Permission Denied

```bash
# Fix venv permissions
chmod +x /path/to/project/venv/bin/python*
chmod +x /path/to/project/venv/bin/pip*
```

### Missing System Dependencies

```bash
# Install system dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y python3-dev build-essential

# Install system dependencies (Alpine)
apk add --no-cache python3-dev build-base
```

### Virtual Environment Broken

```bash
# Check if venv is broken
/path/to/project/venv/bin/python --version

# If segfault or error, recreate venv
rm -rf /path/to/project/venv
python3 -m venv /path/to/project/venv
```

## Service-Specific Examples

### Himari Bot

```bash
# Recreate venv and install deps
rm -rf /opt/himaryi/venv
python3 -m venv /opt/himaryi/venv
/opt/himaryi/venv/bin/pip install --upgrade pip
/opt/himaryi/venv/bin/pip install -r /opt/himaryi/requirements.txt

# Restart service
systemctl daemon-reload && systemctl restart himaryi.service
sleep 2
systemctl status himaryi.service
```

### With Systemd Service File Update

```bash
# Update service file to use new venv
sed -i 's|ExecStart=.*|ExecStart=/opt/himaryi/venv/bin/python main.py|' /etc/systemd/system/himaryi.service

# Reload and restart
systemctl daemon-reload && systemctl restart himaryi.service
```

## Stopping Condition

The workflow is complete when:
1. All dependencies are installed successfully
2. Service shows `active (running)` in status
3. No import errors in service logs
4. Expected functionality is working
