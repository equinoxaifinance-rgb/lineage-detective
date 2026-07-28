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
VENV = os.path.join(HERE, ".venv")
SIDECAR_VENV = os.path.join(HERE, ".datahub-mcp-venv")
RUNTIME_LOCK = os.path.join(HERE, "requirements-runtime.lock")
SIDECAR_LOCK = os.path.join(HERE, "requirements-datahub-sidecar.lock")
UNIFIED_LOCK = os.path.join(HERE, "requirements-datahub-unified.lock")
DATAHUB_PACKAGE_SPEC = os.environ.get("LINEAGE_DATAHUB_PACKAGE", "acryl-datahub==1.6.0.15")
MCP_PACKAGE_SPEC = os.environ.get("LINEAGE_MCP_PACKAGE", "mcp-server-datahub==0.6.0")


def venv_python() -> str:
    return (os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt"
            else os.path.join(VENV, "bin", "python"))


def sidecar_python() -> str:
    return (os.path.join(SIDECAR_VENV, "Scripts", "python.exe") if os.name == "nt"
            else os.path.join(SIDECAR_VENV, "bin", "python"))


def sidecar_mcp_command() -> str:
    return os.path.join(os.path.dirname(sidecar_python()), "mcp-server-datahub.exe" if os.name == "nt" else "mcp-server-datahub")


def enter_project_venv() -> None:
    """Re-exec inside .venv so setup never mutates the caller's global Python."""
    if os.environ.get("LINEAGE_DETECTIVE_IN_VENV") == "1":
        return
    py = venv_python()
    if not os.path.exists(py):
        say("Creating isolated project environment (.venv)")
        result = subprocess.run([sys.executable, "-m", "venv", VENV], cwd=HERE)
        if result.returncode != 0:
            die("Could not create .venv. Install Python with the venv module, then re-run.")
    env = dict(os.environ)
    env["LINEAGE_DETECTIVE_IN_VENV"] = "1"
    env["PATH"] = os.path.dirname(py) + os.pathsep + env.get("PATH", "")
    raise SystemExit(
        subprocess.run(
            [py, os.path.abspath(__file__), *sys.argv[1:]],
            cwd=HERE,
            env=env,
        ).returncode
    )


def ensure_sidecar_venv() -> str:
    """Build the narrow environment that owns DataHub CLI/SDK/MCP dependencies."""
    py = sidecar_python()
    if not os.path.exists(py):
        say("Creating isolated DataHub MCP sidecar (.datahub-mcp-venv)")
        result = subprocess.run([sys.executable, "-m", "venv", SIDECAR_VENV], cwd=HERE)
        if result.returncode != 0:
            die("Could not create the DataHub sidecar environment.")
    require_run([py, "-m", "pip", "install", "--require-hashes", "--progress-bar", "off",
                 "--timeout", "30", "--retries", "1", "-r", SIDECAR_LOCK],
                "Could not install DataHub sidecar dependencies")
    if not os.path.exists(sidecar_mcp_command()):
        die("The DataHub MCP sidecar installed without its console command.")
    return py


def upstream_supports_fixed_runtime() -> bool:
    """Ask pip's resolver whether the selected DataHub release can use setuptools>=83.

    This is a dry resolution only: it does not modify either environment. A future
    DataHub release that removes its <82 cap automatically takes the unified path.
    """
    probe = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
         "--disable-pip-version-check", DATAHUB_PACKAGE_SPEC, "setuptools>=83"],
        cwd=HERE, capture_output=True, text=True,
    )
    return probe.returncode == 0


