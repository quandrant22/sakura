---
name: websocket-test
description: "Use when testing WebSocket connections to the bot server — covers connection testing, message sending, and response validation"
---

# WebSocket Connection Testing

Use this skill when you need to test WebSocket connections to the bot server.

## When to Use

- After restarting the bot service
- When diagnosing client connection issues
- When testing new WebSocket message types
- When validating WebSocket server functionality

## Procedure

### 1. Basic Connection Test

```bash
# Simple connection test
python3 -c "
import asyncio, websockets, json
async def test():
    try:
        async with websockets.connect('ws://127.0.0.1:8766', open_timeout=3) as ws:
            print('Connected successfully')
    except Exception as e:
        print(f'Connection failed: {e}')
asyncio.run(test())
"
```

### 2. Register Device

```bash
# Register a test device
python3 -c "
import asyncio, websockets, json
async def test():
    try:
        async with websockets.connect('ws://127.0.0.1:8766', open_timeout=3) as ws:
            await ws.send(json.dumps({'type': 'register', 'device_id': 'test'}))
            response = await ws.recv()
            print(f'Register response: {response}')
    except Exception as e:
        print(f'Error: {e}')
asyncio.run(test())
"
```

### 3. Send Voice Command

```bash
# Send a voice command
python3 -c "
import asyncio, websockets, json
async def test():
    try:
        async with websockets.connect('ws://127.0.0.1:8766', open_timeout=3) as ws:
            # Register first
            await ws.send(json.dumps({'type': 'register', 'device_id': 'test'}))
            await ws.recv()
            
            # Send voice command
            await ws.send(json.dumps({
                'type': 'voice_command',
                'text': 'привет',
                'device_id': 'test',
                'context': {},
                'active_window': ''
            }))
            
            # Wait for response
            response = await asyncio.wait_for(ws.recv(), timeout=10)
            print(f'Voice reply: {response}')
    except Exception as e:
        print(f'Error: {e}')
asyncio.run(test())
"
```

### 4. Test Screenshot Handler

```bash
# Test screenshot processing (if enabled)
python3 -c "
import asyncio, websockets, json, base64
async def test():
    try:
        async with websockets.connect('ws://127.0.0.1:8766', open_timeout=3) as ws:
            # Register
            await ws.send(json.dumps({'type': 'register', 'device_id': 'test'}))
            await ws.recv()
            
            # Send test screenshot (small base64 image)
            test_image = base64.b64encode(b'test').decode()
            await ws.send(json.dumps({
                'type': 'vision_query',
                'image': test_image,
                'device_id': 'test'
            }))
            
            # Wait for response
            response = await asyncio.wait_for(ws.recv(), timeout=10)
            print(f'Vision response: {response}')
    except Exception as e:
        print(f'Error: {e}')
asyncio.run(test())
"
```

## Common Issues

### Connection Refused

```bash
# Check if port is listening
ss -tlnp | grep 8766

# Check service status
systemctl status himaryi.service

# Check for errors in logs
journalctl -u himaryi --no-pager -n 20
```

### Timeout on Response

```bash
# Check if service is processing
journalctl -u himaryi --no-pager -n 10

# Check if Gemini API is responding
curl -s https://generativelanguage.googleapis.com/...  # Test API key
```

### Device Not Registered

```bash
# Check device manager
cd /opt/himaryi && python -c "
from modules.device_manager import get_devices
import json
print(json.dumps(get_devices(), indent=2))
"
```

## Service-Specific Examples

### Himari Bot

```bash
# Test connection to Himari
python3 -c "
import asyncio, websockets, json
async def test():
    try:
        async with websockets.connect('ws://127.0.0.1:8766', open_timeout=3) as ws:
            await ws.send(json.dumps({'type': 'register', 'device_id': 'arch-himari'}))
            response = await ws.recv()
            print(f'Connected: {response}')
    except Exception as e:
        print(f'Failed: {e}')
asyncio.run(test())
"
```

## Stopping Condition

The workflow is complete when:
1. WebSocket connection succeeds
2. Device registration works
3. Expected responses are received
4. No errors in service logs
