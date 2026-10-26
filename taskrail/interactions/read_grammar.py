"""Explicit read-command options; unknown syntax requires personal approval."""

from types import MappingProxyType

from taskrail.core.schema import require

# Each pair lists switches, then options taking exactly one non-option value.
COMMANDS = MappingProxyType(
    {
        "ls": (
            "-a -A -l -h -d -i -n -r -s -t -S -1 --all --almost-all --directory --human-readable --color",
            "--sort --time-style",
        ),
        "du": (
            "-a -h -s -c -k -m -x --all --human-readable --summarize --total --one-file-system",
            "-d --max-depth --block-size",
        ),
        "stat": ("-f -t --file-system --terse", "-c --format --printf"),
        "wc": ("-c -m -l -L -w --bytes --chars --lines --max-line-length --words", ""),
        "cat": ("-A -b -e -E -n -s -t -T -v --show-all --number --squeeze-blank", ""),
        "head": ("-q -v --quiet --silent --verbose", "-n -c --lines --bytes"),
        "tail": ("-q -v --quiet --silent --verbose", "-n -c --lines --bytes"),
        "grep": (
            "-E -F -G -i -v -w -x -n -h -H -c -l -L -q -s -o -a -I --extended-regexp --fixed-strings --ignore-case --invert-match --line-number --count --files-with-matches --color",
            "-e -m -A -B -C --regexp --max-count --after-context --before-context --context",
        ),
    }
)
FIND_VALUES = frozenset(("-name", "-iname", "-path", "-ipath", "-type", "-maxdepth", "-mindepth"))
FIND_SWITCHES = frozenset(("-print", "-print0", "-empty"))
DASH = "-"
# GNU optional long values require '='; bare --color leaves the next operand intact.
OPTIONAL_VALUES = frozenset(("--color",))


def operands(program, arguments):
    """Return actual path operands, excluding patterns and option values."""
    if program == "find":
        return find_paths(arguments)
    require(program in COMMANDS, "Unsupported read command")
    options, paths = parse(arguments, COMMANDS[program])
    if program == "grep" and not {"-e", "--regexp"}.intersection(options):
        require(bool(paths), "Missing grep pattern")
        paths = paths[1:]
    return paths


def parse(arguments, grammar, options_after_paths=False):
    """GNU-style options with exact names, explicit value arity and literal -- paths."""
    grammar = tuple(set(names.split()) for names in grammar)
    options, paths = [], []
    cursor = iter(arguments)
    for argument in cursor:
        if argument == "--":
            paths.extend(cursor)
            break
        if argument.startswith(DASH):
            require(options_after_paths or not paths, "Read options must precede path operands")
            options.extend(option(argument, grammar, cursor))
        else:
            paths.append(argument)
    return options, paths


def option(argument, grammar, cursor):
    """A known long option or a bundle of known short options."""
    if argument.startswith("--"):
        return long_option(argument, grammar, cursor)
    names = []
    for index, letter in enumerate(argument[1:], 2):
        name = f"-{letter}"
        require(name in grammar[0] | grammar[1], "Unsupported read option")
        names.append(name)
        if name in grammar[1]:
            if index == len(argument):
                take_value(cursor)
            return names
    require(bool(names), "Standard input is not a path operand")
    return names


def long_option(argument, grammar, cursor):
    """Long option values cannot be supplied to switches or omitted from valued flags."""
    name, separator, text = argument.partition("=")
    require(name in grammar[0] | grammar[1], "Unsupported read option")
    if separator:
        valued = grammar[1] | OPTIONAL_VALUES
        require(name in valued and bool(text), "Invalid read option value")
    if name in grammar[1] and not separator:
        take_value(cursor)
    return [name]


def take_value(cursor):
    """Consume exactly one argument without accepting another option in its place."""
    text = next(cursor, "")
    require(bool(text) and not text.startswith(DASH), "Missing read option value")


def find_paths(arguments):
    """find keeps interpreting predicates after --; only listed predicates qualify."""
    paths = []
    predicates = False
    cursor = iter(arguments)
    for argument in cursor:
        if argument == "--":
            require(not predicates, "Unexpected find separator")
            continue
        if argument.startswith(DASH):
            find_predicate(argument, cursor)
            predicates = True
            continue
        require(not predicates, "Unsupported find predicate")
        require(not argument.startswith(("!", "(")), "Unsupported find predicate")
        paths.append(argument)
    return paths


def find_predicate(argument, cursor):
    """No execution, output files, link following or unknown expression operators."""
    require(argument in FIND_VALUES | FIND_SWITCHES, "Unsupported find predicate")
    if argument in FIND_VALUES:
        take_value(cursor)
