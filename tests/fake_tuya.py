"""Lâmpada Tuya (protocolo 3.3) simulada por TCP, para testes sem hardware.

Comporta-se como as lâmpadas reais que causavam lentidão: aceita a conexão
com algum atraso, responde a comandos com uma confirmação vazia e só depois
empurra o novo estado. Também permite simular mudanças externas (Alexa).
"""

import json
import socket
import struct
import threading
import time

from tinytuya.core.crypto_helper import AESCipher
from tinytuya.core.message_helper import TuyaMessage, pack_message, parse_header, unpack_message

KEY = "0123456789abcdef"
DEV_ID = "ebfake0000000000000000"
HEADER_33 = b"3.3" + b"\0" * 12

CONTROL, STATUS, HEART_BEAT, DP_QUERY = 7, 8, 9, 10


class FakeTuyaBulb:
    def __init__(self, accept_delay=0.0, push_delay=0.02, ack_first=True):
        self.dps = {"20": True, "21": "white", "22": 500, "23": 250, "24": "00f003e803e8", "25": "", "26": 0}
        self.accept_delay = accept_delay
        self.push_delay = push_delay
        self.ack_first = ack_first
        self.cipher = AESCipher(KEY.encode())
        self.received = []          # (timestamp, dps) de cada CONTROL recebido
        self.connections = 0
        self._clients = []
        self._lock = threading.Lock()
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(5)
        self.port = self._srv.getsockname()[1]
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()

    # -- API dos testes -------------------------------------------------------
    def external_set(self, dps: dict):
        """Simula uma mudança feita pela Alexa/app: atualiza e avisa os clientes."""
        with self._lock:
            self.dps.update(dps)
            clients = list(self._clients)
        for c in clients:
            self._push(c, dps)

    def drop_clients(self):
        with self._lock:
            clients, self._clients = list(self._clients), []
        for c in clients:
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass

    def close(self):
        self._running = False
        self.drop_clients()
        self._srv.close()

    # -- servidor -------------------------------------------------------------
    def _accept_loop(self):
        while self._running:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            time.sleep(self.accept_delay)
            self.connections += 1
            with self._lock:
                self._clients.append(conn)
            threading.Thread(target=self._client_loop, args=(conn,), daemon=True).start()

    def _send(self, conn, cmd, body: bytes, seq=0):
        payload = struct.pack(">I", 0) + body
        msg = TuyaMessage(seq, cmd, 0, payload, 0, True, 0x55AA, None)
        try:
            conn.sendall(pack_message(msg))
        except OSError:
            pass

    def _encrypt(self, obj, header=False):
        data = self.cipher.encrypt(json.dumps(obj).encode(), use_base64=False)
        return (HEADER_33 + data) if header else data

    def _push(self, conn, dps):
        self._send(conn, STATUS, self._encrypt({"dps": dps, "t": int(time.time())}, header=True))

    def _client_loop(self, conn):
        buf = b""
        while self._running:
            try:
                chunk = conn.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while len(buf) >= 16:
                try:
                    hdr = parse_header(buf)
                except Exception:
                    buf = b""
                    break
                if len(buf) < hdr.total_length:
                    break
                raw, buf = buf[:hdr.total_length], buf[hdr.total_length:]
                msg = unpack_message(raw, header=hdr, no_retcode=True)
                self._handle(conn, msg)
        with self._lock:
            if conn in self._clients:
                self._clients.remove(conn)
        conn.close()

    def _decrypt(self, payload: bytes):
        if payload.startswith(b"3.3"):
            payload = payload[len(HEADER_33):]
        return json.loads(self.cipher.decrypt(payload, False, decode_text=False))

    def _handle(self, conn, msg):
        if msg.cmd == HEART_BEAT:
            self._send(conn, HEART_BEAT, b"", msg.seqno)
        elif msg.cmd == DP_QUERY:
            with self._lock:
                dps = dict(self.dps)
            self._send(conn, DP_QUERY, self._encrypt({"devId": DEV_ID, "dps": dps}), msg.seqno)
        elif msg.cmd == CONTROL:
            dps = self._decrypt(msg.payload).get("dps", {})
            self.received.append((time.monotonic(), dps))
            with self._lock:
                self.dps.update(dps)
            if self.ack_first:
                self._send(conn, CONTROL, b"", msg.seqno)  # confirmação vazia
            if self.push_delay:
                time.sleep(self.push_delay)
            self._push(conn, dps)
