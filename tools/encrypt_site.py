#!/usr/bin/env python3
"""Build a deployable copy of the site with its private parts encrypted.

GitHub Pages is public no matter how private the repository is, so anything it
serves can be fetched by URL - the plan data included the street address. A
password prompt in JavaScript would not help: it hides the interface while
leaving every JSON file and blueprint scan one `curl` away.

So the private files are encrypted here, at build time, and only ciphertext is
deployed. The browser asks for the passphrase, derives a key with PBKDF2 and
decrypts locally with AES-GCM. The server never holds anything readable.

What is encrypted: the plan data (which carries the address), both rectified
blueprint scans and the per-area crops of them.
What is not: index.html, the CSS and JS, and the plant photographs - those are
public Wikimedia images and reveal nothing about the property.
What is not deployed at all: images/source (the original photos), the tooling,
and the detector's working files.

The passphrase is never written anywhere. Pass it with --passphrase or in
SITE_PASSPHRASE; in CI it comes from a repository secret.

Usage:
    SITE_PASSPHRASE='...' python3 tools/encrypt_site.py --out dist/site
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import pathlib
import shutil
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = pathlib.Path(__file__).resolve().parent.parent

# PBKDF2-HMAC-SHA256. The ciphertext is public, so an attacker can grind
# offline; this is the cost per guess. Web Crypto does it natively, so a phone
# spends about a second on it once per unlock.
ITERATIONS = 600_000

# Everything under these is served but left readable.
PUBLIC = ("index.html", "css", "js", "images/plants", ".nojekyll")

# Encrypted before deploy.
PRIVATE_GLOBS = (
    "data/**/*.json",
    "images/sheet-*/plan-*.webp",
    "images/sheet-*/plan.jpg",
    "images/sheet-*/zones/*.webp",
)

# Never deployed at all.
SKIP_PARTS = ("images/source", "tools", "dist", ".git", ".github",
              "node_modules", "__pycache__")
SKIP_NAMES = ("README.md", "requirements.txt", ".gitignore")


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def encrypt(aes: AESGCM, blob: bytes) -> bytes:
    """iv || ciphertext, so one file is one self-contained blob."""
    iv = os.urandom(12)
    return iv + aes.encrypt(iv, blob, None)


def should_skip(rel: pathlib.PurePosixPath) -> bool:
    s = str(rel)
    if any(s == p or s.startswith(p + "/") for p in SKIP_PARTS):
        return True
    if rel.name in SKIP_NAMES:
        return True
    # The detector's working files: _callout-candidates.json, _dims.json, ...
    return any(part.startswith("_") for part in rel.parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist/site")
    ap.add_argument("--passphrase")
    ap.add_argument("--iterations", type=int, default=ITERATIONS)
    args = ap.parse_args()

    passphrase = args.passphrase or os.environ.get("SITE_PASSPHRASE")
    if not passphrase:
        passphrase = getpass.getpass("Passphrase: ")
    if len(passphrase) < 8:
        raise SystemExit("passphrase must be at least 8 characters")

    out = pathlib.Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, args.iterations, 32)
    aes = AESGCM(key)

    private = set()
    for pattern in PRIVATE_GLOBS:
        for p in ROOT.glob(pattern):
            rel = pathlib.PurePosixPath(p.relative_to(ROOT).as_posix())
            if not should_skip(rel):
                private.add(rel)

    copied = encrypted = 0
    enc_bytes = 0

    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = pathlib.PurePosixPath(p.relative_to(ROOT).as_posix())
        if should_skip(rel):
            continue
        is_public = any(str(rel) == q or str(rel).startswith(q + "/") for q in PUBLIC)
        if not is_public and rel not in private:
            continue

        dst = out / str(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel in private:
            blob = encrypt(aes, p.read_bytes())
            dst.with_name(dst.name + ".enc").write_bytes(blob)
            encrypted += 1
            enc_bytes += len(blob)
        elif rel == pathlib.PurePosixPath("index.html"):
            # Tell the client this build is locked, so it need not probe for
            # auth.json and log a 404 on the plaintext build.
            html = p.read_text()
            dst.write_text(html.replace(
                "<head>",
                '<head>\n<meta name="plan-locked" content="auth.json">', 1))
            copied += 1
        else:
            shutil.copy2(p, dst)
            copied += 1

    # A tiny blob the client can decrypt to tell a wrong passphrase from a
    # corrupt download, without fetching anything large.
    manifest = {
        "version": 1,
        "kdf": {"name": "PBKDF2", "hash": "SHA-256",
                "iterations": args.iterations, "salt": b64(salt)},
        "cipher": "AES-GCM",
        "verifier": b64(encrypt(aes, b"pearson-residence")),
        "files": sorted(str(r) for r in private),
    }
    (out / "auth.json").write_text(json.dumps(manifest, indent=1) + "\n")

    print(f"  {copied} public files copied")
    print(f"  {encrypted} private files encrypted ({enc_bytes / 1024 / 1024:.1f} MB)")
    print(f"  PBKDF2-SHA256 x {args.iterations:,}, AES-256-GCM")
    print(f"  -> {out}")

    # Guard against ever shipping a readable copy of the private files.
    for rel in private:
        if (out / str(rel)).exists():
            raise SystemExit(f"refusing to ship plaintext {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
