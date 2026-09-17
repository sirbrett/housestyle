class ConfigError(Exception):
    """The rule set, genre map, allow-list or a given path is wrong.

    The lint exits with code 2 when one of these is raised.
    """


class ReadError(Exception):
    """A file the tool was handed could not be read as a document."""
