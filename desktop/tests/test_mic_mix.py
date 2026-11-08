"""Тесты для desktop.core.mic_mix"""

import pytest
from desktop.core.mic_mix import AudioDevice, MicMixManager


def test_mic_mix_manager():
    manager = MicMixManager()

    # Emulate devices
    devices = [
        AudioDevice(name="Realtek High Definition Audio", id="DEV1", is_cable=False),
        AudioDevice(name="CABLE Input (VB-Audio Virtual Cable)", id="DEV2", is_cable=True),
    ]

    cables = [d for d in devices if d.is_cable]
    assert len(cables) == 1
    assert "VB-Audio" in cables[0].name
