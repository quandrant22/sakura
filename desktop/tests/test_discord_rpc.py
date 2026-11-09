from desktop.core.discord_rpc import DiscordRpcManager, DiscordUser
import time


def test_get_active_speaker_empty():
    m = DiscordRpcManager()
    speaker_name, speaker_id, is_master = m.get_active_speaker()
    assert speaker_name is None
    assert speaker_id is None
    assert is_master is False


def test_get_active_speaker_recent():
    m = DiscordRpcManager()
    u1 = DiscordUser(id="101", username="alex", display_name="Алексей", is_self=False)
    u2 = DiscordUser(id="102", username="gidrant7", display_name="Мастер", is_self=True)
    m.participants["101"] = u1
    m.participants["102"] = u2

    m.speaker_timestamps["101"] = time.monotonic()
    speaker_name, speaker_id, is_master = m.get_active_speaker(max_age_sec=2.0)
    assert speaker_name == "Алексей"
    assert speaker_id == "101"
    assert is_master is False

    # Master spoke more recently
    time.sleep(0.05)
    m.speaker_timestamps["102"] = time.monotonic()
    speaker_name, speaker_id, is_master = m.get_active_speaker(max_age_sec=2.0)
    assert speaker_name == "Мастер"
    assert speaker_id == "102"
    assert is_master is True


def test_get_active_speaker_expired():
    m = DiscordRpcManager()
    u1 = DiscordUser(id="101", username="alex", display_name="Алексей", is_self=False)
    u2 = DiscordUser(id="103", username="boris", display_name="Борис", is_self=False)
    m.participants["101"] = u1
    m.participants["103"] = u2
    m.speaker_timestamps["101"] = time.monotonic() - 15.0  # expired
    speaker_name, speaker_id, is_master = m.get_active_speaker(max_age_sec=2.0)
    assert speaker_name is None
    assert speaker_id is None


def test_get_active_speaker_single_friend_fallback():
    m = DiscordRpcManager()
    u1 = DiscordUser(id="101", username="faxon", display_name="Faxon", is_self=False)
    u_master = DiscordUser(id="102", username="gidrant7", display_name="Мастер", is_self=True)
    m.participants["101"] = u1
    m.participants["102"] = u_master
    # No speaking events recorded yet
    speaker_name, speaker_id, is_master = m.get_active_speaker(max_age_sec=2.0)
    assert speaker_name == "Faxon"
    assert speaker_id == "101"
    assert is_master is False
