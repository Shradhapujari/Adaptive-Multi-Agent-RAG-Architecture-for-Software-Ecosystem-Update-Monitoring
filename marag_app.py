"""
Deployment entrypoint — runs the maintained demo in `app_1.py`.

This file used to be a second, older copy of the whole pipeline; that is
recorded in git history and in the commit that replaced it. This note is
about a second bug the replacement introduced.

Streamlit reruns the entrypoint *script* on every page load and every widget
interaction -- rebuilding the page from scratch is the framework's whole
model, so nothing persists between runs except what an app explicitly caches.
A plain `import app_1` looks like it does that, but only its first execution
does real work: Python imports the module once and caches it in
`sys.modules`, so every rerun after the first finds `app_1` already imported
and does nothing -- none of its `st.*` calls fire again. Streamlit still
reports the run as CONNECTED / notRunning, because nothing raised; the page
is simply never rebuilt. Confirmed by reloading a running local instance:
first load -- layout "wide", 8 elements, 482 characters of text; reload of
the same process -- layout "narrow" (app_1's set_page_config never re-ran),
zero elements, still CONNECTED. That is the same state the deployed URL was
in, and it explains why a brand-new process always looked fine to every local
test and probe run here -- each one only ever observed a first run.

`runpy.run_path` re-executes the target file as `__main__` on every call, so
every rerun does real work again, the same as if `app_1.py` were the
configured entrypoint directly. This file exists at all only because
Streamlit Cloud is configured to serve this filename; if that setting is ever
repointed to `app_1.py`, this file can go.

Re-executing app_1.py fixes app_1.py, and nothing else. Everything it
imports -- temporal, yesno, guardrail, the rest -- is still resolved through
`sys.modules`, which is loaded once per process. So a deploy leaves the page
current and its helpers whatever the running process happened to import,
and the two drift apart the moment a change spans both.

Measured on Streamlit Cloud, 2026-09-24: a deploy added `questions_total` to
yesno.py and a call to it in app_1.py. The page picked up the call, the
module did not grow the function, and `yesno.questions_total` raised
AttributeError at module level -- the whole app, down, on a number printed
in a caption. A reboot restarted the process while the disk was still
mid-pull, so it came back holding the same stale module and stayed down.
Rebooting again, later, was the only thing that fixed it.

Dropping this project's own modules before each run closes the gap: the
rerun re-imports them from disk, the same way it re-reads app_1.py. Measured
at 3-4ms for 21 modules, against runs that spend tens of seconds on the
network.

Safe here because nothing in this project tests identity across a reload --
no `isinstance` against a first-party class, and the one object that
outlives a rerun (the store handle, via `st.cache_resource`) is only ever
used through its methods. That is a property of this codebase, not of the
technique: an `isinstance` check against a re-imported class would start
failing, and the fix would be to keep that type out of the cache.
"""

import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _drop_first_party_modules() -> None:
    """Forget this project's own modules, so the rerun imports them afresh."""
    for name, module in list(sys.modules.items()):
        if name == "__main__":
            continue
        path = getattr(module, "__file__", None)
        if not path:                       # namespace packages, builtins
            continue
        try:
            resolved = Path(path).resolve()
        except (OSError, ValueError):
            continue
        if not resolved.is_relative_to(HERE):
            continue
        # The virtualenv lives inside the project directory, so "under HERE"
        # is not the same as "ours": streamlit itself sits below this path and
        # dropping it mid-run would be a far worse bug than the one above.
        if any(part == "site-packages" or part.startswith("venv")
               for part in resolved.parts):
            continue
        del sys.modules[name]


try:
    _drop_first_party_modules()
except Exception:                          # noqa: BLE001 - never fatal
    # A refresh that does not happen leaves a stale module, which is the bug
    # this guards against. A refresh that raises leaves a blank page, which
    # is worse. Degrade to the old behaviour rather than to nothing.
    pass

# Resolved against this file rather than the working directory, so the
# entrypoint does not depend on where the server was started from.
runpy.run_path(str(Path(__file__).with_name("app_1.py")), run_name="__main__")
