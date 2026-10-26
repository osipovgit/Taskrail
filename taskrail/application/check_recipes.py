"""Server-owned exact check recipes; task text cannot grant execution authority."""

from taskrail.application.check_catalog import public_catalog as public_catalog
from taskrail.application.check_jenkins_recipe import validate_jenkins
from taskrail.application.verify_settings import parse_command
from taskrail.core.schema import require
from taskrail.executor import action_schema, protocol

JENKINS = "jenkins"
KINDS = frozenset(("local", JENKINS, "ssh"))
SERVER = "server"
KIND = "kind"
ADAPTER = "adapter"
PHASE = "phase"
IDENTITY_LENGTH = 12
DESCRIPTION_LIMIT = 1000
PHASES = frozenset(("check", "validation", SERVER))
ADAPTERS = frozenset(
    (
        "exit-code",
        "ruff-json",
        "eslint-json",
        "stylelint-json",
        "shellcheck-json",
        "junit",
        JENKINS,
    )
)


def parse_catalog(options):
    """Freeze configured recipes and expose existing exact verification commands."""
    configured = options.get("check_recipes", {})
    require(isinstance(configured, dict), "check_recipes must be an object")
    recipes = {}
    for name, recipe in configured.items():
        name = protocol.label(name)
        require(
            not name.startswith("verify-"), "verify- recipe IDs are reserved for verify_commands"
        )
        recipes[name] = validate(recipe)
    recipes.update(legacy(options.get("verify_commands", [])))
    return recipes


def legacy(commands):
    """Existing verification settings are exact local recipes with stable identities."""
    recipes = {}
    for command in commands:
        request = parse_command(command)
        name = verification_id(request)
        recipes[name] = dict(kind="local", phase="check", request=request, adapter="exit-code")
    return recipes


def verification_id(command):
    """A command retains its identity across unrelated catalog edits."""
    signature = protocol.fingerprint(command)[:IDENTITY_LENGTH]
    return f"verify-{signature}"


def validate(recipe):
    """Validate recipe shape before any model or process is started."""
    validate_fields(recipe)
    require(recipe[KIND] in KINDS, "Unknown check recipe kind")
    require(recipe[PHASE] in PHASES, "Unknown check recipe phase")
    require(recipe[ADAPTER] in ADAPTERS, "Unknown check output adapter")
    return dict(recipe, request=validated_request(recipe))


def validated_request(recipe):
    """Recipe kind fixes its phase and applicable execution adapter."""
    request = recipe["request"]
    if recipe[KIND] == "local":
        require(recipe[PHASE] == "check", "Local checks use the check phase")
        require(recipe[ADAPTER] != JENKINS, "Local checks require a local output adapter")
        request = parse_command(request)
    elif recipe[KIND] == "ssh":
        require(recipe[PHASE] == SERVER, "SSH recipes require confirmed server checks")
        require(recipe[ADAPTER] == "exit-code", "SSH recipes use the exit-code adapter")
        request = action_schema.validate(request)
    else:
        require(recipe[PHASE] in {"validation", SERVER}, "Jenkins checks require a delivery phase")
        validate_jenkins(request)
        require(recipe[ADAPTER] == JENKINS, "Jenkins recipes use the jenkins adapter")
    return request


def validate_fields(recipe):
    """Unknown recipe keys and unbounded descriptions fail before execution."""
    fields = {KIND, PHASE, "request", "adapter"}
    require(isinstance(recipe, dict), "Invalid check recipe fields")
    require(fields <= set(recipe) <= fields | {"description"}, "Invalid check recipe fields")
    description = recipe.get("description", "")
    require(
        isinstance(description, str) and len(description) <= DESCRIPTION_LIMIT,
        "Invalid recipe description",
    )
