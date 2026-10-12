"""Actual TCP backpressure holds a download lease across expiry/cleanup."""

import asyncio
import hashlib
import socket
import threading
import time
import uuid

import httpx
import uvicorn
import pytest
from app.main import create_app, digest, stamp


def test_active_tcp_download_survives_cleanup(tmp_path):
    app = create_app(tmp_path)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started
    base = f"http://127.0.0.1:{port}"
    try:
        devices = []
        with httpx.Client(base_url=base, timeout=30) as c:
            for platform in ["android", "windows"]:
                code = str(uuid.uuid4())
                with app.state.store.transaction() as db:
                    db.execute(
                        "INSERT INTO enrollments VALUES(?,?,NULL)", (digest(code.encode()), time.time() + 600)
                    )
                r = c.post(
                    "/v1/enroll",
                    json=dict(code=code, device_name="lease", platform=platform, client_version="test"),
                )
                r.raise_for_status()
                devices.append(r.json())
            a, b = devices
            ha = {"Authorization": "Bearer " + a["token"]}
            hb = {"Authorization": "Bearer " + b["token"]}
            small = b'hello'
            small_meta = dict(client_transfer_id=str(uuid.uuid4()), recipient_device_id=b['device_id'], kind='file', name='retry.txt', mime='text/plain', size=5, sha256=digest(small), origin_created_at=stamp(time.time()))
            r = c.post('/v1/transfers', json=small_meta, headers=ha)
            r.raise_for_status()
            small_id = r.json()['id']
            def interrupted():
                yield small[:2]
                raise OSError('simulated client connection interrupted')
            with pytest.raises(OSError):
                c.put(f'/v1/transfers/{small_id}/content', content=interrupted(), headers=ha)
            assert c.post('/v1/transfers', json=small_meta, headers=ha).json()['id'] == small_id
            for _ in range(100):
                retry = c.put(f'/v1/transfers/{small_id}/content', content=small, headers=ha)
                if retry.status_code != 409:
                    break
                time.sleep(.02)
            retry.raise_for_status()
            c.post(f'/v1/transfers/{small_id}/commit', headers=ha).raise_for_status()
            assert c.get(f'/v1/transfers/{small_id}/content', headers=hb).content == small
            chunk = b"0" * 65536
            count = 800
            h = hashlib.sha256()
            for _ in range(count):
                h.update(chunk)
            meta = dict(
                client_transfer_id=str(uuid.uuid4()),
                recipient_device_id=b["device_id"],
                kind="file",
                name="lease.bin",
                mime="application/octet-stream",
                size=len(chunk) * count,
                sha256=h.hexdigest(),
                origin_created_at=stamp(time.time()),
            )
            r = c.post("/v1/transfers", json=meta, headers=ha)
            r.raise_for_status()
            tid = r.json()["id"]
            c.put(
                f"/v1/transfers/{tid}/content", content=(chunk for _ in range(count)), headers=ha
            ).raise_for_status()
            c.post(f"/v1/transfers/{tid}/commit", headers=ha).raise_for_status()
            with c.stream("GET", f"/v1/transfers/{tid}/content", headers=hb) as r:
                r.raise_for_status()
                parts = r.iter_raw()
                received = hashlib.sha256()
                received.update(next(parts))
                assert app.state.leases[tid] == 1
                with app.state.store.transaction() as db:
                    db.execute("UPDATE transfers SET expires_at=? WHERE id=?", (time.time() - 1, tid))
                asyncio.run_coroutine_threadsafe(app.state.cleanup(), app.state.loop).result(10)
                assert app.state.store.path(tid).exists()
                assert c.get(f"/v1/transfers/{tid}/content", headers=hb).status_code == 410
                for part in parts:
                    received.update(part)
                assert received.hexdigest() == meta["sha256"]
            for _ in range(100):
                if app.state.leases[tid] == 0:
                    break
                time.sleep(0.01)
            asyncio.run_coroutine_threadsafe(app.state.cleanup(), app.state.loop).result(10)
            assert not app.state.store.path(tid).exists()
    finally:
        server.should_exit = True
        thread.join(10)
        assert not thread.is_alive()
