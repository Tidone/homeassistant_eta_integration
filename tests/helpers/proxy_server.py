#!/usr/bin/env python3

"""Interactive proxy server for testing ETA integration with node state changes.

Forwards all /user/menu, /user/var/<node>, and /user/varinfo/<node> requests
to an external ETA device, with selectable override modes for a specific node.

Modes (switch with key presses):
  1 — Pass-through: all requests forwarded to the external server
  2 — Valid node:   /user/var//40/10021/0/11108/0 and
                    /user/varinfo//40/10021/0/11108/0 return the "valid"
                    fixture from changing_endpoint.json; rest are forwarded
  3 — Invalid node: same paths return the "invalid" fixture; rest forwarded

Usage:
  python proxy_server.py --host 192.168.0.25
  python proxy_server.py --host 192.168.0.25 --port 8080 --listen-port 8081
"""

import argparse
import json
import logging
import sys
import termios
import threading
from pathlib import Path

from aiohttp import web
import aiohttp

SCRIPT_DIR = Path(__file__).parent
FIXTURE_PATH = SCRIPT_DIR / "../fixtures/changing_endpoint.json"

OVERRIDE_PATHS = {
    "/user/var//40/10021/0/11108/0",
    "/user/varinfo//40/10021/0/11108/0",
}

# Shared mutable state — written only from the keyboard thread, read from handlers
_mode = 1  # 1 = pass-through, 2 = valid, 3 = invalid
_mode_lock = threading.Lock()


def get_mode() -> int:
    with _mode_lock:
        return _mode


def set_mode(m: int):
    global _mode
    with _mode_lock:
        _mode = m


def load_fixture(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def mode_label(m: int) -> str:
    return {1: "pass-through", 2: "valid node", 3: "invalid node"}.get(m, "?")


def keyboard_thread(fixture: dict):
    """Read single keypresses and switch the proxy mode."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        # Disable canonical mode and echo, but keep output processing (OPOST/ONLCR)
        # so that \n is still translated to \r\n and output stays aligned.
        new = termios.tcgetattr(fd)
        new[3] &= ~(termios.ECHO | termios.ICANON)  # c_lflag
        new[6][termios.VMIN] = 1
        new[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSADRAIN, new)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("q", "\x03"):  # q or Ctrl-C
                print("\r\nExiting...\r\n", flush=True)
                import os, signal
                os.kill(os.getpid(), signal.SIGTERM)
                break
            elif ch == "1":
                set_mode(1)
                print(f"\r\n[mode] 1 — pass-through\r\n", flush=True)
            elif ch == "2":
                set_mode(2)
                print(f"\r\n[mode] 2 — valid node\r\n", flush=True)
            elif ch == "3":
                set_mode(3)
                print(f"\r\n[mode] 3 — invalid node\r\n", flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


async def proxy_request(
    request: web.Request,
    upstream_base: str,
    fixture: dict,
    session: aiohttp.ClientSession,
) -> web.Response:
    path = request.path
    mode = get_mode()

    # In mode 2/3, intercept the special override paths
    if mode in (2, 3) and path in OVERRIDE_PATHS:
        key = "valid" if mode == 2 else "invalid"
        body = fixture[key].get(path)
        if body is not None:
            logging.debug(f"[mode {mode}] serving fixture for {path}")
            return web.Response(
                text=body,
                content_type="application/xml",
                charset="utf-8",
            )

    # Forward to upstream
    upstream_url = upstream_base + path
    if request.query_string:
        upstream_url += "?" + request.query_string

    logging.debug(f"[mode {mode}] forwarding {path} -> {upstream_url}")
    try:
        async with session.get(
            upstream_url,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            body = await resp.read()
            content_type = resp.content_type or "application/xml"
            return web.Response(
                body=body,
                status=resp.status,
                content_type=content_type,
            )
    except Exception as exc:
        logging.warning(f"Upstream error for {path}: {exc}")
        return web.Response(status=502, text=f"Upstream error: {exc}")


def make_app(upstream_base: str, fixture: dict, session: aiohttp.ClientSession) -> web.Application:
    app = web.Application()

    async def handle(request: web.Request) -> web.Response:
        return await proxy_request(request, upstream_base, fixture, session)

    app.router.add_get("/user/errors", handle)
    app.router.add_get("/user/api", handle)
    app.router.add_get("/user/menu", handle)
    app.router.add_get(r"/user/var/{node:.*}", handle)
    app.router.add_get(r"/user/varinfo/{node:.*}", handle)

    return app


async def run(host: str, port: int, listen_port: int, fixture: dict):
    upstream_base = f"http://{host}:{port}"

    async with aiohttp.ClientSession() as session:
        app = make_app(upstream_base, fixture, session)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", listen_port)
        await site.start()

        print(f"Proxy listening on http://0.0.0.0:{listen_port}")
        print(f"Upstream:         {upstream_base}")
        print(f"Mode:             1 — pass-through  [active]")
        print()
        print("Keys:  1=pass-through  2=valid node  3=invalid node  q=quit")
        print()

        # Block until the server is stopped (SIGTERM/SIGINT handled by aiohttp)
        import asyncio
        stop = asyncio.Event()

        import signal

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        await stop.wait()
        await runner.cleanup()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Interactive ETA proxy server with mode switching",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--host", required=True, help="Upstream ETA device hostname or IP")
    parser.add_argument(
        "--port", type=int, default=8080, help="Upstream ETA device port (default: 8080)"
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=8081,
        help="Local port to listen on (default: 8081)",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=FIXTURE_PATH,
        help=f"Path to changing_endpoint.json (default: {FIXTURE_PATH})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    fixture = load_fixture(args.fixture)

    # Start keyboard listener in a daemon thread so it dies with the process
    kb = threading.Thread(target=keyboard_thread, args=(fixture,), daemon=True)
    kb.start()

    import asyncio
    asyncio.run(run(args.host, args.port, args.listen_port, fixture))


if __name__ == "__main__":
    main()
