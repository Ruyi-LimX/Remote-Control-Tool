#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import secrets
import socket
import sys
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"


@dataclass(frozen=True)
class HostConfig:
    bind: str
    port: int
    password: str
    token_ttl: int
    fps: int
    quality: int
    max_width: int
    monitor: int


AUTH_FAIL_LIMIT = 8
AUTH_FAIL_WINDOW_SECONDS = 5 * 60


class InputController:
    def __init__(self) -> None:
        self._pyautogui = None

    def _pg(self):
        if self._pyautogui is None:
            if sys.platform.startswith("linux"):
                try:
                    self._pyautogui = X11InputBackend()
                    return self._pyautogui
                except Exception as exc:
                    print(f"X11 input backend unavailable: {exc}", file=sys.stderr)

            import pyautogui

            pyautogui.FAILSAFE = False
            self._pyautogui = pyautogui
        return self._pyautogui

    def _point(self, event: dict[str, Any]) -> tuple[int | None, int | None]:
        x = event.get("x")
        y = event.get("y")
        if x is None or y is None:
            return None, None

        pg = self._pg()
        width, height = pg.size()
        fx = float(x)
        fy = float(y)
        if 0 <= fx <= 1 and 0 <= fy <= 1:
            return int(fx * width), int(fy * height)
        return int(fx), int(fy)

    def dispatch(self, event: dict[str, Any]) -> dict[str, Any]:
        pg = self._pg()
        event_type = str(event.get("type", ""))

        if event_type == "move_abs":
            x, y = self._point(event)
            if x is None or y is None:
                raise ValueError("move_abs requires x and y")
            pg.moveTo(x, y, duration=0)
        elif event_type == "move_rel":
            pg.moveRel(int(event.get("dx", 0)), int(event.get("dy", 0)), duration=0)
        elif event_type == "mouse_down":
            self._move_if_present(event)
            pg.mouseDown(button=self._button(event))
        elif event_type == "mouse_up":
            self._move_if_present(event)
            pg.mouseUp(button=self._button(event))
        elif event_type == "click":
            self._move_if_present(event)
            pg.click(button=self._button(event))
        elif event_type == "double_click":
            self._move_if_present(event)
            pg.doubleClick(button=self._button(event))
        elif event_type == "right_click":
            self._move_if_present(event)
            pg.click(button="right")
        elif event_type == "scroll":
            pg.scroll(int(event.get("clicks", 0)))
        elif event_type == "key":
            key = str(event.get("key", "")).strip()
            if not key:
                raise ValueError("key event requires key")
            pg.press(key)
        elif event_type == "hotkey":
            keys = event.get("keys")
            if not isinstance(keys, list) or not keys:
                raise ValueError("hotkey event requires keys")
            pg.hotkey(*[str(key) for key in keys])
        elif event_type == "paste_text":
            self._paste_text(str(event.get("value", "")))
        else:
            raise ValueError(f"unsupported control event: {event_type}")

        return {"ok": True}

    def _move_if_present(self, event: dict[str, Any]) -> None:
        x, y = self._point(event)
        if x is not None and y is not None:
            self._pg().moveTo(x, y, duration=0)

    @staticmethod
    def _button(event: dict[str, Any]) -> str:
        button = str(event.get("button", "left"))
        if button not in {"left", "middle", "right"}:
            return "left"
        return button

    def _paste_text(self, value: str) -> None:
        if not value:
            return

        pg = self._pg()
        try:
            import pyperclip

            pyperclip.copy(value)
            pg.hotkey("ctrl", "v")
        except Exception:
            pg.write(value, interval=0)


