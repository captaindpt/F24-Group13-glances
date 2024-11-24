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
3CD92B\tHewlett Packard"""
        
        # Write test database to a temporary file
        self.test_db_path = os.path.join(os.path.dirname(__file__), 'test_ieee_oui.txt')
        with open(self.test_db_path, 'w') as f:
            f.write(self.test_db_content)

    def tearDown(self):
        """Clean up test fixtures."""
        # Remove temporary test database
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_load_vendor_database(self):
        """Test loading vendor database from file with real vendor entries."""
        vendor_db = self.plugin.load_vendor_database(self.test_db_path)
        self.assertEqual(vendor_db['E043DB'], 'Shenzhen ViewAt Technology Co.,Ltd.')
        self.assertEqual(vendor_db['3CD92B'], 'Hewlett Packard')

    def test_get_vendor_exact_match(self):
        """Test vendor lookup with exact MAC prefix match using real vendor data."""
        vendor_db = self.plugin.load_vendor_database(self.test_db_path)
        vendor = self.plugin.get_vendor('E0:43:DB:12:34:56', vendor_db)
        self.assertEqual(vendor, 'Shenzhen ViewAt Technology Co.,Ltd.')

    def test_get_vendor_case_insensitive(self):
        """Test vendor lookup with different case combinations using real vendor data."""
        vendor_db = self.plugin.load_vendor_database(self.test_db_path)
        vendor1 = self.plugin.get_vendor('e0:43:db:12:34:56', vendor_db)
        vendor2 = self.plugin.get_vendor('E0:43:DB:12:34:56', vendor_db)
        self.assertEqual(vendor1, vendor2)
        self.assertEqual(vendor1, 'Shenzhen ViewAt Technology Co.,Ltd.')

    def test_vendor_lookup_with_leading_zeros(self):
        """Test vendor lookup with real MAC addresses that have leading zeros."""
        vendor_db = self.plugin.load_vendor_database(self.test_db_path)
        vendor = self.plugin.get_vendor('3C:D9:2B:00:00:00', vendor_db)
        self.assertEqual(vendor, 'Hewlett Packard')

    def test_vendor_lookup_different_formats(self):
        """Test vendor lookup with different MAC address formats using real vendor data."""
        vendor_db = self.plugin.load_vendor_database(self.test_db_path)
        
        # Test different delimiters
        vendor1 = self.plugin.get_vendor('E0:43:DB:12:34:56', vendor_db)  # Colon
        vendor2 = self.plugin.get_vendor('E0-43-DB-12-34-56', vendor_db)  # Hyphen
        vendor3 = self.plugin.get_vendor('E0.43.DB.12.34.56', vendor_db)  # Dot
        vendor4 = self.plugin.get_vendor('E043DB123456', vendor_db)       # No delimiter
        
        self.assertEqual(vendor1, 'Shenzhen ViewAt Technology Co.,Ltd.')
        self.assertEqual(vendor1, vendor2)
        self.assertEqual(vendor2, vendor3)
        self.assertEqual(vendor3, vendor4)
