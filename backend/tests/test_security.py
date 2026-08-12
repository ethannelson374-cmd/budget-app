from __future__ import annotations

from argon2 import PasswordHasher, Type

from app.core.security import PASSWORD_HASHER, hash_password, verify_password


def test_argon2id_parameters_verification_and_upgrade_signal() -> None:
    password = "Correct Horse Battery Staple!"
    current_hash = hash_password(password)
    assert current_hash.startswith("$argon2id$")
    assert PASSWORD_HASHER.memory_cost == 19 * 1024
    assert PASSWORD_HASHER.time_cost == 2
    assert PASSWORD_HASHER.parallelism == 1
    assert verify_password(current_hash, password) == (True, False)
    assert verify_password(current_hash, "wrong password")[0] is False

    legacy_hash = PasswordHasher(
        time_cost=1,
        memory_cost=8 * 1024,
        parallelism=1,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    ).hash(password)
    assert verify_password(legacy_hash, password) == (True, True)
