"""Lists every GET route and the permissions it declares (read from the dependency tree)."""
from scripts.local_api_qa import get_routes


def run(h):
    for r in h.app.routes:
        if hasattr(r, "dependant") and "GET" in getattr(r, "methods", ()):
            keys = []
            def walk(d):
                for s in d.dependencies:
                    k = getattr(s.call, "permission_keys", None)
                    if k: keys.append("|".join(k))
                    walk(s)
            walk(r.dependant)
            print(f"{r.path:60s} {' & '.join(keys) or '(sign-in only / public)'}")
