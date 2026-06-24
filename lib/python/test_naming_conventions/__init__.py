"""Validate AWS resource naming conventions.

Provides predicates and validators for the two naming styles this project
uses: PascalCase (IAM roles, Lambda functions) and kebab-case with a
PascalCase prefix (infrastructure resources such as buckets and tables).

Example usage::

    from test_naming_conventions import is_pascalcase, validate_name, find_violations
    from test_naming_conventions import is_kebabcase, validate_kebab_name

    is_pascalcase("WanGraphSynthesizer")   # True
    is_pascalcase("wan-graph-synthesizer") # False (contains dash)

    validate_name("Bad-Name")              # Returns an error string
    find_violations(["Good", "Bad-Name"])  # [("Bad-Name", "...")]

    is_kebabcase("TenULabs-state-bucket")  # True
    validate_kebab_name("TenULabs-state")  # Returns None (valid)
"""
from __future__ import annotations

import re

_KEBAB_SUFFIX = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def is_pascalcase(name: str) -> bool:
    """Report whether a name is valid PascalCase.

    PascalCase here means: starts with an uppercase letter and contains only
    alphanumeric characters (no dashes, underscores, or spaces).

    Args:
        name: The name to test.

    Returns:
        ``True`` if the name is valid PascalCase, ``False`` otherwise.
    """
    if not name:
        return False
    if not name[0].isupper():
        return False
    return name.isalnum()


def validate_name(name: str) -> str | None:
    """Validate a PascalCase name and describe the first problem found.

    Args:
        name: The name to validate.

    Returns:
        ``None`` if valid, otherwise an error message describing the issue.
    """
    if not name:
        return "Name is empty"
    violations = [
        (not name[0].isupper(), f"Name '{name}' must start with uppercase letter"),
        ("-" in name, f"Name '{name}' contains dash (-), use PascalCase instead"),
        ("_" in name, f"Name '{name}' contains underscore (_), use PascalCase instead"),
        (" " in name, f"Name '{name}' contains space, use PascalCase instead"),
        (not name.isalnum(), f"Name '{name}' contains non-alphanumeric characters"),
    ]
    for condition, error_message in violations:
        if condition:
            return error_message
    return None


def find_violations(names: list[str]) -> list[tuple[str, str]]:
    """Collect every PascalCase violation in a list of names.

    Args:
        names: The names to check.

    Returns:
        A list of ``(name, error_message)`` tuples, one per violating name.
    """
    violations: list[tuple[str, str]] = []
    for name in names:
        error = validate_name(name)
        if error:
            violations.append((name, error))
    return violations


def is_kebabcase(name: str) -> bool:
    """Report whether a name is a PascalCase-prefixed kebab-case name.

    The expected shape is a PascalCase prefix, a hyphen, then lowercase words
    separated by hyphens (e.g. ``TenULabs-state-bucket``).

    Args:
        name: The name to test.

    Returns:
        ``True`` if the name is valid kebab-case, ``False`` otherwise.
    """
    if not name or "-" not in name:
        return False
    prefix, rest = name.split("-", 1)
    prefix_valid = bool(prefix) and prefix[0].isupper() and prefix.isalnum()
    rest_valid = bool(rest) and bool(_KEBAB_SUFFIX.match(rest))
    return prefix_valid and rest_valid


def validate_kebab_name(name: str) -> str | None:
    """Validate a kebab-case name and describe the first problem found.

    Expected format: ``PascalCasePrefix-lowercase-words-with-hyphens``
    (e.g. ``TenULabs-rack-configurations-backup``).

    Args:
        name: The name to validate.

    Returns:
        ``None`` if valid, otherwise an error message describing the issue.
    """
    if not name:
        return "Name is empty"
    if "-" not in name:
        return f"Name '{name}' must contain hyphens for kebab-case format"
    prefix, rest = name.split("-", 1)
    if not prefix or not prefix[0].isupper() or not prefix.isalnum():
        return f"Name '{name}' prefix must be PascalCase (alphanumeric, starts uppercase)"
    if not rest or not _KEBAB_SUFFIX.match(rest):
        return f"Name '{name}' suffix must be lowercase words separated by hyphens"
    return None
