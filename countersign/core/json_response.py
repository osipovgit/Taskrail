"""Recover a single unambiguous JSON object without repairing its contents."""

import json
import re


def read_container(fragment, pairs_hook):
    """Allow bracketed prose, but never rescue children of malformed JSON."""
    try:
        return json.JSONDecoder(object_pairs_hook=pairs_hook).raw_decode(fragment)
    except json.JSONDecodeError as error:
        if re.match(r"\[[A-Za-z][A-Za-z0-9 _-]*\]", fragment):
            return None
        raise ValueError("Incomplete or malformed JSON container in final response") from error


def extract(response, pairs_hook):
    """Ignore prose and reject multiple containers or nested rescue."""
    containers = []
    consumed = 0
    for opening in re.finditer(r"[\[{]", response):
        if opening.start() < consumed:
            continue
        decoded = read_container(response[opening.start() :], pairs_hook)
        if decoded is None:
            continue
        containers.append(decoded[0])
        consumed = opening.start() + decoded[1]
    if len(containers) != 1 or not isinstance(containers[0], dict):
        raise ValueError("Expected exactly one complete JSON object in final response")
    return containers[0]
