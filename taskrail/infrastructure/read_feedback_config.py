"""Load read guidance for model sessions without replacing the operator's JSONC settings."""

import json
import re
from pathlib import Path

from taskrail.infrastructure import opencode_cli

CONFIG_TEXT = "OPENCODE_CONFIG_CONTENT"
PLUGIN_DIR = Path(__file__).with_name("read_feedback")
TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/|[{}\[\]:,]')
OBJECT = "{"
OPEN = frozenset((OBJECT, "["))
CLOSE = frozenset(("}", "]"))


def environment(allow, compact, two):
    """Use the native plugin entry point for the selected protocol."""
    variables = opencode_cli.environment(allow, compact)
    key, plugin = ("plugins", PLUGIN_DIR) if two else ("plugin", PLUGIN_DIR / "v1.mjs")
    source = variables.get(CONFIG_TEXT) or "{}"
    variables[CONFIG_TEXT] = with_plugin(source, key, plugin.as_uri())
    return variables


def with_plugin(source, key, uri):
    """Splice one value, retaining comments, substitutions and paths in place."""
    tokens = list(config_tokens(source))
    if not tokens:
        return "\n".join((source, json.dumps({key: [uri]})))
    if len(tokens) < 2 or tokens[0][0] != OBJECT:
        return source
    index = plugin_array(tokens, key)
    fragment = json.dumps(uri)
    if index is None:
        index = 0
        fragment = f'"{key}":[{fragment}]'
    return prepend(source, tokens, index, fragment)


def config_tokens(source):
    for token in TOKENS.finditer(source):
        if not token[0].startswith("/"):
            yield token


def prepend(source, tokens, index, fragment):
    after = tokens[index].end()
    following = index + 1
    if following < len(tokens) and tokens[following][0] not in CLOSE:
        fragment = f"{fragment},"
    return "".join((source[:after], fragment, source[after:]))


def plugin_array(tokens, key):
    """Locate the root property, including escaped keys; ignore nested names and values."""
    names = [token[0] for token in tokens]
    for index, name in root_strings(names):
        suffix = names[index + 1 : index + 3]
        if name == key and suffix == [":", "["]:
            return index + 2
    return None


def root_strings(names):
    depth = 0
    for index, spelling in enumerate(names):
        if depth == 1 and spelling.startswith('"'):
            yield index, json.loads(spelling)
        if spelling in OPEN:
            depth += 1
        elif spelling in CLOSE:
            depth -= 1
