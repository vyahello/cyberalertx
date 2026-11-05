"""verify_release.py <release_dir> <repo> <commit>: every file of the commit's tree is present in the
release with the identical git blob hash; files that are not in the tree are listed (expected: build outputs)."""
import hashlib, os, subprocess, sys
rel, repo, commit = sys.argv[1:4]
BUILD = ("venv/", "frontend/node_modules/", "frontend/.next/", "frontend/next-env.d.ts", "frontend/tsconfig.tsbuildinfo",
         "frontend/.env.production", "data", "RELEASE", "RELEASE-INVENTORY.txt")
tree = {}
out = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "-z", commit], capture_output=True, check=True).stdout
for rec in out.split(b"\0"):
    if not rec: continue
    meta, path = rec.split(b"\t", 1); mode, typ, sha = meta.split()
    if typ == b"blob": tree[path.decode()] = (mode.decode(), sha.decode())
bad = 0
for path, (mode, sha) in tree.items():
    p = os.path.join(rel, path)
    if mode == "120000":
        data = os.readlink(p).encode() if os.path.islink(p) else None
    else:
        data = open(p, "rb").read() if os.path.isfile(p) and not os.path.islink(p) else None
    if data is None or hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != sha:
        bad += 1; print("MISMATCH", path)
CACHES = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
extra = []
for root, dirs, files in os.walk(rel):
    r = os.path.relpath(root, rel); r = "" if r == "." else r + "/"
    if any((r).startswith(b) for b in BUILD if b.endswith("/")): dirs[:] = []; continue
    if any(c in r.split("/") for c in CACHES): dirs[:] = []; continue
    for n in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
        q = r + n
        if n in CACHES: continue
        if q not in tree and not any(q == b or q.startswith(b) for b in BUILD): extra.append(q)
    dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d)) and not (r + d + "/").startswith(BUILD)]
print(f"commit {commit}: {len(tree)} files in tree, {bad} mismatched/missing, {len(extra)} unexpected extra")
for q in extra[:20]: print("EXTRA", q)
sys.exit(1 if bad or extra else 0)
