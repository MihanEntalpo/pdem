import asyncio
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from pdem import pdem


class ServerHandle:
    def __init__(self, app, port, thread, loop_holder):
        self.app = app
        self.port = port
        self.thread = thread
        self.loop_holder = loop_holder


def _build_command(parts):
    encoded = [pdem.Tools.addSlashes(part.encode("utf-8")) for part in parts]
    return b"[CMD[" + b" ".join(encoded) + b"]CMD]"


class RawClient:
    def __init__(self, port: int):
        self.sock = socket.create_connection(("127.0.0.1", port))
        self.sock.settimeout(2.0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def send_command(self, parts):
        payload = _build_command(parts)
        self.sock.sendall(payload)

    def read_answer(self):
        buffer = bytearray()
        while True:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("Connection closed before receiving answer")
            buffer.extend(chunk)
            start = buffer.find(b"[ANS[")
            end = buffer.find(b"]ANS]")
            if start != -1 and end != -1 and end > start:
                return bytes(buffer[start + 5:end])

    def wait_for_close(self, timeout=2.0):
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                data = self.sock.recv(1)
                if not data:
                    return True
            except socket.timeout:
                continue
            except OSError:
                break
        return False


def send_command(port, parts):
    with RawClient(port) as client:
        client.send_command(parts)
        return client.read_answer()


def wait_for_condition(predicate, timeout=3.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _get_free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


def _wait_for_server(port, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("Server did not start listening in time")


@pytest.fixture()
def pdem_server():
    port = _get_free_port()
    app = pdem.PdemServerApp({
        "listenAddr": "127.0.0.1",
        "listenPort": port,
        "daemonize": False,
        "logLevel": pdem.logging.ERROR,
    })

    loop_holder = {}
    ready = threading.Event()

    def run_server():
        asyncio_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(asyncio_loop)
        loop = pdem.IOLoop.current()
        loop_holder["loop"] = loop
        ready.set()
        app.run()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    ready.wait(timeout=5)
    _wait_for_server(port)

    yield ServerHandle(app, port, thread, loop_holder)

    loop = loop_holder.get("loop")
    if thread.is_alive():
        if loop is not None:
            loop.add_callback(app.die)
        thread.join(timeout=5)
    else:
        thread.join(timeout=5)


def test_runprocess_and_proclist(tmp_path: Path, pdem_server: ServerHandle):
    script = tmp_path / "worker.py"
    script.write_text(
        "import sys\n"
        "import time\n"
        "print('[PDEM[progressenabled]PDEM]', flush=True)\n"
        "for value in (25, 50, 75, 100):\n"
        "    print(f'[PDEM[progress={value}]PDEM]', flush=True)\n"
        "    time.sleep(0.05)\n"
        "print('[PDEM[var:state=done]PDEM]', flush=True)\n"
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = pdem.PdemClient("127.0.0.1", pdem_server.port, autoIOLoop=True)
    command = f"{sys.executable} {script}"
    client.runprocess("testproc", "Test Process", command)

    time.sleep(0.5)

    results = []

    def store_results(data):
        results.append(data)

    client.proclist(store_results, showdead=True)

    assert results, "Expected proclist callback to be invoked"
    processes = results[0]
    assert "testproc" in processes

    process_info = processes["testproc"]
    assert process_info["title"] == "Test Process"
    assert process_info["is_supportsprogress"] is True
    assert process_info["progress"] == 100
    assert process_info["is_alive"] is False
    assert process_info["vars"].get("state") == "done"

    if client.stream is not None:
        client.stream.close()
        wait_for_condition(
            lambda: len(pdem_server.app.server.manager.connections) == 0,
            timeout=2.0,
        )
    loop.close()


def test_help_command_returns_documentation(pdem_server: ServerHandle):
    response = send_command(
        pdem_server.port,
        ["help"],
    ).decode("utf-8")

    assert "pdem protocol help" in response
    assert "Commands and their descriptions" in response


def test_show_command_parses_arguments(pdem_server: ServerHandle):
    response = send_command(
        pdem_server.port,
        ["show", "kill", "my process", "mode=fast"],
    ).decode("utf-8")

    assert "Parse result" in response
    assert "Command:`kill`" in response
    assert "Parameter #1:`my process`" in response
    assert "Parameter #2:`mode=fast`" in response


def test_disconnect_command_closes_connection(pdem_server: ServerHandle):
    handle = pdem_server
    with RawClient(handle.port) as client:
        assert wait_for_condition(
            lambda: len(handle.app.server.manager.connections) == 1,
            timeout=2.0,
        )
        client.send_command(["disconnect"])
        assert client.wait_for_close()

    assert wait_for_condition(
        lambda: len(handle.app.server.manager.connections) == 0,
        timeout=2.0,
    )


def test_disconnectall_closes_all_connections(pdem_server: ServerHandle):
    handle = pdem_server
    client1 = RawClient(handle.port)
    assert wait_for_condition(
        lambda: len(handle.app.server.manager.connections) == 1,
        timeout=2.0,
    )
    client2 = RawClient(handle.port)
    assert wait_for_condition(
        lambda: len(handle.app.server.manager.connections) == 2,
        timeout=2.0,
    )

    client1.send_command(["disconnectall"])
    assert client1.wait_for_close()
    assert client2.wait_for_close()
    client1.close()
    client2.close()

    assert wait_for_condition(
        lambda: len(handle.app.server.manager.connections) == 0,
        timeout=2.0,
    )


def test_kill_command_terminates_process(tmp_path: Path, pdem_server: ServerHandle):
    handle = pdem_server
    script = tmp_path / "long_task.py"
    script.write_text(
        "import time\n"
        "while True:\n"
        "    time.sleep(0.5)\n"
    )

    command = f"{sys.executable} {script}"
    response = send_command(
        handle.port,
        ["runprocess", "longproc", "Long Process", "local", command],
    )
    assert response == b"OK"

    assert wait_for_condition(
        lambda: (
            handle.app.server.processes.get_proc_by_name("longproc") is not None
            and handle.app.server.processes.get_proc_by_name("longproc").alive
        ),
        timeout=3.0,
    )

    with RawClient(handle.port) as client:
        client.send_command(["kill", "longproc"])
        time.sleep(0.2)

    assert wait_for_condition(
        lambda: (
            handle.app.server.processes.get_proc_by_name("longproc") is not None
            and not handle.app.server.processes.get_proc_by_name("longproc").alive
        ),
        timeout=3.0,
    )


def test_burndead_removes_finished_processes(tmp_path: Path, pdem_server: ServerHandle):
    handle = pdem_server
    script = tmp_path / "short_task.py"
    script.write_text("print('done', flush=True)\n")

    command = f"{sys.executable} {script}"
    response = send_command(
        handle.port,
        ["runprocess", "shortproc", "Short Process", "local", command],
    )
    assert response == b"OK"

    assert wait_for_condition(
        lambda: (
            handle.app.server.processes.get_proc_by_name("shortproc") is not None
            and not handle.app.server.processes.get_proc_by_name("shortproc").alive
        ),
        timeout=3.0,
    )

    with RawClient(handle.port) as client:
        client.send_command(["burndead"])
        time.sleep(0.2)

    assert wait_for_condition(
        lambda: handle.app.server.processes.get_proc_by_name("shortproc") is None,
        timeout=3.0,
    )


def test_quit_command_stops_server(pdem_server: ServerHandle):
    handle = pdem_server
    with RawClient(handle.port) as client:
        client.send_command(["quit"])
        client.wait_for_close(timeout=5.0)

    handle.thread.join(timeout=5)
    assert not handle.thread.is_alive()
    assert handle.app.server is None
