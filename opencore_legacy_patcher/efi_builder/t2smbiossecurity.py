import os
import plistlib
import logging
import binascii
import sys

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class T2TahoePatcher:
    """
    Robust patcher for T2 Macs running macOS 26 (Tahoe) 
    Modeled after OCLP security.py logic.
    """

    def __init__(self, config: dict):
        self.config = config

    def _set_nested_value(self, path: str, value: any) -> None:
        """Helper to ensure nested dictionary paths exist before assignment."""
        node = self.config
        keys = path.split('.')
        for part in keys[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[keys[-1]] = value

    def _update_nvram_string(self, uuid: str, key: str, value: str) -> None:
        """Appends boot-args using token-based deduplication to prevent duplicates."""
        if "NVRAM" not in self.config: self.config["NVRAM"] = {"Add": {}}
        if "Add" not in self.config["NVRAM"]: self.config["NVRAM"]["Add"] = {}
        if uuid not in self.config["NVRAM"]["Add"]: self.config["NVRAM"]["Add"][uuid] = {}

        current_value = self.config["NVRAM"]["Add"][uuid].get(key, "")
        existing_tokens = set(current_value.split())
        new_tokens = value.strip().split()

        tokens_to_add = [t for t in new_tokens if t not in existing_tokens]
        
        if tokens_to_add:
            combined = (current_value.strip() + " " + " ".join(tokens_to_add)).strip()
            self.config["NVRAM"]["Add"][uuid][key] = combined

    def apply_patches(self):
        logging.info("Applying T2 Tahoe patches via nested validation...")

        # 1. Booter Quirks - Using Dotted Path Logic
        self._set_nested_value("Booter.Quirks.RebuildAppleMemoryMap", True)
        self._set_nested_value("Booter.Quirks.EnableWriteUnprotector", False)
        self._set_nested_value("Booter.Quirks.SyncRuntimePermissions", True)
        self._set_nested_value("Booter.Quirks.DevirtualiseMmio", True)

        # 2. Security & SMBIOS
        self._set_nested_value("PlatformInfo.UpdateSMBIOSMode", "Custom")
        self._set_nested_value("Misc.Security.SecureBootModel", "Disabled")

        # 3. NVRAM - Safe Token Injection
        APPLE_UUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
        self._update_nvram_string(APPLE_UUID, "boot-args", "amfi=0x80 ipc_control_port_options=0")
