"""quickstart.py — one command to run Lineage Detective end to end.

    python quickstart.py

It checks prerequisites, installs Python deps, brings up a local DataHub, plants the demo
incidents, and launches the web app — then opens your browser. Safe to re-run; each step is
skipped if it's already done.

Two things it can't install for you (and will tell you plainly if they're missing):
  1) Docker Desktop must be running   — DataHub runs inside it.
  2) An Anthropic API key              — the agent's reasoning step. Set ANTHROPIC_API_KEY,
                                          or put it in a .env file next to this script.
"""
from __future__ import annotations
import os, sys, time, shutil, subprocess, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
GMS = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")


def say(msg): print(f"\n\033[96m>> {msg}\033[0m" if os.name != "nt" else f"\n>> {msg}", flush=True)
def ok(msg):  print(f"   [ok] {msg}", flush=True)
def die(msg): print(f"\n   [X] {msg}\n", flush=True); sys.exit(1)


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=HERE, **kw)


def load_dotenv():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def gms_healthy() -> bool:
    try:
        with urllib.request.urlopen(f"{GMS}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    load_dotenv()
    print("=" * 68)
    print("  LINEAGE DETECTIVE — one-command setup")
    print("=" * 68)

    # 1. Prerequisites we can't install ------------------------------------------------
    say("Checking prerequisites")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        die("ANTHROPIC_API_KEY is not set. Get a key at https://console.anthropic.com , then either\n"
            "       set it as an environment variable, or make a file named .env next to this script\n"
            "       containing:  ANTHROPIC_API_KEY=sk-ant-...")
    ok("Anthropic API key found")
    if shutil.which("docker") is None:
        die("Docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop")
    if run(["docker", "ps"], capture_output=True).returncode != 0:
        die("Docker is installed but not running. Start Docker Desktop, wait for it to say 'running', re-run.")
    ok("Docker is running")
    if shutil.which("uvx") is None and shutil.which("uv") is None:
        say("Installing 'uv' (used to launch DataHub's MCP server)")
        run([sys.executable, "-m", "pip", "install", "-q", "uv"])
    ok("uv/uvx available")

    # 2. Python deps -------------------------------------------------------------------
    say("Installing Python dependencies (requirements.txt)")
    run([sys.executable, "-m", "pip", "install", "-q", "-r", os.path.join(HERE, "requirements.txt")])
    ok("dependencies installed")

    # 3. DataHub up --------------------------------------------------------------------
    if gms_healthy():
        ok(f"DataHub already up at {GMS}")
    else:
        say("Starting a local DataHub (first run downloads containers — a few minutes)")
        run([sys.executable, "-m", "datahub", "docker", "quickstart"])
        say("Waiting for DataHub to be ready")
        for _ in range(120):
            if gms_healthy():
                break
            time.sleep(5)
        else:
            die("DataHub did not come up in time. Re-run this script; it resumes where it left off.")
        ok("DataHub is ready")

    # 4. Seed the demo incidents -------------------------------------------------------
    say("Planting the 3 demo incidents into DataHub")
    if run([sys.executable, os.path.join(HERE, "seed_demo.py")]).returncode != 0:
        die("Seeding failed — see the error above.")
    ok("demo incidents planted")

    # 5. Launch the app ----------------------------------------------------------------
    os.environ.setdefault("DATAHUB_GMS_URL", GMS)
    os.environ.setdefault("DATAHUB_SERVER", GMS)
    # Skip Streamlit's first-run "enter your email" prompt so the judge is never blocked.
    cred = os.path.join(os.path.expanduser("~"), ".streamlit", "credentials.toml")
    if not os.path.exists(cred):
        os.makedirs(os.path.dirname(cred), exist_ok=True)
        with open(cred, "w") as f:
            f.write('[general]\nemail = ""\n')
    say("Launching Lineage Detective at http://localhost:8501  (Ctrl+C to stop)")
    print("   DataHub catalog UI is at http://localhost:9002 — you'll see the tags the agent writes.\n")
    run([sys.executable, "-m", "streamlit", "run", os.path.join(HERE, "app.py"),
         "--server.port", "8501", "--browser.gatherUsageStats", "false"])


if __name__ == "__main__":
    main()