class X11InputBackend:
    def __init__(self) -> None:
        from Xlib.display import Display

        self._display = Display(os.environ.get("DISPLAY", ":0"))
        self._screen = self._display.screen()

    def size(self) -> tuple[int, int]:
        return self._screen.width_in_pixels, self._screen.height_in_pixels

    def moveTo(self, x: int, y: int, duration: float = 0) -> None:
        del duration
        from Xlib import X
        from Xlib.ext.xtest import fake_input

        fake_input(self._display, X.MotionNotify, x=int(x), y=int(y))
        self._display.sync()

    def moveRel(self, dx: int, dy: int, duration: float = 0) -> None:
        del duration
        pos = self._display.screen().root.query_pointer()._data
        self.moveTo(int(pos["root_x"]) + int(dx), int(pos["root_y"]) + int(dy))

    def mouseDown(self, button: str = "left") -> None:
        from Xlib import X
        from Xlib.ext.xtest import fake_input

        fake_input(self._display, X.ButtonPress, self._button_number(button))
        self._display.sync()

    def mouseUp(self, button: str = "left") -> None:
        from Xlib import X
        from Xlib.ext.xtest import fake_input

        fake_input(self._display, X.ButtonRelease, self._button_number(button))
        self._display.sync()

    def click(self, button: str = "left") -> None:
        self.mouseDown(button)
        self.mouseUp(button)

    def doubleClick(self, button: str = "left") -> None:
        self.click(button)
        time.sleep(0.04)
        self.click(button)

    def scroll(self, clicks: int) -> None:
        button = "scroll_up" if clicks > 0 else "scroll_down"
        for _ in range(min(abs(int(clicks)), 30)):
            self.click(button)

    def press(self, key: str) -> None:
        self._key(key, True)
        self._key(key, False)

    def hotkey(self, *keys: str) -> None:
        for key in keys:
            self._key(key, True)
        for key in reversed(keys):
            self._key(key, False)

    def write(self, value: str, interval: float = 0) -> None:
        for char in value:
            self.press(char)
            if interval:
                time.sleep(interval)

    def _key(self, key: str, down: bool) -> None:
        from Xlib import X
        from Xlib.ext.xtest import fake_input
        import Xlib.XK

        aliases = {
            "esc": "Escape",
            "escape": "Escape",
            "space": "space",
            "enter": "Return",
            "return": "Return",
            "ctrl": "Control_L",
            "control": "Control_L",
            "alt": "Alt_L",
            "shift": "Shift_L",
            "tab": "Tab",
            "backspace": "BackSpace",
            "delete": "Delete",
            "del": "Delete",
            "left": "Left",
            "right": "Right",
            "up": "Up",
            "down": "Down",
            "home": "Home",
            "end": "End",
            "pageup": "Page_Up",
            "pagedown": "Page_Down",
            "win": "Super_L",
        }
        keysym_name = aliases.get(key.lower(), key)
        keysym = Xlib.XK.string_to_keysym(keysym_name)
        keycode = self._display.keysym_to_keycode(keysym)
        if not keycode:
            raise ValueError(f"unsupported key: {key}")
        fake_input(self._display, X.KeyPress if down else X.KeyRelease, keycode)
        self._display.sync()

    @staticmethod
    def _button_number(button: str) -> int:
        return {
            "left": 1,
            "middle": 2,
            "right": 3,
            "scroll_up": 4,
            "scroll_down": 5,
        }.get(button, 1)


class HostApp:
    def __init__(self, config: HostConfig) -> None:
        self.config = config
        self.input = InputController()
        self.tokens: dict[str, float] = {}
        self.auth_failures: dict[str, list[float]] = {}

    def create_token(self, password: str) -> str | None:
        if not hmac.compare_digest(password, self.config.password):
            return None
        token = secrets.token_urlsafe(32)
        self.tokens[token] = time.monotonic() + self.config.token_ttl
        return token

    def is_token_valid(self, token: str | None) -> bool:
        if not token:
            return False

        expires_at = self.tokens.get(token)
        if expires_at is None:
            return False
        if expires_at < time.monotonic():
            self.tokens.pop(token, None)
            return False
        return True

    def is_auth_limited(self, client_key: str) -> bool:
        return len(self._recent_auth_failures(client_key)) >= AUTH_FAIL_LIMIT

    def record_auth_failure(self, client_key: str) -> None:
        failures = self._recent_auth_failures(client_key)
        failures.append(time.monotonic())
        self.auth_failures[client_key] = failures

    def record_auth_success(self, client_key: str) -> None:
        self.auth_failures.pop(client_key, None)

    def _recent_auth_failures(self, client_key: str) -> list[float]:
        cutoff = time.monotonic() - AUTH_FAIL_WINDOW_SECONDS
        failures = [ts for ts in self.auth_failures.get(client_key, []) if ts >= cutoff]
        if failures:
            self.auth_failures[client_key] = failures
        else:
            self.auth_failures.pop(client_key, None)
        return failures

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "fps": self.config.fps,
            "quality": self.config.quality,
            "maxWidth": self.config.max_width,
            "monitor": self.config.monitor,
            "tokenTtl": self.config.token_ttl,
            "lanIp": guess_lan_ip(),
        }


