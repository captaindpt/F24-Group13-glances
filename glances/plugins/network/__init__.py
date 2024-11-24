#
# This file is part of Glances.
#
# SPDX-FileCopyrightText: 2022 Nicolas Hennion <nicolas@nicolargo.com>
#
# SPDX-License-Identifier: LGPL-3.0-only
#

"""Network plugin."""

import psutil
import netifaces
import os
from datetime import datetime

from glances.logger import logger
from glances.plugins.plugin.model import GlancesPluginModel

# Fields description
# description: human readable description
# short_name: shortname to use un UI
# unit: unit type
# rate: if True then compute and add *_gauge and *_rate_per_is fields
# min_symbol: Auto unit should be used if value > than 1 'X' (K, M, G)...
fields_description = {
    'interface_name': {'description': 'Interface name.'},
    'alias': {'description': 'Interface alias name (optional).'},
    'bytes_recv': {
        'description': 'Number of bytes received.',
        'rate': True,
        'unit': 'byte',
    },
    'bytes_sent': {
        'description': 'Number of bytes sent.',
        'rate': True,
        'unit': 'byte',
    },
    'bytes_all': {
        'description': 'Number of bytes received and sent.',
        'rate': True,
        'unit': 'byte',
    },
    'speed': {
        'description': 'Maximum interface speed (in bit per second). Can return 0 on some operating-system.',
        'unit': 'bitpersecond',
    },
    'is_up': {'description': 'Is the interface up ?', 'unit': 'bool'},
    'vendor': {'description': 'Network interface vendor name'},
}

# SNMP OID
# http://www.net-snmp.org/docs/mibs/interfaces.html
# Dict key = interface_name
snmp_oid = {
    'default': {
        'interface_name': '1.3.6.1.2.1.2.2.1.2',
        'bytes_recv': '1.3.6.1.2.1.2.2.1.10',
        'bytes_sent': '1.3.6.1.2.1.2.2.1.16',
    }
}

# Define the history items list
items_history_list = [
    {'name': 'bytes_recv_rate_per_sec', 'description': 'Download rate per second', 'y_unit': 'B/s'},
    {'name': 'bytes_sent_rate_per_sec', 'description': 'Upload rate per second', 'y_unit': 'B/s'},
]


