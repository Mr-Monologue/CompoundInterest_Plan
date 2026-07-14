"""scripts/project_runtime.py — unified clean Python subprocess runner."""
import os, sys, subprocess, json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def resolve_project_python():
    candidates = [ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def clean_env(extra=None):
    env = os.environ.copy()
    removed = []
    for key in ["PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "__PYVENV_LAUNCHER__"]:
        if key in env:
            removed.append(key)
            del env[key]
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env, removed


def runtime_probe():
    pp = resolve_project_python()
    if pp is None:
        return {"passed": False, "error": "PROJECT_PYTHON_NOT_FOUND"}
    env, removed = clean_env()
    results = {"project_python": pp, "removed_env_keys": removed, "passed": False}

    def _run(args, to=10):
        r = subprocess.run([pp] + list(args), capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=to)
        return r.returncode, r.stdout, r.stderr

    rc, out, err = _run(["--version"]); results["python_version"] = out.strip() or err.strip()
    rc, out, err = _run(["-c", "import sys; print(sys.executable)"]); results["sys_executable"] = out.strip()
    rc, out, err = _run(["-c", "import pydantic_core; print(pydantic_core.__file__)"], to=15)
    if rc == 0:
        results["pydantic_core_path"] = out.strip(); results["pydantic_core_ok"] = True
    else:
        results["pydantic_core_path"] = None; results["pydantic_core_ok"] = False; results["pydantic_core_error"] = err[:200]
    rc, out, err = _run(["-c", "import sys; print(chr(10).join(sys.path))"]); path_lines = [l for l in out.splitlines() if l.strip()]
    results["sys_path"] = path_lines; results["sys_path_contaminated"] = any("hermes-agent" in p for p in path_lines)

    results["passed"] = (results["pydantic_core_ok"] and "compound-interest-plan" in (results.get("sys_executable") or "") and not results["sys_path_contaminated"])
    return results


def run_project(cmd_args, timeout=300):
    pp = resolve_project_python()
    if pp is None:
        return (-1, "", "PROJECT_PYTHON_NOT_FOUND")
    env, _ = clean_env()
    try:
        r = subprocess.run([pp] + list(cmd_args), capture_output=True, text=True, timeout=timeout, cwd=str(ROOT), env=env)
        return (r.returncode, r.stdout, r.stderr)
    except subprocess.TimeoutExpired:
        return (-1, "", "TIMEOUT")
    except Exception as e:
        return (-1, "", str(e))


def run_pytest(test_path="tests/", extra_args=None):
    args = ["-m", "pytest", test_path, "-q", "--tb=short"]
    if extra_args:
        args.extend(extra_args)
    return run_project(args, timeout=600)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "probe":
        print(json.dumps(runtime_probe(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(runtime_probe(), indent=2, ensure_ascii=False))
