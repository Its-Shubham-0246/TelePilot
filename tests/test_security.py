from core.security import encrypt_session_string, decrypt_session_string


def test_session_string_encryption_and_decryption():
    raw_session = "1B3c4D5e6F7g8H9i0J_TelethonStringSessionExample=="
    encrypted = encrypt_session_string(raw_session)
    assert encrypted != raw_session
    assert isinstance(encrypted, str)

    decrypted = decrypt_session_string(encrypted)
    assert decrypted == raw_session


def test_empty_session_string():
    assert encrypt_session_string("") == ""
    assert decrypt_session_string("") == ""


def test_process_spintax():
    from services.mtproto_service import process_spintax
    pattern = "{Option1|Option2|Option3}"
    result = process_spintax(pattern)
    assert result in ["Option1", "Option2", "Option3"]

    nested_pattern = "Hello {world|{there|friend}}!"
    res2 = process_spintax(nested_pattern)
    assert res2.startswith("Hello ")