class PluginModel(GlancesPluginModel):
    """Glances network plugin.

    stats is a list
    """

    def __init__(self, args=None, config=None):
        """Init the plugin."""
        super().__init__(
            args=args,
            config=config,
            items_history_list=items_history_list,
            fields_description=fields_description,
            stats_init_value=[],
        )

        # Set up debug logging
        self.debug_log = os.path.join(os.getcwd(), 'logs', 'network_debug.log')
        os.makedirs(os.path.dirname(self.debug_log), exist_ok=True)
        with open(self.debug_log, 'w') as f:
            f.write(f"=== Network Plugin Debug Log Started at {datetime.now()} ===\n\n")

        # Set debug mode flag (default to False)
        self.debug_mode = False

        # We want to display the stat in the curse interface
        self.display_curse = True

        # Hide stats if it has never been != 0
        if config is not None:
            self.hide_zero = config.get_bool_value(self.plugin_name, 'hide_zero', default=False)
        else:
            self.hide_zero = False
        self.hide_zero_fields = ['bytes_recv_rate_per_sec', 'bytes_sent_rate_per_sec']

        #  Add support for automatically hiding network interfaces that are down
        # or that don't have any IP addresses #2799
        self.hide_no_up = config.get_bool_value(self.plugin_name, 'hide_no_up', default=False)
        self.hide_no_ip = config.get_bool_value(self.plugin_name, 'hide_no_ip', default=False)

        # Force a first update because we need two updates to have the first stat
        self.update()
        self.refresh_timer.set(0)

    def get_key(self):
        """Return the key of the list."""
        return 'interface_name'

    # @GlancesPluginModel._check_decorator
    @GlancesPluginModel._log_result_decorator
    def update(self):
        """Update network stats using the input method.

        :return: list of stats dict (one dict per interface)
        """
        if self.input_method == 'local':
            stats = self.update_local()
        else:
            stats = self.get_init_value()

        # Update the stats
        self.stats = stats

        return self.stats

    @GlancesPluginModel._manage_rate
    def update_local(self):
        self.debug_log_write("\n=== Starting update_local() ===")
        # Update stats using the standard system lib
        stats = self.get_init_value()

        # Load vendor database
        vendor_db = self.load_vendor_database()
        
        # Get MAC addresses for all interfaces
        mac_addresses = self.get_mac_addresses()

        # Grab network interface stat using the psutil net_io_counter method
        # Example:
        # { 'veth4cbf8f0a': snetio(
        #   bytes_sent=102038421, bytes_recv=1263258,
        #   packets_sent=25046, packets_recv=14114,
        #   errin=0, errout=0, dropin=0, dropout=0), ... }
        try:
            net_io_counters = psutil.net_io_counters(pernic=True)
            net_status = psutil.net_if_stats()
            net_addrs = psutil.net_if_addrs()
        except OSError as e:
            logger.debug(f"Cannot retrieve network stats: {e}")
            return self.stats
    
        # Load vendor database once (cache for efficiency)
        if not hasattr(self, '_vendor_db'):
            self._vendor_db = load_vendor_database("ieee-oui.txt")
    
        for interface_name, interface_stat in net_io_counters.items():
            if not self.is_display(interface_name) or interface_name not in net_status:
                continue
    
            stat = self.filter_stats(interface_stat)
            stat.update(self.filter_stats(net_status[interface_name]))
            stat['key'] = self.get_key()
            stat['interface_name'] = interface_name
            stat['alias'] = self.has_alias(interface_name)
            stat['bytes_all'] = stat['bytes_sent'] + stat['bytes_recv']

            # Add vendor information if MAC address is available
            if interface_name in mac_addresses:
                stat['vendor'] = self.get_vendor(mac_addresses[interface_name], vendor_db)
            else:
                stat['vendor'] = "Unknown"

            # Interface speed in Mbps, convert it to bps
            # Can be always 0 on some OSes
            stat['speed'] = stat['speed'] * 1048576
    
            # Add MAC address and vendor name
            mac_info = net_addrs.get(interface_name, [])
            mac_address = next((addr.address for addr in mac_info if addr.family == psutil.AF_LINK), "N/A")
            stat['mac_address'] = mac_address
            stat['vendor'] = get_vendor(mac_address, self._vendor_db)
    
            stats.append(stat)
    
        return stats

    def update_views(self):
        """Update stats views."""
        # Call the father's method
        super().update_views()

        # Add specifics information
        # Alert
        for i in self.get_raw():
            # Skip alert if no timespan to measure
            if 'bytes_recv_rate_per_sec' not in i or 'bytes_sent_rate_per_sec' not in i:
                continue

            # Convert rate to bps (to be able to compare to interface speed)
            bps_rx = int(i['bytes_recv_rate_per_sec'] * 8)
            bps_tx = int(i['bytes_sent_rate_per_sec'] * 8)

            # Decorate the bitrate with the configuration file thresholds
            if_real_name = i['interface_name'].split(':')[0]
            alert_rx = self.get_alert(bps_rx, header=if_real_name + '_rx')
            alert_tx = self.get_alert(bps_tx, header=if_real_name + '_tx')

            # If nothing is define in the configuration file...
            # ... then use the interface speed (not available on all systems)
            if alert_rx == 'DEFAULT' and 'speed' in i and i['speed'] != 0:
                alert_rx = self.get_alert(current=bps_rx, maximum=i['speed'], header='rx')
            if alert_tx == 'DEFAULT' and 'speed' in i and i['speed'] != 0:
                alert_tx = self.get_alert(current=bps_tx, maximum=i['speed'], header='tx')

            # then decorates
            self.views[i[self.get_key()]]['bytes_recv']['decoration'] = alert_rx
            self.views[i[self.get_key()]]['bytes_sent']['decoration'] = alert_tx

    def get_mac_addresses(self):
        self.debug_log_write("Getting MAC addresses...")
        mac_dict = {}
        try:
            logger.debug("Getting MAC addresses for interfaces...")
            for interface in netifaces.interfaces():
                logger.debug(f"Getting MAC for interface: {interface}")
                self.debug_log_write(f"Checking interface: {interface}")
                try:
                    addrs = netifaces.ifaddresses(interface)
                    self.debug_log_write(f"Interface {interface} addresses: {addrs}")
                    mac = addrs.get(netifaces.AF_LINK)
                    if mac:
                        mac_dict[interface] = mac[0]['addr']
                        self.debug_log_write(f"Found MAC for {interface}: {mac[0]['addr']}")
                    else:
                        self.debug_log_write(f"No MAC found for {interface}")
                except Exception as e:
                    self.debug_log_write(f"Error getting MAC for {interface}: {str(e)}")
        except Exception as e:
            self.debug_log_write(f"Error in get_mac_addresses: {str(e)}")
        self.debug_log_write(f"Final MAC dictionary: {mac_dict}")
        return mac_dict

    def load_vendor_database(self, file_path="ieee-oui.txt"):
        """
        Load the vendor database from the ieee-oui.txt file.
        Each line is in the format: <OUI><TAB><Vendor>
        """
        self.debug_log_write(f"Loading vendor database from: {file_path}")
        vendor_dict = {}
        try:
            # First try to find the file in the same directory as the plugin
            current_dir = os.path.dirname(os.path.abspath(__file__))
            possible_paths = [
                os.path.join(current_dir, file_path),
                os.path.join(current_dir, '..', file_path),
                os.path.join(current_dir, '..', '..', file_path),
                file_path  # Try absolute path last
            ]
            
            file_found = False
            for path in possible_paths:
                self.debug_log_write(f"Trying path: {path}")
                if os.path.exists(path):
                    self.debug_log_write(f"Found database at: {path}")
                    file_found = True
                    with open(path, "r", encoding='utf-8') as file:
                        for line_num, line in enumerate(file, 1):
                            try:
                                line = line.strip()
                                if not line or line.startswith('#'):
                                    continue
                                    
                                parts = line.split("\t")
                                if len(parts) >= 2:
                                    mac_prefix = parts[0].strip().upper()
                                    vendor_name = parts[1].strip()
                                    if len(mac_prefix) == 6:  # Only store valid 6-character prefixes
                                        vendor_dict[mac_prefix] = vendor_name
                                        self.debug_log_write(f"Added vendor entry: {mac_prefix} -> {vendor_name}")
                            except Exception as e:
                                self.debug_log_write(f"Error parsing line {line_num}: {str(e)}")
                    break
                    
            if not file_found:
                self.debug_log_write("Database file not found in any expected location")
                
            self.debug_log_write(f"Loaded {len(vendor_dict)} vendor entries")
        except Exception as e:
            self.debug_log_write(f"Error loading vendor database: {str(e)}")
        return vendor_dict

    def get_vendor(self, mac, vendor_db):
        """
        Match the MAC address prefix with the vendor database.
        The database uses 6-character hex values without delimiters.
        """
        if self.debug_mode:
            self.debug_log_write(f"\n{'='*50}")
            self.debug_log_write(f"Looking up vendor for MAC: {mac}")
        
        try:
            # Step 1: Handle both delimited and non-delimited formats
            if ':' in mac or '-' in mac or '.' in mac:
                # Split into bytes and pad each with leading zeros
                bytes_list = mac.replace('-', ':').replace('.', ':').split(':')
                if self.debug_mode:
                    self.debug_log_write(f"Split into bytes: {bytes_list}")
                
                # Pad each byte with leading zeros
                normalized_bytes = [byte.zfill(2) for byte in bytes_list]
                if self.debug_mode:
                    self.debug_log_write(f"Normalized bytes: {normalized_bytes}")
                
                # Take first three bytes and join
                mac_prefix = ''.join(normalized_bytes[:3]).upper()
                if self.debug_mode:
                    self.debug_log_write(f"Final MAC prefix from bytes: {mac_prefix}")
            else:
                # Already in non-delimited format
                cleaned_mac = mac.upper()
                mac_prefix = cleaned_mac[:6]
                if self.debug_mode:
                    self.debug_log_write(f"Final MAC prefix from raw: {mac_prefix}")
            
            # Look up the vendor
            vendor = vendor_db.get(mac_prefix)
            if vendor:
                if self.debug_mode:
                    self.debug_log_write(f"Found vendor: {vendor}")
                return vendor
            
            if self.debug_mode:
                self.debug_log_write(f"No vendor found for prefix: {mac_prefix}")
            return "Unknown Vendor"
                
        except Exception as e:
            if self.debug_mode:
                self.debug_log_write(f"Error in get_vendor: {str(e)}")
            return "Unknown Vendor"

    def debug_log_write(self, message):
        """Write debug message to the log file."""
        if not self.debug_mode:
            return
            
        try:
            with open(self.debug_log, 'a') as f:
                f.write(f"[{datetime.now()}] {message}\n")
        except Exception as e:
            logger.error(f"Failed to write to debug log: {e}")

    def msg_curse(self, args=None, max_width=None):
        """Return the dict to display in the curse interface."""
        # Init the return message
        ret = []
    
        # Only process if stats exist and display plugin enable...
        if not self.stats or self.is_disabled():
            return ret
    
        # Max size for the interface name
        if max_width:
            name_max_width = max_width - 20  # Adjust width to make space for vendor info
        else:
            # No max_width defined, return an empty curse message
            logger.debug(f"No max_width defined for the {self.plugin_name} plugin, it will not be displayed.")
            return ret
    
        # Header
        msg = '{:{width}}'.format('NETWORK', width=name_max_width)
        ret.append(self.curse_add_line(msg, "TITLE"))
        msg = '{:>15}'.format('VENDOR')
        ret.append(self.curse_add_line(msg))

        if args.network_cumul:
            # Cumulative stats
            if args.network_sum:
                # Sum stats
                msg = '{:>14}'.format('Rx+Tx')
                ret.append(self.curse_add_line(msg))
            else:
                # Rx/Tx stats
                msg = '{:>7}'.format('Rx')
                ret.append(self.curse_add_line(msg))
                msg = '{:>7}'.format('Tx')
                ret.append(self.curse_add_line(msg))
        else:
            # Bitrate stats
            if args.network_sum:
                # Sum stats
                msg = '{:>14}'.format('Rx+Tx/s')
                ret.append(self.curse_add_line(msg))
            else:
                msg = '{:>7}'.format('Rx/s')
                ret.append(self.curse_add_line(msg))
                msg = '{:>7}'.format('Tx/s')
                ret.append(self.curse_add_line(msg))
    
        # Interface list (sorted by name)
        for i in self.sorted_stats():
            # Do not display interface in down state (issue #765)
            if ('is_up' in i) and (i['is_up'] is False):
                continue
            # Hide stats if never be different from 0 (issue #1787)
            if all(self.get_views(item=i[self.get_key()], key=f, option='hidden') for f in self.hide_zero_fields):
                continue
            # Format stats
            # Is there an alias for the interface name?
            if i['alias'] is None:
                if_name = i['interface_name'].split(':')[0]
            else:
                if_name = i['alias']
            if len(if_name) > name_max_width:
                # Cut interface name if it is too long
                if_name = '_' + if_name[-name_max_width + 1:]
    
            # Add vendor information
            vendor = i.get('vendor', 'Unknown Vendor')
    
            if args.byte:
                # Bytes per second (for dummy)
                to_bit = 1
                unit = ''
            else:
                # Bits per second (for real network administrator | Default)
                to_bit = 8
                unit = 'b'
    
            if args.network_cumul and 'bytes_recv' in i:
                rx = self.auto_unit(int(i['bytes_recv'] * to_bit)) + unit
                tx = self.auto_unit(int(i['bytes_sent'] * to_bit)) + unit
                ax = self.auto_unit(int(i['bytes_all'] * to_bit)) + unit
            elif 'bytes_recv_rate_per_sec' in i:
                rx = self.auto_unit(int(i['bytes_recv_rate_per_sec'] * to_bit)) + unit
                tx = self.auto_unit(int(i['bytes_sent_rate_per_sec'] * to_bit)) + unit
                ax = self.auto_unit(int(i['bytes_all_rate_per_sec'] * to_bit)) + unit
            else:
                # Avoid issue when a new interface is created on the fly
                # Example: start Glances, then start a new container
                continue
    
            # New line
            ret.append(self.curse_new_line())
            # Include vendor in the display line
            msg = f'{if_name} ({vendor})'
            ret.append(self.curse_add_line(msg))

            # Add vendor information
            vendor = i.get('vendor', 'Unknown')[:15]  # Truncate to 15 chars
            msg = '{:>15}'.format(vendor)
            ret.append(self.curse_add_line(msg))

            if args.network_sum:
                msg = f'{ax:>14}'
                ret.append(self.curse_add_line(msg))
            else:
                msg = f'{rx:>7}'
                ret.append(
                    self.curse_add_line(
                        msg, self.get_views(item=i[self.get_key()], key='bytes_recv', option='decoration')
                    )
                )
                msg = f'{tx:>7}'
                ret.append(
                    self.curse_add_line(
                        msg, self.get_views(item=i[self.get_key()], key='bytes_sent', option='decoration')
                    )
                )
    
        return ret

