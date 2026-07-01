"""
modern_wireless.py: Modern Wireless detection
"""

from ..base import BaseHardware, HardwareVariant

from ...base import PatchType

from .....constants  import Constants
from .....detections import device_probe

from .....datasets.os_data import os_data


class ModernWireless(BaseHardware):

    def __init__(self, xnu_major, xnu_minor, os_build, global_constants: Constants) -> None:
        super().__init__(xnu_major, xnu_minor, os_build, global_constants)


    def name(self) -> str:
        """
        Display name for end users
        """
        return f"{self.hardware_variant()}: Modern Wireless"


    def present(self) -> bool:
        """
        Targeting Modern Wireless
        """
        return isinstance(self._computer.wifi, device_probe.Broadcom) and (
            self._computer.wifi.chipset in [
                device_probe.Broadcom.Chipsets.AirPortBrcm4360,
                device_probe.Broadcom.Chipsets.AirportBrcmNIC,
                # We don't officially support this chipset, however we'll throw a bone to hackintosh users
                device_probe.Broadcom.Chipsets.AirPortBrcmNICThirdParty,
            ]
        )


    def native_os(self) -> bool:
        """
        Dropped support with macOS 14, Sonoma
        """
        return self._xnu_major < os_data.sonoma.value


    def hardware_variant(self) -> HardwareVariant:
        """
        Type of hardware variant
        """
        return HardwareVariant.NETWORKING


    def patches(self) -> dict:
        """
        Patches for Modern Wireless
        """
        if self.native_os() is True:
            return {}

        # Workaround for missing airportd in macOS 26 Tahoe (13.7.2-25)
        # Determine the base version for Tahoe (macOS 26) and other versions
        if self._xnu_major == os_data.tahoe:  # macOS 26 Tahoe
            # For Tahoe, use fallback versions since 13.7.2-25 is missing airportd
            base_version = "13.7.2-24"  # Fallback to Ventura version
            wifi_agent_version = "14.7.2"  # Use Sonoma version since 15.1 doesn't exist
        elif self._xnu_major >= os_data.sequoia:  # macOS 14+ Sonoma/Sequoia
            base_version = f"13.7.2-{self._xnu_major}"
            wifi_agent_version = "14.7.2"
        else:  # macOS 13 Ventura and earlier
            base_version = f"13.7.2-{self._xnu_major}"
            wifi_agent_version = None

        # Build the patch dictionary
        patches_dict = {
            "Modern Wireless": {
                PatchType.OVERWRITE_SYSTEM_VOLUME: {
                    "/usr/libexec": {
                        "airportd": base_version,
                        "wifip2pd": base_version,
                    },
                },
                PatchType.MERGE_SYSTEM_VOLUME: {
                    "/System/Library/Frameworks": {
                        "CoreWLAN.framework": base_version,
                    },
                    "/System/Library/PrivateFrameworks": {
                        "CoreWiFi.framework":       base_version,
                        "IO80211.framework":        base_version,
                        "WiFiPeerToPeer.framework": base_version,
                    },
                }
            },
        }

        # Add WiFiAgent.app for Sonoma and later
        if wifi_agent_version:
            patches_dict["Modern Wireless"][PatchType.OVERWRITE_SYSTEM_VOLUME][
                "/System/Library/CoreServices"
            ] = {"WiFiAgent.app": wifi_agent_version}

        return patches_dict
