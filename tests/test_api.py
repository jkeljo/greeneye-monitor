from datetime import timedelta
import unittest

from siobrultech_protocols.gem.packets import PacketFormatType

from greeneye.api import GemSettings, TemperatureUnit, _parse_all_settings


class TestAllSettings(unittest.TestCase):
    def setUp(self):
        self.settings = _parse_all_settings(
            "ALL\r\n00,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,00,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,D3,D3,D3,D2,D3,D3,D4,D3,D3,D3,D3,D3,D3,D3,D3,D2,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D2,D3,D3,D2,90,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,44,44,44,43,44,44,44,44,44,44,44,44,44,44,44,24,44,44,44,44,44,44,44,44,89,03,08,05,00,00,1E,00,87,00,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,18,26,A6,80,C7,18,25,81,87,C6,18,25,A4,40,27,F9,86,81,BF,78,6E,25,87,4E,84,88,4E,85,89,A6,8A,B0,83,C7,04,EB,C7,05,1B,A6,00,B2,82,C7,04,EA,C7,05,1A,55,82,D6,00,DC,B7,86,CD,04,B0,AF,01,8B,89,55,00,00,A6,20,00,02,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,AF,FF,35,84,65,DD,00,00,00,00,00,00,00,0F,00,00,00,00,00,01,01,00,00,01,07,FF,01,50,17,70,20,7F"
        )

    def testPacketFormat(self):
        self.assertEqual(PacketFormatType.BIN32_NET, self.settings.packet_format)

    def testPacketInterval(self):
        self.assertEqual(timedelta(seconds=5), self.settings.packet_send_interval)

    def testNumChannels(self):
        self.assertEqual(32, self.settings.num_channels)

    def testFahrenheit(self):
        self.assertEqual(TemperatureUnit.FAHRENHEIT, self.settings.temperature_unit)

    def testNetMetering(self):
        self.assertTrue(self.settings.channel_net_metering[30])

    def testNotNetMetering(self):
        self.assertFalse(self.settings.channel_net_metering[0])

    def testBadPacketFormat(self):
        self.settings = _parse_all_settings(
            "ALL\r\n00,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,00,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,40,D3,D3,D3,D2,D3,D3,D4,D3,D3,D3,D3,D3,D3,D3,D3,D2,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D2,D3,D3,D2,90,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,D3,44,44,44,43,44,44,44,44,44,44,44,44,44,44,44,24,44,44,44,44,44,44,44,44,89,03,0A,05,00,00,1E,00,87,00,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,01,18,26,A6,80,C7,18,25,81,87,C6,18,25,A4,40,27,F9,86,81,BF,78,6E,25,87,4E,84,88,4E,85,89,A6,8A,B0,83,C7,04,EB,C7,05,1B,A6,00,B2,82,C7,04,EA,C7,05,1A,55,82,D6,00,DC,B7,86,CD,04,B0,AF,01,8B,89,55,00,00,A6,20,00,02,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,AF,FF,35,84,65,DD,00,00,00,00,00,00,00,0F,00,00,00,00,00,01,01,00,00,01,07,FF,01,50,17,70,20,7F"
        )
        self.assertIsNone(self.settings.packet_format)