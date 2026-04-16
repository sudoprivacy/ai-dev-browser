"""Package version — SSOT derived from git tag via setuptools-scm.

See [tool.setuptools_scm] in pyproject.toml. Release flow:
    git tag vX.Y.Z && git push --tags
"""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("ai-dev-browser")
except PackageNotFoundError:
    __version__ = "0.0.0"