def resolve_datahub_compatibility() -> tuple[str, str, str]:
    """Choose a seamless unified or isolated DataHub toolchain.

    The app always sees one MCP command. The isolated route is selected only when
    the upstream package metadata rejects the fixed setuptools runtime.
    """
    requested = os.environ.get("LINEAGE_DATAHUB_COMPAT_MODE", "auto").lower()
    if requested not in {"auto", "unified", "isolated"}:
        die("LINEAGE_DATAHUB_COMPAT_MODE must be auto, unified, or isolated.")
    supported = upstream_supports_fixed_runtime()
    if requested == "unified" and not supported:
        die("DataHub's current package metadata rejects setuptools>=83; unified mode is unavailable. Use auto.")
    unified_lock_is_current = (
        os.path.isfile(UNIFIED_LOCK)
        and MCP_PACKAGE_SPEC in open(UNIFIED_LOCK, encoding="utf-8").read()
        and DATAHUB_PACKAGE_SPEC in open(UNIFIED_LOCK, encoding="utf-8").read()
    )
    if requested == "unified" and not unified_lock_is_current:
        die("Unified mode requires a reviewed hash lock for the selected DataHub and MCP versions. "
            "Use auto until requirements-datahub-unified.lock is regenerated and reviewed.")
    if (requested == "unified" or (requested == "auto" and supported)) and unified_lock_is_current:
        say("DataHub supports the fixed runtime; installing hash-locked unified MCP tooling")
        require_run([sys.executable, "-m", "pip", "install", "-q", "--require-hashes", "-r", UNIFIED_LOCK],
                    "Could not install hash-locked unified DataHub tooling")
        command = os.path.join(os.path.dirname(sys.executable), "mcp-server-datahub.exe" if os.name == "nt" else "mcp-server-datahub")
        if not os.path.exists(command):
            die("Unified DataHub tooling installed without its MCP command.")
        return sys.executable, command, "unified-fixed-runtime"

    if supported and not unified_lock_is_current:
        say("DataHub supports a fixed runtime but no reviewed unified hash lock exists; using the equivalent isolated MCP route")
    sidecar_py = ensure_sidecar_venv()
    return sidecar_py, sidecar_mcp_command(), "isolated-upstream-compatibility"


def say(msg): print(f"\n\033[96m>> {msg}\033[0m" if os.name != "nt" else f"\n>> {msg}", flush=True)
def ok(msg):  print(f"   [ok] {msg}", flush=True)
def die(msg): print(f"\n   [X] {msg}\n", flush=True); sys.exit(1)


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=HERE, **kw)


def require_run(cmd, failure_message, **kw):
    """Stop rather than printing a false success after a failed setup command."""
    result = run(cmd, **kw)
    if result.returncode != 0:
        die(f"{failure_message} (exit {result.returncode}). See the command output above, fix it, then re-run.")
    return result


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
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(
            "Lineage Detective self-hosted quickstart\n\n"
            "Usage:\n"
            "  python quickstart.py\n\n"
            "Requires Docker Desktop. Creates project-local Python environments, starts "
            "DataHub Quickstart, seeds the three reproducible incidents, and launches "
            "the app at http://localhost:8501. Re-running resumes safely."
        )
        return
    enter_project_venv()
    load_dotenv()
    print("=" * 68)
    print("  LINEAGE DETECTIVE — one-command setup")
    print("=" * 68)

    # 1. Prerequisites we can't install ------------------------------------------------
    say("Checking prerequisites")
    if os.environ.get("ANTHROPIC_API_KEY"):
        ok("Anthropic API key found: model-backed reasoning will be available")
    else:
        ok("No model key: starting the free, read-only evidence-only judge path")
    if shutil.which("docker") is None:
        die("Docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop")
    if run(["docker", "ps"], capture_output=True).returncode != 0:
        die("Docker is installed but not running. Start Docker Desktop, wait for it to say 'running', re-run.")
    ok("Docker is running")
    # 2. Isolated dependencies ---------------------------------------------------------
    say("Installing hash-locked Python dependencies")
    require_run([sys.executable, "-m", "pip", "install", "-q", "--require-hashes", "-r", RUNTIME_LOCK],
                "Could not install the project dependencies")
    ok("dependencies installed in .venv")
    datahub_py, mcp_command, compatibility_mode = resolve_datahub_compatibility()
    ok(f"DataHub compatibility route: {compatibility_mode}")

    # 3. DataHub up --------------------------------------------------------------------
    if gms_healthy():
        ok(f"DataHub already up at {GMS}")
    else:
        say("Starting a local DataHub (first run downloads containers — a few minutes)")
        require_run([datahub_py, "-m", "datahub", "docker", "quickstart"], "DataHub quickstart failed")
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
    if run([datahub_py, os.path.join(HERE, "seed_demo.py")]).returncode != 0:
        die("Seeding failed — see the error above.")
    ok("demo incidents planted")

    # 5. Launch the app ----------------------------------------------------------------
    os.environ.setdefault("DATAHUB_GMS_URL", GMS)
    os.environ.setdefault("DATAHUB_SERVER", GMS)
    # These values are selected by the resolver above.  Set them explicitly so
    # a stale shell variable cannot silently send the judge to an unrelated MCP
    # installation.  The executable gets its own variable so Windows paths
    # containing spaces never need fragile command-line splitting.
    os.environ["DATAHUB_MCP_EXECUTABLE"] = mcp_command
    os.environ["DATAHUB_BOOTSTRAP_PYTHON"] = datahub_py
    os.environ["LINEAGE_DATAHUB_COMPAT_ACTIVE"] = compatibility_mode
    os.environ["LINEAGE_RUN_MODE"] = "self_hosted"
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
