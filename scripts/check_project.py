"""Run offline project checks consistently on Windows, macOS and CI."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default="node", help="Node executable name or full path")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    node = shutil.which(args.node)
    if not node:
        parser.error("Node is required; install Node or pass --node PATH")
    commands = [[node, "--check", "web/app.js"]]
    commands += [[sys.executable, str(p.relative_to(root))]
                 for p in sorted((root / "web").glob("test_*.py"))]
    commands += [[node, str(p.relative_to(root))]
                 for p in sorted((root / "web").glob("test_*.cjs"))]
    commands.append([sys.executable, "web/selftest.py"])
    failures = []
    for command in commands:
        print("\nCHECK " + " ".join(command[1:]), flush=True)
        try:
            result = subprocess.run(command, cwd=root, timeout=180)
            if result.returncode:
                failures.append(command[-1])
        except subprocess.TimeoutExpired:
            failures.append(command[-1] + " (timeout)")
    print(f"\nChecks: {len(commands) - len(failures)}/{len(commands)} passed")
    for failure in failures:
        print("FAILED: " + failure)
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
