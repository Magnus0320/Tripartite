"""The one function that builds a message for a response body (ARCHITECTURE.md D8 §No absolute
paths in response bodies, FU-35).

No response body contains an absolute path. ``public_message`` rewrites every one in a text:

1. a path under the data root becomes its path relative to the data root (``raw/validation.csv``);
2. a path under the repository becomes its repository-relative path;
3. any other absolute path becomes its file name.

The data root is ``$TRIPARTITE_DATA_DIR`` when that is an absolute path, else the default
``data/``; it is read from the environment at every call, as D3 requires, and never through
``data_dir()``, which raises for a root that does not exist. Both roots are matched as written
and resolved, because a message may hold either form (on macOS ``/var`` is ``/private/var``).

In step 3 a path starts only at the start of the text or after whitespace, a quote, ``(``, ``[``
or ``=``, so a URL such as ``http://127.0.0.1:11435/api/tags`` is left as it is. A quoted path
is taken whole, spaces included. An unquoted one ends at whitespace, a quote, a bracket or
``:``, ``,`` or ``;``, so an unquoted path with a space, outside both roots, is cut there.

The full text is logged, at WARNING on the ``tripartite.api`` logger, whenever it was changed.
"""

import logging
import os
import re
from pathlib import Path
from typing import Final

from tripartite.config import REPO_ROOT
from tripartite.data.manifest import DATA_DIR, DATA_DIR_ENV

logger: Final = logging.getLogger("tripartite.api")

_QUOTED: Final = re.compile(r"""(?P<quote>['"])(?P<path>/[^'"]*)(?P=quote)""")
_UNQUOTED: Final = re.compile(r"""(?<![^\s'"(\[=])/[^\s'"`:,;()\[\]]+""")


def _data_root() -> Path:
    value = os.environ.get(DATA_DIR_ENV)
    if value is not None and Path(value).is_absolute():
        return Path(value)
    return DATA_DIR


def _prefixes(root: Path) -> list[str]:
    """``root`` as written and resolved, each with a trailing separator, longest first."""
    forms = {str(root), str(root.resolve())}
    return sorted((form.rstrip("/") + "/" for form in forms), key=len, reverse=True)


def _name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or path


def public_message(text: str, *, log: bool = True) -> str:
    """``text`` without absolute paths. ``log=False`` is for a text whose full form is already
    kept server-side, such as a run's error in ``manifest.json``."""
    public = text
    for root in (_data_root(), REPO_ROOT):
        for prefix in _prefixes(root):
            public = public.replace(prefix, "")
    public = _QUOTED.sub(lambda m: m["quote"] + _name(m["path"]) + m["quote"], public)
    public = _UNQUOTED.sub(lambda m: _name(m[0]), public)
    if log and public != text:
        logger.warning("full text of a message served without absolute paths: %s", text)
    return public
