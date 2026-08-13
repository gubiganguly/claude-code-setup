# Cleanup rules

Deleting is the only irreversible thing a checkpoint does. These rules exist so
it stays boring.

## The default is: do not delete

When unsure, flag it and move on. A leftover file costs nothing. A deleted file
someone needed costs trust, and you will not be there when they find out.

## Never delete

Not even with permission, without the user naming the specific file:

- Anything under `context/inbox/` — the user's drop zone, full stop
- `.env`, `.env.*`, credentials, keys, certificates, `*.pem`, `*.key`
- Lockfiles (`package-lock.json`, `poetry.lock`, `*.tfstate`, `.terraform.lock.hcl`)
- Database migrations, even ones that look superseded
- `.git/` and anything inside it
- Files a running deployment reads
- Anything you have not opened

## Auto-safe (delete without asking)

Genuinely regenerable machine droppings:

```
.DS_Store          Thumbs.db          desktop.ini
*.pyc              __pycache__/       .pytest_cache/
*.swp  *.swo  *~   .*.sw[a-p]
*.orig  *.rej                         (merge leftovers)
0-byte files
```

Even here, list what you removed in the report. Silent deletion is a bad habit
regardless of how safe the file was.

## Propose (show the user, wait)

Each candidate needs a **path**, a **size**, a **reason**, and a **confidence**.

### Unreferenced assets

Search **file contents**, not just names. An image can be referenced by:

```
src="/img/logo.png"          direct
src={`/img/${name}.png`}     built at runtime  ← a name search misses this
background: url(logo.png)    CSS
![alt](../img/logo.png)      markdown
```

If a directory is loaded dynamically, every file in it is live even though none
appear by name. When a variable-built path exists anywhere near the asset
directory, drop confidence to low and say why.

### Superseded documents

`design-v1.md` next to `design-v2.md`; `notes-old/`; `README.backup.md`.
Confirm the newer one actually covers everything the older one did before
proposing removal. Sometimes v1 holds a rationale v2 dropped.

### Stale docs

A document describing something that no longer exists. These are worse than
useless: the next agent believes them. Propose deletion, or rewrite them.

### Rebuildable artifacts

`dist/`, `build/`, `.next/`, coverage reports, compiled assets — but only when
they are gitignored or reproducible by a command you have verified.

### Unused dependencies

A manifest entry nothing imports. Propose, never remove: build tools, type
packages, and peer dependencies are often invisible to a naive import search.

## How to present it

```
| File | Size | Why it looks dead | Confidence |
|---|---|---|---|
| docs/old-api.md | 12K | Describes /v1 endpoints, removed in 3f2a1b | High |
| public/hero-v2.png | 2.1M | No reference in any file | Medium |
```

Then: "Delete all, delete some, or skip?" Bulk approval is fine. Guessing is
not.

## How to delete

**In a repo:**
```bash
git rm <paths>
```
Recoverable from history. This is why the tree should be clean before starting.

**Not in a repo:**
```bash
mkdir -p .checkpoint-trash/<date>
mv <paths> .checkpoint-trash/<date>/
```
Tell the user where it went and that they can remove it once satisfied.

## After deleting

Check nothing broke:
- Did you remove something the README links to? Fix the link.
- Did an index reference it? Update the index.
- Does the build still pass?

A cleanup that leaves broken links has made the docs worse, not better.
