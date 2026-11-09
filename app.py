"""
Tablero SPI-01.

Lee el JSON que el Arduino publica por el USB serial y lo muestra
en una página. La tablet solo abre esa página. Este proceso no decide
si una barrera se abre: eso lo hace la placa.
"""

import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import serial
except ImportError:
    serial = None

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PORT_NAME = os.environ.get("SERIAL_PORT", "/dev/ttyACM0")
BAUD = int(os.environ.get("SERIAL_BAUD", "115200"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))
ALLOWED_COMMANDS = {"status", "sensors", "open", "close", "reset"}

state_lock = threading.Lock()
clients_lock = threading.Lock()
write_lock = threading.Lock()
clients = []
serial_port = None

state = {
    "connected": False,
    "port": PORT_NAME,
    "serial_error": None,
    "received_at": None,
    "uptime_ms": None,
    "slots": [
        {"id": 1, "status": "UNKNOWN", "cm": None},
        {"id": 2, "status": "UNKNOWN", "cm": None},
        {"id": 3, "status": "UNKNOWN", "cm": None},
    ],
    "available": 0,
    "occupied": 0,
    "gate": "CLOSED",
    "exit_gate": "CLOSED",
    "entry": [0, 0],
    "exit": [0, 0],
    "barrier": 0,
    "exit_barrier": 0,
    "events": [],
    "last_error": None,
}


def snapshot():
    with state_lock:
        return json.loads(json.dumps(state))


def publish():
    payload = json.dumps(snapshot(), ensure_ascii=False).encode("utf-8")
    with clients_lock:
        current = list(clients)
    for client in current:
        if client.full():
            try:
                client.get_nowait()
            except queue.Empty:
                pass
        try:
            client.put_nowait(payload)
        except queue.Full:
            pass


def remember_event(message):
    item = {
        "event": message.get("event"),
        "location": message.get("location"),
        "reason": message.get("reason"),
        "slot": message.get("slot"),
        "status": message.get("status"),
        "uptime_ms": message.get("uptime_ms"),
        "at": time.strftime("%H:%M:%S"),
    }
    state["events"].insert(0, item)
    del state["events"][20:]


def slot_by_id(slot_id):
    for slot in state["slots"]:
        if slot["id"] == slot_id:
            return slot
    return None


def apply_message(message):
    kind = message.get("type")
    with state_lock:
        if "uptime_ms" in message:
            state["uptime_ms"] = message["uptime_ms"]
        state["received_at"] = time.strftime("%H:%M:%S")

        if kind == "parking_status":
            for incoming in message.get("slots", []):
                slot = slot_by_id(incoming.get("id"))
                if slot and "status" in incoming:
                    slot["status"] = incoming["status"]
            for key in ("available", "occupied", "gate", "exit_gate"):
                if key in message:
                    state[key] = message[key]

        elif kind == "sensors":
            for incoming in message.get("slots", []):
                slot = slot_by_id(incoming.get("id"))
                if not slot:
                    continue
                if "status" in incoming:
                    slot["status"] = incoming["status"]
                if "cm" in incoming:
                    slot["cm"] = incoming["cm"]
            for key in ("entry", "exit", "barrier", "exit_barrier", "gate", "exit_gate"):
                if key in message:
                    state[key] = message[key]

        elif kind == "event":
            if message.get("event") == "SLOT_CHANGED":
                slot = slot_by_id(message.get("slot"))
                if slot and "status" in message:
                    slot["status"] = message["status"]
            remember_event(message)

        elif kind == "error":
            state["last_error"] = message.get("message")
            remember_event({
                "event": "ERROR",
                "reason": message.get("message"),
                "uptime_ms": message.get("uptime_ms"),
            })
        else:
            return
    publish()


def set_link(connected, error=None):
    with state_lock:
        changed = state["connected"] != connected or state["serial_error"] != error
        state["connected"] = connected
        state["serial_error"] = error
    if changed:
        publish()


def send_command(command):
    if command not in ALLOWED_COMMANDS:
        return False, "comando no permitido"
    if PORT_NAME == "demo":
        return True, None
    with write_lock:
        port = serial_port
        if port is None or not port.is_open:
            return False, "el Arduino no está conectado"
        port.write(('{"cmd":"%s"}\n' % command).encode("ascii"))
        port.flush()
    return True, None


