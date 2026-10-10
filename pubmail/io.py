from __future__ import annotations
import fcntl, hashlib, json, os, sqlite3, subprocess
from pathlib import Path
import yaml


class Error(RuntimeError):
    pass


def run(argv, *, env=None, input=None, timeout=90):
    try:
        r = subprocess.run(
            argv, input=input, capture_output=True, text=True, env=env, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Error(f"{argv[0]} unavailable or timed out") from e
    if r.returncode:
        raise Error(
            f"{argv[0]} failed (exit {r.returncode}); output suppressed to protect mail/credentials"
        )
    return r.stdout


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)
    os.replace(tmp, path)
    path.chmod(0o600)


def load_config(path):
    c = yaml.safe_load(Path(path).expanduser().read_text())
    for key in (
        "account",
        "client",
        "state_dir",
        "timezone",
        "newsletter",
        "rollout",
        "model",
        "limits",
    ):
        if key not in c:
            raise Error(f"Missing config key: {key}")
    ignored = c.get("ignored_tracking_domains", [])
    suffixes = c.get("ignored_tracking_domain_suffixes", [])
    if not isinstance(ignored, list) or not isinstance(suffixes, list):
        raise Error("Tracking exclusions must be hostname lists")
    ignored = ignored + suffixes
    import re
    if not isinstance(ignored, list) or any(not isinstance(h, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", h) for h in ignored):
        raise Error("ignored_tracking_domains must be exact lowercase hostnames (no wildcards or URLs)")
    controls = c.get("unsubscribe_controls", {})
    images = c.get("image_loading", {})
    if not isinstance(controls, dict) or not isinstance(images, dict) or type(images.get("enabled", False)) is not bool:
        raise Error("Invalid image/subscription configuration")
    hosts = images.get("hosts", {})
    if not isinstance(hosts, dict):
        raise Error("Image hosts must be an exact-host mapping")
    for h in list(controls) + list(hosts):
        if not isinstance(h, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", h):
            raise Error("Invalid exact image/subscription hostname")
    for paths in controls.values():
        if not isinstance(paths, list) or any(not isinstance(p, str) or not p.startswith('/') or '?' in p for p in paths):
            raise Error("Subscription controls require exact paths")
    for rule in hosts.values():
        if not isinstance(rule, dict) or not isinstance(rule.get('path_prefixes'), list) or not rule['path_prefixes']:
            raise Error("Image host requires path prefixes")
        if any(not isinstance(p, str) or not p.startswith('/') or p == '/' for p in rule['path_prefixes']):
            raise Error("Image paths must be narrowly scoped")
        if not isinstance(rule.get('query_keys', []), list) or any(not isinstance(k, str) for k in rule.get('query_keys', [])):
            raise Error("Image query keys must be a list")
    from .reviewer import validate_config
    validate_config(c)
    if c["newsletter"]["format"] not in ("html", "text", "multipart"):
        raise Error("Invalid newsletter format")
    c["state_dir"] = str(Path(c["state_dir"]).expanduser())
    Path(c["state_dir"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    if Path(c["state_dir"]).stat().st_mode & 0o077:
        raise Error("State directory must have mode 0700")
    c.setdefault("labels", {"ads": "adds", "newsletter": "adds/newsletter"})
    return c


def policy_hash(c):
    return hashlib.sha256(json.dumps({"policy_version": 4, "config": c}, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, c):
        root = Path(c["state_dir"])
        self.root = root
        self.lock = open(root / "run.lock", "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error("Another run holds the lock")
        self.db = sqlite3.connect(root / "state.sqlite3")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, digest TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, fingerprint TEXT, policy TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS archived(id TEXT PRIMARY KEY, plan TEXT, previously_ads INTEGER);
        CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY, status TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()

    def put_decision(self, m, c, d):
        self.db.execute(
            "INSERT OR REPLACE INTO decisions VALUES(?,?,?,?)",
            (m["id"], m["headers_hash"], policy_hash(c), json.dumps(d)),
        )
        self.db.commit()

    def cached(self, m, c):
        r = self.db.execute(
            "SELECT body FROM decisions WHERE id=? AND fingerprint=? AND policy=?",
            (m["id"], m["headers_hash"], policy_hash(c)),
        ).fetchone()
        return json.loads(r[0]) if r else None

    def delivery(self, id, status, body):
        self.db.execute(
            "INSERT OR REPLACE INTO deliveries VALUES(?,?,?)",
            (id, status, json.dumps(body)),
        )
        self.db.commit()

    def close(self):
        self.db.close()
        self.lock.close()


class Gmail:
    def __init__(self, c):
        self.c = c
        self.env = None

    def call(self, *args):
        if self.env is None:
            self.env = os.environ.copy()
            cmd = self.c.get("keyring_password_command")
            if cmd:
                if not isinstance(cmd, list) or not all(
                    isinstance(x, str) for x in cmd
                ):
                    raise Error("Credential command must be an argv array")
                self.env["GOG_KEYRING_PASSWORD"] = run(cmd).rstrip("\r\n")
        result = run(
            [
                "gog",
                "--account",
                self.c["account"],
                "--client",
                self.c["client"],
                "--json",
                "--no-input",
                *args,
            ],
            env=self.env,
        )
        return json.loads(result) if result.strip() else {}

    def search(self, q, limit=200):
        found = []
        page = ""
        while True:
            args = [
                "gmail",
                "messages",
                "search",
                q,
                "--max",
                str(min(100, limit - len(found))),
            ]
            if page:
                args += ["--page", page]
            d = self.call(*args)
            found += d.get("messages") or []
            page = d.get("nextPageToken", "")
            if not page or len(found) >= limit:
                return found, bool(page)

    def raw(self, id):
        return self.call("gmail", "raw", id)

    def labels(self, create=False):
        d = self.call("gmail", "labels", "list")
        labels = {x["name"]: x["id"] for x in d.get("labels", [])}
        for name in self.c["labels"].values():
            if name not in labels and create:
                self.call("gmail", "labels", "create", name)
        if create:
            return self.labels(False)
        return labels

    def modify(self, id, add=(), remove=()):
        args = ["gmail", "batch", "modify", id]
        if add:
            args += ["--add", ",".join(add)]
        if remove:
            args += ["--remove", ",".join(remove)]
        return self.call(*args)
