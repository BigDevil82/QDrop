"""Verify a deployed API over trusted HTTPS/WSS; temporary identities are revoked.

Requires the dev Python environment and authorized SSH access. --restart-api explicitly
allows restarting only this Compose API to verify durable inbox/ACK recovery.
Credentials remain in memory and are never printed or saved.
"""
import argparse
import hashlib
import json
import shlex
import subprocess
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--directory', default='/srv/QDrop')
    parser.add_argument('--restart-api', action='store_true')
    args = parser.parse_args()
    origin = urlsplit(args.url)
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ('', '/'):
        parser.error('--url must be a trusted HTTPS origin')
    base = args.url.rstrip('/')
    compose = 'docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.external-proxy.example.yaml '

    def remote(command):
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', args.ssh, 'cd ' + shlex.quote(args.directory) + ' && ' + compose + command], capture_output=True, text=True, check=True, timeout=90)
        return result.stdout.strip()

    devices = []
    report = {}
    with httpx.Client(base_url=base, timeout=45) as client:
        def request(method, path, device=None, **kwargs):
            headers = {'Authorization': 'Bearer ' + device['token']} if device else {}
            return client.request(method, path, headers=headers, **kwargs)

        def checked(method, path, device=None, **kwargs):
            response = request(method, path, device, **kwargs)
            response.raise_for_status()
            return response

        def send(source, target, body, kind='text'):
            sha = hashlib.sha256(body).hexdigest()
            metadata = dict(client_transfer_id=str(uuid.uuid4()), recipient_device_id=target['device_id'], kind=kind,
                            name='deployment-check.bin' if kind == 'file' else None,
                            mime='application/octet-stream' if kind == 'file' else 'text/plain;charset=utf-8',
                            size=len(body), sha256=sha, origin_created_at=datetime.now(timezone.utc).isoformat())
            tid = checked('POST', '/v1/transfers', source, json=metadata).json()['id']
            assert checked('POST', '/v1/transfers', source, json=metadata).json()['id'] == tid
            conflicting = {**metadata, 'size': len(body) + 1}
            assert request('POST', '/v1/transfers', source, json=conflicting).status_code == 409
            checked('PUT', f'/v1/transfers/{tid}/content', source, content=body)
            checked('POST', f'/v1/transfers/{tid}/commit', source)
            return tid, dict(size=len(body), sha256=sha)

        def receive(tid, device, body, ack):
            data = checked('GET', f'/v1/transfers/{tid}/content', device).content
            assert data == body and hashlib.sha256(data).hexdigest() == ack['sha256']
            for _ in range(2):
                assert checked('POST', f'/v1/transfers/{tid}/ack', device, json=ack).json()['state'] == 'RECEIVED'

        try:
            assert checked('GET', '/readyz').json()['ready'] is True
            assert request('GET', '/v1/me').status_code == 401
            report['trusted_https_and_auth'] = 'passed'
            for platform in ('android', 'windows'):
                code = remote('exec -T api python -m app.cli enroll')
                device = checked('POST', '/v1/enroll', json=dict(code=code, device_name='deployment-check-' + platform,
                                platform=platform, client_version='deployment-check')).json()
                devices.append(device)
                assert checked('GET', '/v1/me', device).json()['protocol_version'] == 1
            sender, receiver = devices
            body = ('QDrop 公网文本验证 🌍\nhttps://example.com\n' + '中文逐字一致。' * 100).encode('utf-8')
            socket_url = 'wss://' + origin.netloc + '/v1/events'
            with connect(socket_url, additional_headers={'Authorization': 'Bearer ' + receiver['token']}, open_timeout=20) as ws:
                assert json.loads(ws.recv(timeout=10))['type'] == 'device.changed'
                tid, ack = send(sender, receiver, body)
                event = json.loads(ws.recv(timeout=10))
                assert event['type'] == 'transfer.ready' and event['transfer_id'] == tid
                assert not set(event).intersection({'body', 'text', 'token', 'name'})
            report['wss_metadata_hint'] = 'passed'
            assert request('GET', f'/v1/transfers/{tid}/content', sender).status_code == 403
            if args.restart_api:
                remote('restart api')
                ready = False
                for _ in range(50):
                    try:
                        ready = client.get('/readyz', timeout=2).status_code == 200
                    except httpx.HTTPError:
                        pass
                    if ready:
                        break
                    time.sleep(.2)
                assert ready
                report['api_restart_durable_inbox'] = 'passed'
            assert tid in [t['id'] for t in checked('GET', '/v1/inbox', receiver).json()['items']]
            receive(tid, receiver, body, ack)
            report['utf8_sha256_and_duplicate_ack'] = 'passed'
            file_body = bytes(range(256)) * 4096
            file_id, file_ack = send(sender, receiver, file_body, 'file')
            receive(file_id, receiver, file_body, file_ack)
            report['one_mib_file_sha256'] = 'passed'
            reverse_id, reverse_ack = send(receiver, sender, body)
            receive(reverse_id, sender, body, reverse_ack)
            report['bidirectional_roles_and_idempotence'] = 'passed'
            with connect(socket_url, additional_headers={'Authorization': 'Bearer ' + sender['token']}, open_timeout=20) as ws:
                ws.recv(timeout=10)
                remote('exec -T api python -m app.cli revoke ' + shlex.quote(sender['device_id']))
                assert request('GET', '/v1/me', sender).status_code == 401
                try:
                    ws.recv(timeout=10)
                    raise AssertionError('Revoked socket remained open')
                except ConnectionClosed:
                    pass
            report['revocation_http_and_wss'] = 'passed'
            print(json.dumps(report, ensure_ascii=False))
        finally:
            for device in devices:
                remote('exec -T api python -m app.cli revoke ' + shlex.quote(device['device_id']))


if __name__ == '__main__':
    run()
