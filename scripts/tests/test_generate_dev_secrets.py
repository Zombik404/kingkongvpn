import importlib.util
import stat
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

SCRIPT = Path(__file__).resolve().parent.parent / "generate-dev-secrets.py"
spec = importlib.util.spec_from_file_location("gen", SCRIPT)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def test_generates_usable_keys_with_private_permissions(tmp_path):
    out = tmp_path / "secrets"
    gen.generate(out, force=False)
    priv = serialization.load_pem_private_key((out / "jwt_ed25519_private.pem").read_bytes(), None)
    pub = serialization.load_pem_public_key((out / "jwt_ed25519_public.pem").read_bytes())
    sig = priv.sign(b"msg")
    pub.verify(sig, b"msg")  # raises if keys don't match
    cert = x509.load_pem_x509_certificate((out / "node_ca.crt").read_bytes())
    assert cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    for name in ("jwt_ed25519_private.pem", "node_ca.key"):
        assert stat.S_IMODE((out / name).stat().st_mode) == 0o600
    assert stat.S_IMODE(out.stat().st_mode) == 0o700


def test_refuses_to_overwrite(tmp_path):
    gen.generate(tmp_path, force=False)
    with pytest.raises(FileExistsError):
        gen.generate(tmp_path, force=False)
    gen.generate(tmp_path, force=True)