def read_serial():
    global serial_port
    if serial is None:
        set_link(False, "falta el paquete pyserial")
        return

    while True:
        try:
            port = serial.Serial(PORT_NAME, BAUD, timeout=1)
            with write_lock:
                serial_port = port
            time.sleep(2)
            set_link(True, None)
            pending = b""
            while True:
                chunk = port.read(port.in_waiting or 1)
                if not chunk:
                    continue
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    text = line.decode("utf-8", "replace").strip()
                    if not text:
                        continue
                    try:
                        apply_message(json.loads(text))
                    except json.JSONDecodeError:
                        with state_lock:
                            state["last_error"] = "línea no JSON"
                        publish()
        except Exception as error:
            with write_lock:
                if serial_port is not None:
                    try:
                        serial_port.close()
                    except Exception:
                        pass
                    serial_port = None
            set_link(False, str(error))
            time.sleep(2)


def request_sensors_forever():
    while True:
        time.sleep(3)
        if PORT_NAME == "demo":
            continue
        with state_lock:
            connected = state["connected"]
        if connected:
            send_command("sensors")


def run_demo():
    """Pantalla de prueba, sin placa. No se usa en la maqueta."""
    set_link(True, None)
    step = 0
    while True:
        step += 1
        occupied = step % 2 == 0
        gate = "OPEN" if step % 4 == 1 else "CLOSED"
        exit_gate = "OPEN" if step % 4 == 3 else "CLOSED"
        apply_message({
            "type": "parking_status",
            "uptime_ms": step * 1000,
            "slots": [
                {"id": 1, "status": "AVAILABLE"},
                {"id": 2, "status": "OCCUPIED" if occupied else "AVAILABLE"},
                {"id": 3, "status": "AVAILABLE"},
            ],
            "available": 2 if occupied else 3,
            "occupied": 1 if occupied else 0,
            "gate": gate,
            "exit_gate": exit_gate,
        })
        if step % 4 == 1:
            apply_message({
                "type": "event",
                "event": "VEHICLE_DETECTED",
                "location": "ENTRY",
                "uptime_ms": step * 1000,
            })
        apply_message({
            "type": "sensors",
            "uptime_ms": step * 1000,
            "slots": [
                {"id": 1, "cm": 40, "status": "AVAILABLE"},
                {"id": 2, "cm": 12 if occupied else 41, "status": "OCCUPIED" if occupied else "AVAILABLE"},
                {"id": 3, "cm": 36, "status": "AVAILABLE"},
            ],
            "entry": [1, 0] if step % 4 == 1 else [0, 0],
            "exit": [0, 0],
            "barrier": 1 if step % 4 == 2 else 0,
            "exit_barrier": 0,
            "gate": gate,
            "exit_gate": exit_gate,
        })
        time.sleep(2)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_bytes(self, code, body, content_type):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            self.send_bytes(200, json.dumps(snapshot(), ensure_ascii=False), "application/json; charset=utf-8")
            return
        if path == "/api/stream":
            self.stream()
            return
        if path == "/":
            path = "/index.html"
        file_path = (STATIC / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(STATIC)) or not file_path.is_file():
            self.send_bytes(404, "No encontrado", "text/plain; charset=utf-8")
            return
        kinds = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}
        self.send_bytes(200, file_path.read_bytes(), kinds.get(file_path.suffix, "application/octet-stream"))

    def stream(self):
        client = queue.Queue(maxsize=8)
        with clients_lock:
            clients.append(client)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b"data: " + json.dumps(snapshot(), ensure_ascii=False).encode("utf-8") + b"\n\n")
            self.wfile.flush()
            while True:
                item = client.get()
                if item is None:
                    self.wfile.write(b": ping\n\n")
                else:
                    self.wfile.write(b"data: " + item + b"\n\n")
                self.wfile.flush()
        except Exception:
            pass
        finally:
            with clients_lock:
                if client in clients:
                    clients.remove(client)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/command":
            self.send_bytes(404, '{"ok":false}', "application/json")
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            command = json.loads(raw.decode("utf-8")).get("cmd", "")
        except json.JSONDecodeError:
            self.send_bytes(400, '{"ok":false,"error":"json"}', "application/json")
            return
        ok, error = send_command(command)
        code = 200 if ok else 409
        self.send_bytes(code, json.dumps({"ok": ok, "error": error}, ensure_ascii=False), "application/json; charset=utf-8")


def ping_clients():
    while True:
        time.sleep(10)
        with clients_lock:
            current = list(clients)
        for client in current:
            try:
                client.put_nowait(None)
            except queue.Full:
                pass


def main():
    if PORT_NAME == "demo":
        threading.Thread(target=run_demo, daemon=True).start()
    else:
        threading.Thread(target=read_serial, daemon=True).start()
        threading.Thread(target=request_sensors_forever, daemon=True).start()
    threading.Thread(target=ping_clients, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    print("Tablero en http://0.0.0.0:%s  puerto serial %s" % (HTTP_PORT, PORT_NAME), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
