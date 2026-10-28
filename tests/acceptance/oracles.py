"""Behavioral expectations independent of scripted model responses and gold edit text."""

import json
import os
import subprocess
import sys

import yaml

DOCKER_STUB = """import json
import os
import sys
from pathlib import Path

with Path(os.environ["TASKRAIL_DOCKER_TRACE"]).open("a") as output:
    output.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["compose", "build"] and os.environ["TASKRAIL_BUILD_FAIL"] == "1":
    sys.exit(17)
"""


def verify(test, case, roots, base):
    name = case["id"]
    if name == "ANSIBLE-LINT":
        role = yaml.safe_load((roots["infra"] / "roles/flink/tasks/main.yml").read_text())
        test.assertEqual(
            role[0]["ansible.builtin.file"], dict(path="/opt/flink", state="directory", mode="0755")
        )
        test.assertEqual(
            role[1]["ansible.builtin.template"],
            dict(src="flink-conf.yaml.j2", dest="/opt/flink/flink-conf.yaml", mode="0644"),
        )
    elif name == "IMAGE-CACHE":
        docker(test, roots["service"], base)
    elif name in {"PERCENT-DISCOUNT", "TESTS-ONLY"}:
        pricing(test, roots["service"])
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            cwd=roots["service"],
            capture_output=True,
            text=True,
            timeout=10,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        test.assertEqual(completed.returncode, 0, completed.stderr)
        test.assertIn("Ran 4 tests" if name == "TESTS-ONLY" else "Ran 2 tests", completed.stderr)
    elif name == "DOCS-ONLY":
        text = (roots["service"] / "README.md").read_text()
        for expected in ("timeout_seconds", "30", "seconds", "default"):
            test.assertIn(expected, text)


def pricing(test, root):
    program = "import json, runpy; source = runpy.run_path('pricing.py'); print(json.dumps([source['order_total']([(2, 10)], percent=p) for p in (0, 1, 10, 50, 100, 99)]))"
    completed = subprocess.run(
        [sys.executable, "-I", "-c", program], cwd=root, capture_output=True, text=True, timeout=10
    )
    test.assertEqual(completed.returncode, 0, completed.stderr)
    test.assertEqual(json.loads(completed.stdout), [20, 19.8, 18, 10, 0, 0.2])


def docker(test, root, base):
    binary = base / "bin/docker"
    binary.parent.mkdir()
    binary.write_text(f"#!{sys.executable}\n" + DOCKER_STUB)
    binary.chmod(0o700)
    build = ["compose", "build", "--no-cache", "api"]
    launches = {
        "start.sh": ["compose", "up", "--no-build"],
        "test.sh": [
            "compose",
            "run",
            "--rm",
            "--no-build",
            "api",
            "python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
        ],
    }
    for script, launch in launches.items():
        for failed in (False, True):
            with test.subTest(script=script, failed_build=failed):
                trace = base / f"{script}-{failed}.jsonl"
                environment = dict(
                    os.environ,
                    PATH=str(binary.parent) + os.pathsep + os.defpath,
                    TASKRAIL_DOCKER_TRACE=str(trace),
                    TASKRAIL_BUILD_FAIL="1" if failed else "0",
                )
                completed = subprocess.run(
                    ["bash", str(root / "scripts" / script)],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                test.assertEqual(completed.returncode, 17 if failed else 0, completed.stderr)
                calls = [json.loads(line) for line in trace.read_text().splitlines()]
                test.assertEqual(calls, [build] if failed else [build, launch])
