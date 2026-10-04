"""Small process client for protocol tests and nonstandard diagnostic commands."""
from __future__ import annotations

import collections
import pathlib
import queue
import subprocess
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_ENGINE = ROOT / "src/Engine/bin/Release/net8.0/Aster.dll"


def engine_command(path: str | pathlib.Path) -> list[str]:
    path = pathlib.Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Engine not found: {path}. Build the Release configuration first.")
    return ["dotnet", str(path)] if path.suffix.lower() == ".dll" else [str(path)]


class UciClient:
    def __init__(self, engine: str | pathlib.Path = DEFAULT_ENGINE):
        self.process = subprocess.Popen(
            engine_command(engine), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
        )
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.stderr: collections.deque[str] = collections.deque(maxlen=100)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.send("uci")
        handshake = self.until("uciok")
        self.name = next((line[8:] for line in handshake if line.startswith("id name ")), "unknown")
        self.ready()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line.strip())
        self.lines.put(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())

    def send(self, command: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def until(self, prefix: str, timeout: float = 10.0) -> list[str]:
        result: list[str] = []
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty as error:
                raise TimeoutError(f"Waiting for {prefix!r}: {result[-5:]}") from error
            if line is None:
                raise RuntimeError(f"Engine exited ({self.process.poll()}): {' '.join(self.stderr)}; output={result[-5:]}")
            result.append(line)
            if line.startswith(prefix):
                return result
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Waiting for {prefix!r}: {result[-5:]}")

    def ready(self) -> None:
        self.send("isready")
        self.until("readyok")

    def command(self, command: str, prefix: str, timeout: float = 10.0) -> str:
        self.send(command)
        return self.until(prefix, timeout)[-1]

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.send("quit")
                self.process.wait(timeout=3)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=3)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()

    def __enter__(self) -> "UciClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
