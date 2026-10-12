"""Narrow exact-byte publication gate; preserve permitted raw evidence."""
import hashlib, json, pathlib, shutil, sys, zipfile
source, dest = map(pathlib.Path, sys.argv[1:3])
held = '7f6565a53bf892900ef225b28c922d882170c96c7278a26d83a3e4e5f5cc5c30'
rows = []
for p in sorted(source.rglob('*')):
    if not p.is_file():
        continue
    raw = p.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    hits = [str(p)] if digest == held else []
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            hits += [n for n in z.namelist() if not n.endswith('/') and hashlib.sha256(z.read(n)).hexdigest() == held]
    relative = p.relative_to(source)
    rows.append({'file': str(relative), 'sha256': digest, 'held_members': hits, 'published': not hits})
    if not hits:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
dest.mkdir(parents=True, exist_ok=True)
(dest/'publication-scan.json').write_text(json.dumps({'held_sha256': held, 'scope': 'Exact-byte hold only; not blanket CRT or redistribution certification', 'files': rows}, indent=2))
print(json.dumps({'scanned':len(rows), 'withheld':sum(bool(r['held_members']) for r in rows)}))
