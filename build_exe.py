#!/usr/bin/env python3
"""Build a standalone Windows .exe of the Starlink dashboard with PyInstaller.

Why this script exists: the app normally compiles its embedded protobuf at first
run by invoking ``python -m grpc_tools.protoc``. A frozen .exe has no interpreter
to do that, so this script pre-compiles the .proto and bundles the generated
modules. At runtime the app detects it is frozen and imports them directly (see
the ``FROZEN`` branch of ``ensure_proto_compiled`` in starlink_dashboard.py).

Usage:
    python build_exe.py             # windowed one-file build -> dist/StarlinkMonitor.exe
    python build_exe.py --console   # keep a console window (startup/debug output)
    python build_exe.py --onedir    # folder build instead of one file (faster launch)

Requires: pip install pyinstaller   (the app's own runtime deps must already be
installed in the same interpreter). Run it with the SAME python you run the app
with, so the frozen build matches the tested environment.
"""
import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
PROTO_OUT = BUILD / "proto"
APP = ROOT / "starlink_dashboard.py"
NAME = "StarlinkMonitor"


def run(cmd):
    print(">", " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd)


def have(mod):
    return importlib.util.find_spec(mod) is not None


def gen_proto():
    """Compile the embedded .proto into build/proto/{starlink_pb2,starlink_pb2_grpc}.py.

    The proto text is pulled straight from the app module so the bundled modules
    can never drift from the source of truth."""
    if not have("grpc_tools"):
        raise SystemExit("grpcio-tools not installed. Run:  pip install grpcio-tools")
    PROTO_OUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    import starlink_dashboard as sd
    proto = PROTO_OUT / "starlink.proto"
    proto.write_text(sd.PROTO_SRC, encoding="utf-8")
    run([sys.executable, "-m", "grpc_tools.protoc",
         f"--proto_path={PROTO_OUT}",
         f"--python_out={PROTO_OUT}",
         f"--grpc_python_out={PROTO_OUT}",
         str(proto)])
    for f in ("starlink_pb2.py", "starlink_pb2_grpc.py"):
        if not (PROTO_OUT / f).exists():
            raise SystemExit(f"proto generation failed: {f} missing")
    print("proto modules generated in", PROTO_OUT)


def build(console=False, onedir=False):
    if not have("PyInstaller"):
        raise SystemExit("PyInstaller not installed. Run:  pip install pyinstaller")
    sep = ";" if sys.platform.startswith("win") else ":"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--name", NAME,
           "--distpath", str(ROOT / "dist"),
           "--workpath", str(BUILD / "pyi"),
           "--specpath", str(BUILD),
           "--onedir" if onedir else "--onefile",
           # make the pre-compiled protobuf importable both at analysis and runtime
           "--paths", str(PROTO_OUT),
           "--add-data", f"{PROTO_OUT / 'starlink_pb2.py'}{sep}.",
           "--add-data", f"{PROTO_OUT / 'starlink_pb2_grpc.py'}{sep}.",
           "--hidden-import", "starlink_pb2",
           "--hidden-import", "starlink_pb2_grpc",
           "--hidden-import", "serial",
           # native/lazy deps PyInstaller can miss without a nudge
           "--collect-submodules", "grpc",
           "--collect-data", "grpc",
           "--collect-all", "sgp4",
           "--collect-all", "PIL",
           # pkg_resources/setuptools get dragged in by metadata collection but
           # nothing here needs them at runtime; their rthook fails on a missing
           # 'jaraco' dep, so drop both to skip that hook entirely.
           "--exclude-module", "pkg_resources",
           "--exclude-module", "setuptools",
           "--console" if console else "--windowed",
           str(APP)]
    run(cmd)
    out = ROOT / "dist" / (NAME if onedir else NAME + ".exe")
    print("\nBuilt:", out)
    print("Writable files (data/, location.json) are created next to the exe on"
          " first run.")


def main():
    ap = argparse.ArgumentParser(description="Build StarlinkMonitor.exe")
    ap.add_argument("--console", action="store_true",
                    help="keep a console window for startup/debug output")
    ap.add_argument("--onedir", action="store_true",
                    help="build a folder instead of a single file (faster launch)")
    args = ap.parse_args()
    gen_proto()
    build(console=args.console, onedir=args.onedir)


if __name__ == "__main__":
    main()
