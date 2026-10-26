"""XML of structured test reports, parsed without document type declarations.

A DTD is the only place an entity can be declared, so refusing it in the parser
itself rules out entity expansion while a report that merely quotes `<!DOCTYPE`,
for example in a failure message, still parses.
"""

from xml.etree import ElementTree
from xml.parsers import expat


def tree(text):
    """The root element; malformed XML and any DTD raise ValueError."""
    builder = ElementTree.TreeBuilder()
    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = refuse_dtd
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(text, True)
    except expat.ExpatError as error:
        raise ValueError(f"Invalid report XML: {error}") from error
    return builder.close()


def refuse_dtd(*_declaration):
    """Expat calls this before it reads any declaration inside the DTD."""
    raise ValueError("DTD is not a test report")
