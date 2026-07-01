import packaging.version

from ..base import BaseHardware, HardwareVariant
from ...base import PatchType
from .....constants import Constants
from .....detections import device_probe
from .....datasets.os_data import os_data

class LegacyWireless(BaseHardware):

    def __init__(self, xnu_major, xnu_minor, os_build, global_constants: Constants) -> None:
        super().__init__(xnu_major, xnu_minor, os_build, global_constants)

    def name(self) -> str:
        return f"{self.hardware_variant()}: Legacy Wireless"

    def present(self) -> bool:
        if (
            isinstance(self._computer.wifi, device_probe.Broadcom)
            and self._computer.wifi.chipset in [device_probe.Broadcom.Chipsets.AirPortBrcm4331, device_probe.Broadcom.Chipsets.AirPortBrcm43224]
        ):
            return True

        if (
            isinstance(self._computer.wifi, device_probe.Atheros)
            and self._computer.wifi.chipset == device_probe.Atheros.Chipsets.AirPortAtheros40
        ):
            return True

        return False

    def native_os(self) -> bool:
        return self._xnu_major < os_data.monterey.value

    def hardware_variant(self) -> HardwareVariant:
        return HardwareVariant.NETWORKING

    @property
    def affected_by_cve_2024_23227(self) -> bool:
        """
        CVE-2024-23227 Prüfung mit Property-Decorator für sauberen Zugriff
        """
        # Tahoe (26) ist neuer als Sonoma, Patch wird benötigt
        if self._xnu_major > os_data.sonoma.value:
            return True

        marketing_version = self._constants.detected_os_version
        parsed_version = packaging.version.parse(marketing_version)

        if marketing_version.startswith("12"):
            return parsed_version >= packaging.version.parse("12.7.4")
        if marketing_version.startswith("13"):
            return parsed_version >= packaging.version.parse("13.6.5")
        if marketing_version.startswith("14"):
            return parsed_version >= packaging.version.parse("14.4")

        return False

    def _base_patch(self) -> dict:
        return {
            "Legacy Wireless": {
                PatchType.OVERWRITE_SYSTEM_VOLUME: {
                    "/usr/libexec": {
                        "airportd": "11.7.10" if not self.affected_by_cve_2024_23227 else "11.7.10-Sandbox",
                    },
                    "/System/Library/CoreServices": {
                        "WiFiAgent.app": "11.7.10",
                    },
                },
                PatchType.OVERWRITE_DATA_VOLUME: {
                    "/Library/Application Support/SkyLightPlugins": {
                        **({ "CoreWLAN.dylib": "SkyLightPlugins" } if self._xnu_major == os_data.monterey.value else {}),
                        **({ "CoreWLAN.txt": "SkyLightPlugins" } if self._xnu_major == os_data.monterey.value else {}),
                    },
                },
            },
        }

    def _extended_patch(self) -> dict:
        if self._xnu_major < os_data.ventura.value:
            return {}
        
        # Versions-String Logik für Sequoia und Tahoe
        suffix = f"-{self._xnu_major}" if self._xnu_major >= os_data.sequoia.value else ""
        version = f"12.7.2{suffix}"

        return {
            "Legacy Wireless Extended": {
                PatchType.OVERWRITE_SYSTEM_VOLUME: {
                    "/usr/libexec": {
                        "wps": version,
                        "wifip2pd": version,
                    },
                },
                PatchType.MERGE_SYSTEM_VOLUME: {
                    "/System/Library/Frameworks": {
                        "CoreWLAN.framework": version,
                    },
                    "/System/Library/PrivateFrameworks": {
                        "CoreWiFi.framework": version,
                        "IO80211.framework": version,
                        "WiFiPeerToPeer.framework": version,
                    },
                }
            },
        }

    def patches(self) -> dict:
        if self.native_os():
            return {}

        return {
            **self._base_patch(),
            **self._extended_patch(),
        }
