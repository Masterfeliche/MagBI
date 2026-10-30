import base64
import os

import pytest

from magbi.storage.credentials import (
    CredentialError,
    CredentialVault,
    generate_key,
    parse_key,
)


@pytest.fixture
def vault() -> CredentialVault:
    return CredentialVault.from_encoded_key(generate_key())


def test_round_trip(vault: CredentialVault) -> None:
    token = vault.encrypt("p@ssw0rd é 密码")
    assert vault.decrypt(token) == "p@ssw0rd é 密码"


def test_token_does_not_contain_plaintext(vault: CredentialVault) -> None:
    assert "hunter2" not in vault.encrypt("hunter2")


def test_nonce_is_unique_per_call(vault: CredentialVault) -> None:
    assert vault.encrypt("same") != vault.encrypt("same")


def test_wrong_key_fails(vault: CredentialVault) -> None:
    token = vault.encrypt("secret")
    other = CredentialVault.from_encoded_key(generate_key())
    with pytest.raises(CredentialError):
        other.decrypt(token)


def test_aad_binds_context(vault: CredentialVault) -> None:
    token = vault.encrypt("secret", aad=b"conn-1")
    assert vault.decrypt(token, aad=b"conn-1") == "secret"
    with pytest.raises(CredentialError):
        vault.decrypt(token, aad=b"conn-2")
    with pytest.raises(CredentialError):
        vault.decrypt(token)


def test_tampered_token_fails(vault: CredentialVault) -> None:
    token = vault.encrypt("secret")
    blob = bytearray(base64.urlsafe_b64decode(token[3:]))
    blob[-1] ^= 0x01
    tampered = "v1:" + base64.urlsafe_b64encode(bytes(blob)).decode()
    with pytest.raises(CredentialError):
        vault.decrypt(tampered)


@pytest.mark.parametrize("token", ["", "plain", "v2:abc", "v1:!!!", "v1:AAAA"])
def test_malformed_tokens_rejected(vault: CredentialVault, token: str) -> None:
    with pytest.raises(CredentialError):
        vault.decrypt(token)


@pytest.mark.parametrize("n", [0, 16, 24, 31, 33, 64])
def test_bad_key_length_rejected(n: int) -> None:
    with pytest.raises(CredentialError):
        CredentialVault(os.urandom(n))
    with pytest.raises(CredentialError):
        parse_key(base64.urlsafe_b64encode(os.urandom(n)).decode())


def test_invalid_base64_key_rejected() -> None:
    with pytest.raises(CredentialError):
        parse_key("not base64 !!!")


def test_generated_key_is_32_bytes() -> None:
    assert len(parse_key(generate_key())) == 32


def test_repr_hides_key() -> None:
    key = generate_key()
    assert key not in repr(CredentialVault.from_encoded_key(key))


def test_error_messages_do_not_leak_secret(vault: CredentialVault) -> None:
    token = vault.encrypt("topsecret")
    other = CredentialVault.from_encoded_key(generate_key())
    with pytest.raises(CredentialError) as exc:
        other.decrypt(token)
    assert "topsecret" not in str(exc.value)
