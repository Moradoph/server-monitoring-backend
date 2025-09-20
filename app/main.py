import os
import asyncio
import json
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
import os
import pty
import shlex
import subprocess
import asyncio
from fastapi.middleware.cors import CORSMiddleware

from .metrics import MetricsProvider
from .alerts import AlertManager

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

metrics = MetricsProvider()
alert_manager = AlertManager(webhook_url=os.getenv("DISCORD_WEBHOOK_URL"))


@app.on_event("startup")
async def startup_event():
    metrics.start()


@app.on_event("shutdown")
async def shutdown_event():
    metrics.stop()


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = metrics.snapshot()
            # check alerts
            alert_manager.check_and_notify(data)
            await websocket.send_text(json.dumps(data))
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


@app.websocket("/ws/shell")
async def websocket_shell(websocket: WebSocket):
    # Simple token-based guard to avoid exposing an open shell by default
    token = os.getenv('SHELL_WS_TOKEN')
    # expect token as a query param: /ws/shell?token=...
    params = dict(websocket._query_params) if hasattr(websocket, '_query_params') else {}
    provided = params.get('token')
    if not token or provided != token:
        # refuse connection
        await websocket.close(code=1008)
        return

    await websocket.accept()

    # spawn a PTY shell and relay input/output
    loop = asyncio.get_event_loop()

    master_fd, slave_fd = pty.openpty()

    # Use /bin/bash if available, fall back to /bin/sh
    shell = os.environ.get('SHELL', '/bin/sh')

    proc = await asyncio.create_subprocess_exec(
        shell,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
    )

    async def reader_task():
        try:
            while True:
                data = await loop.run_in_executor(None, os.read, master_fd, 1024)
                if not data:
                    break
                try:
                    await websocket.send_text(data.decode(errors='ignore'))
                except Exception:
                    break
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    async def writer_task():
        try:
            while True:
                msg = await websocket.receive_text()
                # simple handling: write raw bytes to pty
                if msg is None:
                    break
                try:
                    os.write(master_fd, msg.encode())
                except Exception:
                    break
        except WebSocketDisconnect:
            pass

    r = asyncio.create_task(reader_task())
    w = asyncio.create_task(writer_task())

    done, pending = await asyncio.wait([r, w], return_when=asyncio.FIRST_COMPLETED)

    for t in pending:
        t.cancel()

    try:
        proc.kill()
    except Exception:
        pass
    try:
        os.close(master_fd)
        os.close(slave_fd)
    except Exception:
        pass
