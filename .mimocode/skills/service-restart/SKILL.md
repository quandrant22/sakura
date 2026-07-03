---
name: service-restart
description: "Use when needing to restart a systemd service and verify it's healthy — covers restart, status check, log inspection, and port verification"
---

# Service Restart and Health Check

Use this skill when you need to restart a systemd service and verify it's running correctly.

## When to Use

- After code changes that require service restart
- When a service is unresponsive or crashed
- After configuration changes
- When diagnosing service issues

## Procedure

### 1. Pre-restart Checks

```bash
# Check current service status
systemctl status <service_name>.service

# Check if port is listening
ss -tlnp | grep <port>

# Check recent logs for errors
journalctl -u <service_name> --no-pager -n 20
```

### 2. Restart Service

```bash
# Standard restart
systemctl restart <service_name>.service

# With daemon-reload (if unit file changed)
systemctl daemon-reload && systemctl restart <service_name>.service

# Wait for service to start
sleep 2
```

### 3. Post-restart Verification

```bash
# Verify service is running
systemctl status <service_name>.service

# Verify port is listening
ss -tlnp | grep <port>

# Check for startup errors
journalctl -u <service_name> --no-pager -n 10
```

### 4. Health Check (if applicable)

```bash
# HTTP health check
curl -s http://127.0.0.1:<port>/health

# WebSocket connection test
python3 -c "
import asyncio, websockets, json
async def test():
    try:
        async with websockets.connect('ws://127.0.0.1:<port>', open_timeout=3) as ws:
            await ws.send(json.dumps({'type': 'register', 'device_id': 'test'}))
            print('Connection successful')
    except Exception as e:
        print(f'Connection failed: {e}')
asyncio.run(test())
"
```

## Common Issues

### Port Already in Use

```bash
# Find process using port
fuser <port>/tcp

# Kill process
fuser -k <port>/tcp

# Wait for TIME_WAIT to clear
sleep 2
```

### Service Crashes Immediately

```bash
# Check full crash log
journalctl -u <service_name> --no-pager -n 50

# Check for Python syntax errors
cd /path/to/project && python -m py_compile main.py

# Check for missing dependencies
cd /path/to/project && python -c "import <module>"
```

### Permission Issues

```bash
# Check service file permissions
ls -la /etc/systemd/system/<service_name>.service

# Verify user/group
grep -E "^(User|Group)" /etc/systemd/system/<service_name>.service
```

## Service-Specific Examples

### Himari Bot

```bash
systemctl restart himaryi.service && sleep 2 && systemctl status himaryi.service
ss -tlnp | grep 8766  # WebSocket port
ss -tlnp | grep 8080  # FastAPI port
```

### Docker Compose

```bash
cd /path/to/project
docker compose down
docker compose up -d
docker compose ps
```

## Stopping Condition

The workflow is complete when:
1. Service shows `active (running)` in status
2. Expected ports are listening
3. No errors in recent logs
4. Health check (if applicable) returns success
