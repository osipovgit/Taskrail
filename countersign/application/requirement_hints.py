"""Where the requirements point: files that name their distinctive words.

A word with a path separator, a dot or a joined identifier (var-naming, ntp_server,
roles/ntp) is distinctive; the first line that mentions it in each source file is a
hint for the planner, so it reads there instead of searching the whole project.
"""

import re

WORD = re.compile(r"[A-Za-z0-9][\w.-]*[/_.-][\w./-]*[A-Za-z0-9]")
WORDS_PER_REQUIREMENT = 6
FILES_PER_WORD = 4


def hint_lines(requirements, texts):
    """One line per requirement with hints; texts maps a shown path to its text."""
    lines = []
    for number, requirement in enumerate(requirements, 1):
        hints = [hint(word, texts) for word in distinctive(requirement["text"])]
        hints = [entry for entry in hints if entry]
        if hints:
            lines.append("R{} → {}".format(number, "; ".join(hints)))
    return lines


def distinctive(text):
    """The requirement's distinctive words, in order, without repeats."""
    words = [word.rstrip(".") for word in WORD.findall(text)]
    long_words = [word for word in dict.fromkeys(words) if len(word) >= 4]
    return long_words[:WORDS_PER_REQUIREMENT]


def hint(word, texts):
    """`word: path:line, …` for the first files that mention it, or an empty string."""
    found = mentions(word, texts)
    if not found:
        return ""
    shown = "{}: {}".format(word, ", ".join(found[:FILES_PER_WORD]))
    more = len(found) - FILES_PER_WORD
    return f"{shown} (+{more} files)" if more > 0 else shown


def mentions(word, texts):
    """`path:line` of each file whose text or path names the word."""
    pairs = texts.items()
    named = [name for name, text in pairs if names_word(word, name, text)]
    return [mention(name, texts[name], word) for name in named]


def names_word(word, name, text):
    """The file's path or text names the word."""
    return word in name or word in text


def mention(name, text, word):
    """`path:line` of the first line that names the word, or line 1 when the path does."""
    position = max(text.find(word), 0)
    return "{}:{}".format(name, text.count("\n", 0, position) + 1)
