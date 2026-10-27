"""Landmarks of infrastructure and application files, and the optional YAML syntax check."""

import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

from taskrail.application import builtin_checks, yaml_check
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
            patch.object(yaml_check.shutil, "which", return_value=None),
        ):
            skipped = self.check("roles: [ntp\n")
            self.assertEqual(skipped["status"], "SKIPPED")
            self.assertIn("install python3-yaml", skipped["detail"])
            self.assertEqual(yaml_check.health(), (True, yaml_check.MISSING))

    def test_an_unknown_kind_names_its_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.cfg"
            path.write_text("x")
            skipped = builtin_checks.file_check("app.cfg", path)
        self.assertEqual(skipped["detail"], "No built-in syntax validator for .cfg")


if __name__ == "__main__":
    unittest.main()
