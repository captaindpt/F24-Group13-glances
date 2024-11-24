import unittest
import os
from glances.plugins.network import PluginModel as NetworkPlugin

class MockConfig:
    """Mock configuration for testing."""
    def get_bool_value(self, plugin_name, key, default=False):
        return default

    def get_value(self, *args, **kwargs):
        return None

class TestNetworkPlugin(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        # Create mock config
        mock_config = MockConfig()
        
        # Initialize plugin with mock config
        self.plugin = NetworkPlugin(args=None, config=mock_config)
        self.plugin.debug_mode = True  # Enable debug mode for tests
        
        # Create a temporary vendor database with real MAC prefixes
        self.test_db_content = """# Test database with real vendor entries
E043DB\tShenzhen ViewAt Technology Co.,Ltd.
3CD92B\tHewlett Packard
0050BA\tD-Link Corporation
18622C\tSagemcom Broadband SAS
CC46D6\tCisco Systems, Inc
00CDFE\tApple, Inc.
38F23E\tMicrosoft Mobile Oy
001A11\tGoogle, Inc.
000347\tIntel Corporation
000D0B\tBUFFALO.INC
"""
        self.test_db_path = "test_ieee_oui.txt"
        with open(self.test_db_path, "w") as f:
            f.write(self.test_db_content)
            
    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_get_vendor_exact_match(self):
        """Test vendor lookup with exact MAC prefix match using real vendor data."""
        vendor_db = self.plugin.load_vendor_database(self.test_db_path)
        
        # Test cases with different real MAC address formats
        test_cases = [
            ("E0:43:DB:12:34:56", "Shenzhen ViewAt Technology Co.,Ltd."),  # Shenzhen ViewAt
            ("3C:D9:2B:00:00:00", "Hewlett Packard"),                      # HP
            ("00:50:BA:FF:FF:FF", "D-Link Corporation"),                   # D-Link
            ("18:62:2C:AB:CD:EF", "Sagemcom Broadband SAS"),              # Sagemcom
            ("CC:46:D6:11:22:33", "Cisco Systems, Inc"),                  # Cisco
            ("FF:FF:FF:FF:FF:FF", "Unknown Vendor"),                      # Unknown vendor
        ]
        
        for mac, expected_vendor in test_cases:
            with self.subTest(mac=mac):
                vendor = self.plugin.get_vendor(mac, vendor_db)
                self.assertEqual(vendor, expected_vendor)

    def test_get_vendor_case_insensitive(self):
        """Test vendor lookup with different case combinations using real vendor data."""
        vendor_db = self.plugin.load_vendor_database(self.test_db_path)
        
        test_cases = [
            ("00:CD:FE:00:11:22", "Apple, Inc."),                         # Normal case
            ("00:cd:fe:00:11:22", "Apple, Inc."),                         # Lowercase
            ("00:CD:FE:00:11:22", "Apple, Inc."),                         # Mixed case
            ("38:f2:3e:44:55:66", "Microsoft Mobile Oy"),                 # Lowercase
            ("38:F2:3E:44:55:66", "Microsoft Mobile Oy"),                 # Uppercase
        ]
        
        for mac, expected_vendor in test_cases:
            with self.subTest(mac=mac):
                vendor = self.plugin.get_vendor(mac, vendor_db)
                self.assertEqual(vendor, expected_vendor)

    def test_load_vendor_database(self):
        """Test loading vendor database from file with real vendor entries."""
        vendor_db = self.plugin.load_vendor_database(self.test_db_path)
        
        # Check if all vendors are loaded correctly
        self.assertEqual(len(vendor_db), 10)  # We have 10 real vendor entries
        self.assertEqual(vendor_db["E043DB"], "Shenzhen ViewAt Technology Co.,Ltd.")
        self.assertEqual(vendor_db["3CD92B"], "Hewlett Packard")
        self.assertEqual(vendor_db["0050BA"], "D-Link Corporation")
        self.assertEqual(vendor_db["CC46D6"], "Cisco Systems, Inc")
        self.assertEqual(vendor_db["00CDFE"], "Apple, Inc.")

    def test_vendor_lookup_with_leading_zeros(self):
        """Test vendor lookup with real MAC addresses that have leading zeros."""
        vendor_db = self.plugin.load_vendor_database(self.test_db_path)
        
        test_cases = [
            ("00:03:47:00:00:00", "Intel Corporation"),    # Intel with full format
            ("0:3:47:0:0:0", "Intel Corporation"),         # Intel without leading zeros
            ("000347000000", "Intel Corporation"),         # Intel without delimiters
            ("00-03-47-00-00-00", "Intel Corporation"),    # Intel with dashes
        ]
        
        for mac, expected_vendor in test_cases:
            with self.subTest(mac=mac):
                vendor = self.plugin.get_vendor(mac, vendor_db)
                self.assertEqual(vendor, expected_vendor)

    def test_vendor_lookup_different_formats(self):
        """Test vendor lookup with different MAC address formats using real vendor data."""
        vendor_db = self.plugin.load_vendor_database(self.test_db_path)
        
        test_cases = [
            ("000D0B123456", "BUFFALO.INC"),              # No separators
            ("00-0D-0B-12-34-56", "BUFFALO.INC"),         # Dash separators
            ("00:0D:0B:12:34:56", "BUFFALO.INC"),         # Colon separators
            ("00.0D.0B.12.34.56", "BUFFALO.INC"),         # Dot separators
            ("0:d:b:12:34:56", "BUFFALO.INC"),            # Short format
        ]
        
        for mac, expected_vendor in test_cases:
            with self.subTest(mac=mac):
                vendor = self.plugin.get_vendor(mac, vendor_db)
                self.assertEqual(vendor, expected_vendor)

if __name__ == '__main__':
    unittest.main()