class RemoteRequestHandler(BaseHTTPRequestHandler):
    server_version = "PersonalRemote/0.1"

    @property
    def app(self) -> HostApp:
        return self.server.app  # type: ignore[attr-defined]

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._send_json(self.app.status())
            return
        if parsed.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if parsed.path == "/frame.jpg":
            self._send_screen_frame(parsed.query)
            return
        if parsed.path == "/stream":
            self._stream_screen(parsed.query)
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth":
            self._handle_auth()
            return
        if parsed.path == "/api/control":
            self._handle_control()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _handle_auth(self) -> None:
        client_key = self._client_key()
        if self.app.is_auth_limited(client_key):
            self._send_json({"ok": False, "error": "too_many_attempts"}, HTTPStatus.TOO_MANY_REQUESTS)
            return

        body = self._read_json()
        token = self.app.create_token(str(body.get("password", "")))
        if token is None:
            self.app.record_auth_failure(client_key)
            self._send_json({"ok": False, "error": "bad_password"}, HTTPStatus.UNAUTHORIZED)
            return
        self.app.record_auth_success(client_key)
        self._send_json({"ok": True, "token": token, "status": self.app.status()})

    def _handle_control(self) -> None:
        body = self._read_json()
        if not self._authorized(body=body):
            self._send_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            result = self.app.input.dispatch(body)
        except Exception as exc:
            print(f"control event failed: {exc}; event={body}", file=sys.stderr)
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result)

    def _stream_screen(self, query: str) -> None:
        token = parse_qs(query).get("token", [None])[0]
        if not self.app.is_token_valid(token):
            self.send_error(HTTPStatus.UNAUTHORIZED)
            return

        try:
            import mss
            from PIL import Image
        except Exception as exc:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"missing screen dependency: {exc}")
            return

        boundary = "frame"
        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        self.end_headers()

        frame_delay = 1 / max(1, self.app.config.fps)
        try:
            with mss.MSS() as sct:
                monitor_index = min(max(0, self.app.config.monitor), len(sct.monitors) - 1)
                monitor = sct.monitors[monitor_index]
                while True:
                    started = time.monotonic()
                    frame = self._capture_frame_jpeg(sct, monitor, Image)

                    self.wfile.write(f"--{boundary}\r\n".encode("ascii"))
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()

                    elapsed = time.monotonic() - started
                    if elapsed < frame_delay:
                        time.sleep(frame_delay - elapsed)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_screen_frame(self, query: str) -> None:
        token = parse_qs(query).get("token", [None])[0]
        if not self.app.is_token_valid(token):
            self.send_error(HTTPStatus.UNAUTHORIZED)
            return

        try:
            import mss
            from PIL import Image
        except Exception as exc:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"missing screen dependency: {exc}")
            return

        try:
            with mss.MSS() as sct:
                monitor_index = min(max(0, self.app.config.monitor), len(sct.monitors) - 1)
                monitor = sct.monitors[monitor_index]
                frame = self._capture_frame_jpeg(sct, monitor, Image)
        except Exception as exc:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"screen capture failed: {exc}")
            return

        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(frame)))
        self.end_headers()
        self.wfile.write(frame)

    def _capture_frame_jpeg(self, sct, monitor: dict[str, Any], image_module) -> bytes:
        shot = sct.grab(monitor)
        image = image_module.frombytes("RGB", shot.size, shot.rgb)
        image = self._resize_image(image)
        image = self._decorate_black_capture(image)
        return self._encode_jpeg(image)

    def _resize_image(self, image):
        max_width = self.app.config.max_width
        if max_width <= 0 or image.width <= max_width:
            return image

        height = int(image.height * (max_width / image.width))
        from PIL import Image as PILImage

        resample = getattr(PILImage, "Resampling", PILImage).BILINEAR
        return image.resize((max_width, height), resample)

    def _encode_jpeg(self, image) -> bytes:
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=self.app.config.quality, optimize=True)
        return buffer.getvalue()

    def _decorate_black_capture(self, image):
        if image.getbbox() is not None or os.getenv("XDG_SESSION_TYPE") != "wayland":
            return image

        from PIL import ImageDraw

        image = image.copy()
        draw = ImageDraw.Draw(image)
        lines = [
            "Screen capture is black.",
            "GNOME Wayland blocks this simple MSS capture backend.",
            "Fix: log out, click the gear icon, choose 'Ubuntu on Xorg',",
            "then start Personal Remote again.",
        ]
        padding = 24
        line_height = 24
        box_height = padding * 2 + line_height * len(lines)
        draw.rectangle((0, 0, image.width, box_height), fill=(20, 31, 41))
        y = padding
        for line in lines:
            draw.text((padding, y), line, fill=(246, 248, 250))
            y += line_height
        return image

    def _serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            relative = "index.html"
        else:
            relative = path.lstrip("/")

        file_path = (WEB_DIR / relative).resolve()
        if not file_path.is_relative_to(WEB_DIR.resolve()) or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _authorized(self, body: dict[str, Any] | None = None) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return self.app.is_token_valid(auth.split(" ", 1)[1].strip())
        if body:
            return self.app.is_token_valid(str(body.get("token", "")))
        return False

    def _client_key(self) -> str:
        return self.client_address[0] if self.client_address else "unknown"

    def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")


class RemoteHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address: tuple[str, int], handler, app: HostApp) -> None:
        super().__init__(address, handler)
        self.app = app


def guess_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def random_password() -> str:
    return secrets.token_urlsafe(18)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Personal Android-to-PC remote control host")
    parser.add_argument("--bind", default="127.0.0.1", help="address to bind, default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=7070, help="port to listen on, default: 7070")
    parser.add_argument("--password", default=os.getenv("REMOTE_PASSWORD"), help="access password")
    parser.add_argument("--token-ttl", type=int, default=12 * 60 * 60, help="token lifetime in seconds")
    parser.add_argument("--fps", type=int, default=12, help="screen stream frames per second")
    parser.add_argument("--quality", type=int, default=70, help="JPEG quality, 1-95")
    parser.add_argument("--max-width", type=int, default=1280, help="resize stream width, 0 disables")
    parser.add_argument("--monitor", type=int, default=1, help="mss monitor index, 1 is primary")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    password = args.password or random_password()
    config = HostConfig(
        bind=args.bind,
        port=args.port,
        password=password,
        token_ttl=max(60, args.token_ttl),
        fps=max(1, args.fps),
        quality=min(95, max(1, args.quality)),
        max_width=max(0, args.max_width),
        monitor=max(0, args.monitor),
    )
    app = HostApp(config)
    server = RemoteHTTPServer((config.bind, config.port), RemoteRequestHandler, app)

    print("Personal Remote Host")
    print(f"Bind:      {config.bind}:{config.port}")
    print(f"Local URL: http://127.0.0.1:{config.port}")
    if config.bind not in {"127.0.0.1", "localhost"}:
        print(f"LAN URL:   http://{guess_lan_ip()}:{config.port}")
    print(f"Password:  {password}")
    print(f"Token TTL: {config.token_ttl}s")
    print(f"Tunnel:    cloudflared tunnel --url http://127.0.0.1:{config.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
