"""Landmarks of infrastructure and application files, and the optional YAML syntax check."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from taskrail.application import builtin_checks, yaml_check, yaml_install
from taskrail.application.project_files import described, landmarks

LANDMARK_CASES = (
    (
        "Jenkinsfile",
        "pipeline {\n  stages {\n    stage('Build') {\n    stage(\"Deploy prod\") {\n"
        "}\ndef notify(String to) {\n    def version = 1\n",
        ["Build", "Deploy prod", "notify"],
    ),
    (
        "vars/release.groovy",
        "class Helper {\n    static void run(args) {\n}\ndef build() {\n",
        ["Helper", "run", "build"],
    ),
    (
        "Dockerfile.prod",
        'FROM python:3.12 AS build\nRUN pip install x\nfrom alpine\nENTRYPOINT ["app"]\n',
        ["FROM python:3.12 AS build", "from alpine", 'ENTRYPOINT ["app"]'],
    ),
    (
        "src/app.ts",
        "export default class App {}\nexport interface Props {}\ntype Id = string\n"
        "export async function load() {}\nexport const handler = () => 1\n",
        ["App", "Props", "Id", "load", "handler"],
    ),
    (
        "src/Main.java",
        "public final class Main {\n    public static void main(String[] args) {\n"
        "    private final Map<String, X> cache = new HashMap<>();\n}\nrecord Point(int x) {}\n",
        ["Main", "Point", "main"],
    ),
    (
        "cmd/main.go",
        "package main\ntype Server struct{}\nfunc (s *Server) Start() error {\nfunc main() {\n",
        ["Server", "Start", "main"],
    ),
    (
        "infra/main.tf",
        'resource "aws_instance" "web" {\nvariable "region" {\nmodule "vpc" {\nlocals {\n',
        ['resource "aws_instance" "web"', 'variable "region"', 'module "vpc"'],
    ),
    (
        "templates/nginx.conf.j2",
        "{% block server %}\n{%- macro upstream(name) %}\n",
        ["server", "upstream"],
    ),
)


class LandmarkTests(unittest.TestCase):
    def test_build_infrastructure_and_application_files_have_landmarks(self):
        for name, text, expected in LANDMARK_CASES:
            with self.subTest(name):
                self.assertEqual(landmarks(Path(name).name, text), expected)

    def test_named_build_files_are_recognized_on_disk_case_insensitively(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dockerfile"
            path.write_text("FROM busybox\n")
            self.assertEqual(described(path), (1, ["FROM busybox"], "FROM busybox\n"))
            self.assertEqual(landmarks("notes.txt", "FROM busybox\n"), [])


class YamlSyntaxTests(unittest.TestCase):
    def setUp(self):
        yaml_check.source.cache_clear()
        self.addCleanup(yaml_check.source.cache_clear)

    def check(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "site.yml"
            path.write_text(text)
            return builtin_checks.file_check("site.yml", path)

    def assert_parsed_without_constructing_tags(self):
        passed = self.check("---\npassword: !vault |\n  $ANSIBLE_VAULT;1.1\n---\n- name: a\n")
        self.assertEqual(passed["status"], "PASS", passed)
        failed = self.check("roles: [ntp\n")
        self.assertEqual(failed["status"], "FAIL")
        self.assertIn("line 2", failed["detail"])
        return passed["detail"]

    @unittest.skipUnless(find_spec("yaml"), "PyYAML is optional")
    def test_yaml_is_parsed_in_process_without_constructing_tags(self):
        self.assertIn("PyYAML in this Python", self.assert_parsed_without_constructing_tags())

    @unittest.skipUnless(find_spec("yaml"), "needs a Python with PyYAML")
    def test_a_system_python_with_pyyaml_checks_yaml_for_the_service(self):
        with (
            patch.object(yaml_check, "find_spec", return_value=None),
            patch.object(yaml_check.shutil, "which", return_value=sys.executable),
        ):
            self.assertIn(sys.executable, self.assert_parsed_without_constructing_tags())

    def test_yaml_is_skipped_with_the_reason_when_no_python_has_pyyaml(self):
        with (
            patch.object(yaml_check, "find_spec", return_value=None),
            patch.object(yaml_check, "pythons", return_value=[]),
        ):
            skipped = self.check("roles: [ntp\n")
        self.assertEqual(
            skipped, dict(file="site.yml", status="SKIPPED", detail=yaml_check.MISSING)
        )


class YamlInstallTests(unittest.TestCase):
    def setUp(self):
        yaml_check.source.cache_clear()
        self.addCleanup(yaml_check.source.cache_clear)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        root = base / "repo"
        root.mkdir()
        (root / "site.yml").write_text("roles: [ntp\n")
        run = base / "run"
        run.mkdir()
        self.workflow = SimpleNamespace(run=run, state={}, config=dict(roots=dict(project=root)))
        self.available = []
        for patcher in (
            patch.object(yaml_check, "find_spec", return_value=None),
            patch.object(yaml_check, "pythons", side_effect=lambda: self.available),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def resolve(self):
        checks = builtin_checks.syntax_checks(self.workflow.config["roots"], ["project/site.yml"])
        return yaml_install.resolve(self.workflow, self.workflow.run, checks)[0]

    def test_a_declined_install_leaves_yaml_unchecked_and_is_asked_once(self):
        deny = dict(decision="deny", alternative="")
        with (
            patch.object(yaml_install, "installer", return_value=["pip", "install"]),
            patch.object(yaml_install.approval_policy, "decision", return_value=deny) as asked,
        ):
            self.assertEqual(self.resolve()["detail"], yaml_install.DECLINED)
            self.assertEqual(self.resolve()["status"], "SKIPPED")
        self.assertEqual(asked.call_count, 1)

    def test_an_allowed_install_checks_the_file_at_once(self):
        def installed(*_arguments):
            self.available.append(sys.executable)
            return dict(status="COMPLETED")

        allow = dict(decision="allow", alternative="")
        with (
            patch.object(yaml_install, "installer", return_value=["pip", "install", "PyYAML"]),
            patch.object(yaml_install.approval_policy, "decision", return_value=allow) as asked,
            patch.object(yaml_install.local_actions, "execute", side_effect=installed),
        ):
            failed = self.resolve()
        self.assertEqual(failed["status"], "FAIL")
        self.assertIn("line 2", failed["detail"])
        shown = asked.call_args.args[1]
        self.assertIn(str(yaml_check.TARGET), shown["notice"])
        self.assertFalse(asked.call_args.kwargs["personal"])

    def test_a_failed_install_names_the_last_error_lines(self):
        stderr = (
            "WARNING: Retrying after connection broken\nERROR: No version\n\nERROR: None found\n"
        )
        allow = dict(decision="allow", alternative="")
        with (
            patch.object(yaml_install, "installer", return_value=["pip", "install", "PyYAML"]),
            patch.object(yaml_install.approval_policy, "decision", return_value=allow),
            patch.object(yaml_install.local_actions, "execute", return_value=dict(stderr=stderr)),
        ):
            skipped = self.resolve()
        expected = f"{yaml_install.STILL_MISSING}: ERROR: No version ERROR: None found"
        self.assertEqual(skipped["detail"], expected)

    def test_uv_in_the_user_bin_is_found_without_it_on_path(self):
        with tempfile.TemporaryDirectory() as directory:
            uv = Path(directory) / "uv"
            uv.write_text("#!/bin/sh\n")
            uv.chmod(0o755)
            self.available.append(sys.executable)
            no_pip = SimpleNamespace(returncode=1)
            with (
                patch.dict(os.environ, PATH=os.devnull),
                patch.object(yaml_install, "USER_BIN", directory),
                patch.object(yaml_check, "completed", return_value=no_pip),
            ):
                command = yaml_install.installer()
        self.assertEqual(command[:4], [str(uv), "--no-config", "pip", "install"])

    def test_install_request_uses_server_storage_instead_of_a_project_directory(self):
        command = [sys.executable, "-I", "-m", "pip", "--version"]
        payload, shown = yaml_install.request(self.workflow, command)
        self.assertEqual(payload["cwd"], str(self.workflow.run))
        self.assertEqual(shown["argv"], command)
        tail = yaml_install.run_install(
            self.workflow, self.workflow.run, payload, dict(decision="allow")
        )
        self.assertEqual(tail, "")
        entry = yaml_install.local_actions.local_journal.records(self.workflow.run)[0]
        self.assertEqual(entry["status"], "SUCCEEDED")
        self.assertIn("pip ", entry["outcome"]["stdout"])

    def test_pip_install_isolated_imports_ignore_project_modules(self):
        self.available.append(sys.executable)
        command = yaml_install.installer()
        self.assertIn("-I", command)
        self.assertEqual(command[-1], "PyYAML==6.0.3")
        root = self.workflow.config["roots"]["project"]
        for name in ("pip.py", "sitecustomize.py"):
            (root / name).write_text("raise RuntimeError('project module must not execute')\n")
        probe = [*command[: command.index("install")], "--version"]
        completed = subprocess.run(
            probe, cwd=root, capture_output=True, text=True, timeout=10, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("pip ", completed.stdout)

    @unittest.skipUnless(shutil.which("uv"), "uv is optional")
    def test_uv_install_ignores_malformed_project_configuration_offline(self):
        self.available.append(sys.executable)
        with patch.object(yaml_check, "completed", return_value=SimpleNamespace(returncode=1)):
            command = yaml_install.installer()
        root = self.workflow.config["roots"]["project"]
        (root / "uv.toml").write_text("invalid = [\n")
        command[command.index("--target") + 1] = str(self.workflow.run / "packages")
        command[-1:-1] = ["--offline", "--no-cache"]
        completed = subprocess.run(
            command, cwd=root, env={"PATH": os.defpath}, capture_output=True, text=True, timeout=10
        )
        self.assertNotIn("parse", completed.stderr.lower())
        self.assertIn("pyyaml", completed.stderr.lower())

    def test_without_an_installer_the_operator_installs_it_and_always_decides(self):
        allow = dict(decision="allow", alternative="")
        with (
            patch.object(yaml_install, "installer", return_value=None),
            patch.object(yaml_install.approval_policy, "decision", return_value=allow) as asked,
        ):
            still = self.resolve()
        self.assertTrue(asked.call_args.kwargs["personal"])
        shown = asked.call_args.args[1]
        self.assertIn("sudo apt install python3-yaml", shown["notice"])
        self.assertEqual(shown["status"], yaml_install.MANUAL_STEP)
        self.assertNotIn("argv", shown)
        self.assertEqual(still["detail"], yaml_install.STILL_MISSING)

    def test_an_unknown_kind_names_its_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.cfg"
            path.write_text("x")
            skipped = builtin_checks.file_check("app.cfg", path)
        self.assertEqual(skipped["detail"], "No built-in syntax validator for .cfg")


if __name__ == "__main__":
    unittest.main()
