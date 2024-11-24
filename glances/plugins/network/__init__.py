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
        # Update stats using the standard system lib
        stats = self.get_init_value()
    
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

    
    def get_mac_addresses():
        mac_dict = {}
        for interface in netifaces.interfaces():
            mac = netifaces.ifaddresses(interface).get(netifaces.AF_LINK)
            if mac:
                mac_dict[interface] = mac[0]['addr']
        return mac_dict

    
    def load_vendor_database(file_path="ieee-oui.txt"):
        """
        Load the vendor database from the ieee-oui.txt file.
        Each line is in the format: <MAC_PREFIX>\t<VENDOR_NAME>.
        """
        vendor_dict = {}
        try:
            with open(file_path, "r") as file:
                for line in file:
                    # Split each line into MAC prefix and vendor name
                    parts = line.strip().split("\t")
                    if len(parts) == 2:
                        mac_prefix = parts[0].upper()  # Ensure uppercase for matching
                        vendor_name = parts[1].strip()
                        vendor_dict[mac_prefix] = vendor_name
        except FileNotFoundError:
            print(f"Error: File {file_path} not found.")
        except Exception as e:
            print(f"Error reading the file: {e}")
        return vendor_dict

    
    def get_vendor(mac, vendor_db):
        """
        Match the MAC address prefix with the vendor database.
        Extracts the first 3 bytes of the MAC address, removes delimiters,
        and converts to uppercase for lookup.
        """
        mac_prefix = mac.replace(":", "").replace("-", "").upper()[:6]
        return vendor_db.get(mac_prefix, "Unknown Vendor")

    
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

