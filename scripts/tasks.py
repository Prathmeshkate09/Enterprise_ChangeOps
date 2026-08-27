"""Cross-platform Phase 0 task runner used by Make and Windows developers."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / ".cache"
UV_CACHE = CACHE_ROOT / "uv"
UV_PYTHON_INSTALL_DIR = CACHE_ROOT / "uv-python"
NPM_CACHE = CACHE_ROOT / "npm"
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
NEXT_CLI = ROOT / "node_modules" / "next" / "dist" / "bin" / "next"


def command_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "UV_CACHE_DIR": str(UV_CACHE),
            "UV_PYTHON_INSTALL_DIR": str(UV_PYTHON_INSTALL_DIR),
            "NPM_CONFIG_CACHE": str(NPM_CACHE),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def executable(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise RuntimeError(f"Required executable is not installed or not on PATH: {name}")
    return resolved


def run(args: Sequence[str], *, environment: Mapping[str, str] | None = None) -> None:
    print(f"+ {' '.join(args)}", flush=True)
    env = command_environment()
    if environment is not None:
        env.update(environment)
    subprocess.run(args, cwd=ROOT, env=env, check=True)  # noqa: S603


def setup() -> None:
    CACHE_ROOT.mkdir(exist_ok=True)
    uv = executable("uv")
    npm = executable("npm")
    run([uv, "python", "install", "3.12", "--no-bin", "--no-registry"])
    run([uv, "sync", "--frozen", "--python", "3.12", "--all-packages", "--dev"])
    npm_action = "ci" if (ROOT / "package-lock.json").exists() else "install"
    run([npm, npm_action])


def lint() -> None:
    uv = executable("uv")
    npm = executable("npm")
    run([uv, "run", "ruff", "check", "."])
    run([uv, "run", "ruff", "format", "--check", "."])
    run(
        [
            uv,
            "run",
            "mypy",
            "enterprise-sandbox/src",
            "packages/contracts-python/src",
            "packages/changeops-core/src",
            "packages/persistence/src",
            "services/agent-fleet/src",
            "services/control-api/src",
            "scripts",
        ]
    )
    run([npm, "run", "lint"])
    run([npm, "run", "typecheck"])


def test() -> None:
    uv = executable("uv")
    npm = executable("npm")
    run([uv, "run", "pytest"])
    run([npm, "run", "test"])


def audit() -> None:
    uv = executable("uv")
    npm = executable("npm")
    requirements = CACHE_ROOT / "requirements-audit.txt"
    run(
        [
            uv,
            "export",
            "--frozen",
            "--all-packages",
            "--no-dev",
            "--no-emit-workspace",
            "--output-file",
            str(requirements),
            "--quiet",
        ]
    )
    run(
        [
            uv,
            "run",
            "pip-audit",
            "--requirement",
            str(requirements),
            "--disable-pip",
            "--vulnerability-service",
            "osv",
            "--timeout",
            "10",
            "--progress-spinner",
            "off",
        ]
    )
    run([npm, "audit", "--audit-level=high"])


def build() -> None:
    npm = executable("npm")
    run([npm, "run", "build"])


def sandbox_check() -> None:
    if not VENV_PYTHON.exists():
        raise RuntimeError("The Python environment is missing. Run the setup task first.")
    run([str(VENV_PYTHON), "scripts/sandbox_scenario.py"])


def persistence_check() -> None:
    if not VENV_PYTHON.exists():
        raise RuntimeError("The Python environment is missing. Run the setup task first.")
    docker = executable("docker")
    tenant_id = f"tenant_phase3_{uuid4().hex}"
    scenario_environment = {"PHASE3_TENANT_ID": tenant_id}
    run(
        [
            docker,
            "compose",
            "up",
            "-d",
            "--build",
            "--wait",
            "firestore-emulator",
            "control-api",
        ]
    )
    run(
        [str(VENV_PYTHON), "scripts/phase3_scenario.py", "seed"],
        environment=scenario_environment,
    )
    run([docker, "compose", "restart", "control-api"])
    run([docker, "compose", "up", "-d", "--wait", "control-api"])
    run(
        [str(VENV_PYTHON), "scripts/phase3_scenario.py", "verify-after-restart"],
        environment=scenario_environment,
    )
    print("Phase 3 persistence gate passed; Compose services remain running.", flush=True)


def agent_fleet_check() -> None:
    if not VENV_PYTHON.exists():
        raise RuntimeError("The Python environment is missing. Run the setup task first.")
    docker = executable("docker")
    run(
        [
            docker,
            "compose",
            "up",
            "-d",
            "--build",
            "--wait",
            "customer-api-registry",
            "crm-sandbox",
            "analytics-sandbox",
            "support-sandbox",
            "agent-fleet",
        ]
    )
    run([str(VENV_PYTHON), "scripts/phase4_scenario.py"])


def wait_for_health(
    url: str,
    *,
    processes: Sequence[subprocess.Popen[bytes]] = (),
    timeout_seconds: float = 90.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        stopped_process = next(
            (process for process in processes if process.poll() is not None),
            None,
        )
        if stopped_process is not None:
            raise RuntimeError(
                f"Development service exited before becoming healthy: {stopped_process.returncode}."
            )
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("status") in {"ok", "ready"}:
                    return
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as error:
            last_error = error
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def serve(*, smoke_only: bool) -> None:
    if not VENV_PYTHON.exists():
        raise RuntimeError("The Python environment is missing. Run the setup task first.")
    if not NEXT_CLI.exists():
        raise RuntimeError("Frontend dependencies are missing. Run the setup task first.")

    node = executable("node")
    env = command_environment()
    backend = subprocess.Popen(  # noqa: S603
        [
            str(VENV_PYTHON),
            "-m",
            "uvicorn",
            "control_api.main:app",
            "--app-dir",
            "services/control-api/src",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        cwd=ROOT,
        env=env,
    )
    frontend = subprocess.Popen(  # noqa: S603
        [
            node,
            str(NEXT_CLI),
            "dev",
            "apps/control-tower",
            "--hostname",
            "127.0.0.1",
            "--port",
            "3000",
        ],
        cwd=ROOT,
        env=env,
    )
    processes = (backend, frontend)
    try:
        wait_for_health("http://127.0.0.1:8000/health/live", processes=processes)
        wait_for_health("http://127.0.0.1:3000/api/health", processes=processes)
        print("Development services are healthy on ports 8000 and 3000.", flush=True)
        if smoke_only:
            return
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        failed = next(process for process in processes if process.poll() is not None)
        raise RuntimeError(
            f"Development service exited unexpectedly with code {failed.returncode}."
        )
    except KeyboardInterrupt:
        print("Stopping development services.", flush=True)
    finally:
        for process in reversed(processes):
            stop_process(process)


def clean() -> None:
    generated_paths = [
        ROOT / ".mypy_cache",
        ROOT / ".pytest_cache",
        ROOT / ".ruff_cache",
        ROOT / "apps" / "control-tower" / ".next",
        ROOT / "apps" / "control-tower" / "coverage",
    ]
    for path in generated_paths:
        if path.exists():
            print(f"Removing generated path: {path.relative_to(ROOT)}")
            shutil.rmtree(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "task",
        choices=(
            "setup",
            "lint",
            "test",
            "audit",
            "build",
            "dev",
            "smoke",
            "sandbox-check",
            "persistence-check",
            "agent-fleet-check",
            "clean",
        ),
    )
    args = parser.parse_args()

    actions = {
        "setup": setup,
        "lint": lint,
        "test": test,
        "audit": audit,
        "build": build,
        "sandbox-check": sandbox_check,
        "persistence-check": persistence_check,
        "agent-fleet-check": agent_fleet_check,
        "dev": lambda: serve(smoke_only=False),
        "smoke": lambda: serve(smoke_only=True),
        "clean": clean,
    }
    actions[args.task]()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, TimeoutError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
