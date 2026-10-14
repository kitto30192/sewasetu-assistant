"""
Local startup helper for Sewa Setu (no Docker).

Usage:
    python run_local.py          # starts all local application services
    python run_local.py --setup  # creates the SQLite DB, loads schema & seed, then starts
"""

import os
import sys
import subprocess
import time
import signal
import socket

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(ROOT, "app")
SMSGW_DIR = os.path.join(ROOT, "smsgw")


def setup_database():
    """Create the local SQLite database, schema, and seed data."""
    setup_script = os.path.join(APP_DIR, "scripts", "setup_local_db.py")
    subprocess.run([sys.executable, setup_script], cwd=APP_DIR, check=True)


def start_services():
    """Start every service required for the local portal and AI assistant."""
    # Use the local config
    app_env = os.environ.copy()
    app_env["ADMIN_USERNAME"] = os.environ.get("ADMIN_USERNAME", "admin")
    app_env["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "admin123")
    app_env["PUBLIC_BASE_URL"] = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
    app_env["CITIZEN_MCP_URL"] = os.environ.get(
        "CITIZEN_MCP_URL", "http://127.0.0.1:8101/sse"
    )
    app_env["OFFICER_MCP_URL"] = os.environ.get(
        "OFFICER_MCP_URL", "http://127.0.0.1:8102/sse"
    )
    app_env["AI_AGENT_URL"] = os.environ.get("AI_AGENT_URL", "http://127.0.0.1:8200")

    python = sys.executable
    procs = []

    def cleanup(sig=None, frame=None):
        print("\nShutting down...")
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    # Patch app.py to use local config at runtime
    # We'll set an env var that app.py can check
    app_env["SEWASETU_LOCAL"] = "1"

    def start_service(name, script, cwd, port, extra_env=None):
        service_env = app_env.copy()
        if extra_env:
            service_env.update(extra_env)
        print(f"Starting {name} on port {port}...")
        process = subprocess.Popen([python, script], cwd=cwd, env=service_env)
        procs.append(process)
        deadline = time.time() + 30
        while time.time() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"{name} exited with code {process.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return process
            except OSError:
                time.sleep(0.25)
        raise RuntimeError(f"{name} did not start on port {port}")

    try:
        start_service("SMS gateway", "app.py", SMSGW_DIR, 8025)
        start_service(
            "citizen MCP server", "citizen_mcp.py", ROOT, 8101,
            {"MCP_PORT": "8101"},
        )
        start_service(
            "officer MCP server", "officer_mcp.py", ROOT, 8102,
            {"MCP_PORT": "8102"},
        )
        start_service(
            "AI agent", "ai_agent.py", ROOT, 8200,
            {"AI_AGENT_PORT": "8200"},
        )

        print("Starting Sewa Setu portal on port 8000...")
        print(f"  Admin login: {app_env['ADMIN_USERNAME']} / {app_env['ADMIN_PASSWORD']}")
        print(f"  Portal: http://localhost:8000")
        print(f"  SMS Console: http://localhost:8000/__gateway/")
        print(f"  Admin: http://localhost:8000/admin")
        print(f"  AI assistant: http://localhost:8000/ (open the chat panel)")
        print()

        start_service("Sewa Setu portal", "app.py", APP_DIR, 8000)
    except Exception:
        cleanup()
        raise
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        # Wait for either process to exit
        while True:
            for p in procs:
                ret = p.poll()
                if ret is not None:
                    print(f"Process {p.pid} exited with code {ret}")
                    cleanup()
                    raise SystemExit(ret or 1)
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    if "--setup" in sys.argv:
        setup_database()
    start_services()
