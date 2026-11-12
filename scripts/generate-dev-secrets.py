#!/usr/bin/env python3
"""Generate local development secrets into ./secrets (git-ignored).

Creates:
  jwt_ed25519_private.pem / jwt_ed25519_public.pem  - access-token signing keys
  node_ca.key / node_ca.crt                          - internal CA for node-agent mTLS (dev only)

Refuses to overwrite existing files unless --force is given.
Development and staging only: production keys are generated inside the
deployment secret store, never on a laptop.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parent.parent
FILES = ("jwt_ed25519_private.pem", "jwt_ed25519_public.pem", "node_ca.key", "node_ca.crt")


def _write(path: Path, data: bytes, private: bool) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def generate(out: Path, force: bool) -> list[Path]:
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing = [out / f for f in FILES if (out / f).exists()]
    if existing and not force:
        raise FileExistsError(f"refusing to overwrite: {', '.join(p.name for p in existing)}")

    jwt_key = ed25519.Ed25519PrivateKey.generate()
    _write(
        out / "jwt_ed25519_private.pem",
        jwt_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        private=True,
    )
    _write(
        out / "jwt_ed25519_public.pem",
        jwt_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        private=False,
    )

    ca_key = ec.generate_private_key(ec.SECP384R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "globalvpn dev node CA")])
    now = dt.datetime.now(dt.UTC)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA384())
    )
    _write(
        out / "node_ca.key",
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        private=True,
    )
    _write(out / "node_ca.crt", ca_cert.public_bytes(serialization.Encoding.PEM), private=False)
    return [out / f for f in FILES]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "secrets")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    args = parser.parse_args()
    try:
        written = generate(args.out, args.force)
    except FileExistsError as exc:
        print(f"error: {exc} (use --force)", file=sys.stderr)
        return 1
    for p in written:
        print(f"wrote {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
