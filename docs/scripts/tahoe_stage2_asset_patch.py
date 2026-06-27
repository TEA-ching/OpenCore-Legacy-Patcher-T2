#!/usr/bin/env python3
"""
Inspect and optionally patch a staged macOS Tahoe installer UpdateBundle.

This version dynamically reads the host identity and mirrors it against the 
staged BuildManifest.plist, completely eliminating hardcoded SMBIOS assumptions.
"""

from __future__ import annotations

import argparse
import copy
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

TAHOE_MAJOR = "26."
MSU_VARIANTS = ("Customer Software Update", "macOS Customer Software Update")
LOG_FATAL_PATTERNS = (
    "Operation: OSIMSUInstallElement failed",
    "com.apple.osinstall:-81 > NSPOSIXErrorDomain:2",
    "Failed to get paths for system root hash/mtree manifest",
    "Operation: Install Mobile Software Update failed",
    "Error Domain=com.apple.osinstall Code=-81",
    "Removing incomplete system volume",
)
LOG_FAILURE_MARKERS = (
    "------- Install Failed -------",
)
LOG_IDENTITY_WARN_PATTERNS = (
    "AKAnisetteError",
    "AKAttestationErrorDomain",
    "AKAuthenticationError",
    "DeviceIdentity not available",
    "Failed to get localUserUUID",
    "No Anisette for you today",
    "Failed to get bridge device",
    "Failed to find incompatible apps list",
)


def _load_plist(path: Path) -> dict:
    with path.open("rb") as plist_file:
        return plistlib.load(plist_file)


def _save_plist(path: Path, data: dict) -> None:
    original_mode = path.stat().st_mode
    temporary_write = not path.exists() or not (original_mode & 0o200)
    if temporary_write:
        path.chmod(original_mode | 0o200)
    try:
        with path.open("wb") as plist_file:
            plistlib.dump(data, plist_file, sort_keys=False)
    finally:
        if temporary_write and path.exists():
            path.chmod(original_mode)


def _backup(path: Path) -> Path:
    backup = path.with_name(f"{path.name}.oclp-tahoe-stage2-backup")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def _candidate_roots(paths: list[str]) -> list[Path]:
    roots: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if path.is_dir():
            roots.append(path)
        install_data = path / "macOS Install Data"
        if install_data.is_dir():
            roots.append(install_data)
    for volume in Path("/Volumes").glob("*"):
        install_data = volume / "macOS Install Data"
        if install_data.is_dir():
            roots.append(install_data)

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        resolved = str(root)
        if resolved not in seen:
            deduped.append(root)
            seen.add(resolved)
    return deduped


def _visible_volume_summary() -> list[str]:
    summaries: list[str] = []
    for volume in sorted(Path("/Volumes").glob("*")):
        try:
            if volume.is_symlink():
                continue
            install_data = volume / "macOS Install Data"
            suffix = " (has macOS Install Data)" if install_data.is_dir() else ""
            summaries.append(f"{volume}{suffix}")
        except OSError:
            continue
    return summaries


def _candidate_log_paths(paths: list[str]) -> list[Path]:
    candidates: list[Path] = []
    explicit_paths = [Path(item).expanduser() for item in paths]
    search_roots = explicit_paths if explicit_paths else [Path("/Volumes")]

    for root in search_roots:
        if root.is_file():
            candidates.append(root)
            continue
        if not root.exists() or not root.is_dir():
            continue
        for name in (
            "macOS Install Data/ia.log",
            "macOS Install Data/install.log",
            "install-log-latest.log",
        ):
            candidate = root / name
            if candidate.exists():
                candidates.append(candidate)
        try:
            candidates.extend(root.glob("**/Installer Log*.txt"))
            candidates.extend(root.glob("**/install-log*.log"))
        except OSError:
            continue

    system_log = Path("/var/log/install.log")
    if system_log.exists():
        candidates.append(system_log)

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(candidate)
    return deduped


def _tail_text(path: Path, byte_limit: int = 1_000_000) -> str:
    try:
        with path.open("rb") as log_file:
            log_file.seek(0, 2)
            size = log_file.tell()
            log_file.seek(max(0, size - byte_limit))
            return log_file.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _diagnose_install_logs(paths: list[str]) -> bool:
    logs = _candidate_log_paths(paths)
    printed = False
    fatal_hits: list[str] = []
    failure_markers: list[str] = []
    warning_hits: list[str] = []

    for log_path in logs:
        text = _tail_text(log_path)
        if not text:
            continue
        for line in text.splitlines():
            if any(pattern in line for pattern in LOG_FATAL_PATTERNS):
                fatal_hits.append(f"{log_path}: {line.strip()}")
            elif any(pattern in line for pattern in LOG_FAILURE_MARKERS):
                failure_markers.append(f"{log_path}: {line.strip()}")
            elif any(pattern in line for pattern in LOG_IDENTITY_WARN_PATTERNS):
                warning_hits.append(f"{log_path}: {line.strip()}")

    if fatal_hits:
        print("\nInstall log fatal indicators:")
        for item in fatal_hits[-12:]:
            print(f"  {item}")
        printed = True

    if failure_markers:
        print("\nInstall failure markers without a parsed cause:")
        for item in failure_markers[-8:]:
            print(f"  {item}")
        print("  Note: a failure marker proves the installer stopped, but it does not identify the cause by itself.")
        printed = True

    if warning_hits:
        print("\nInstall log identity/network warnings:")
        for item in warning_hits[-12:]:
            print(f"  {item}")
        print(
            "  Note: these warnings are not treated as the fatal cause unless an OSInstaller "
            "Install Failed line ties them to the failure."
        )
        printed = True

    if not printed and logs:
        print("\nInstall log scan: no known Tahoe Stage-2 fatal indicators found in scanned logs.")
        printed = True
    elif not logs:
        print("\nInstall log scan: no installer logs found on mounted volumes or /var/log/install.log.")
        printed = True

    return bool(fatal_hits)


def _required_paths_exist(asset_data: Path, identity: dict, *, require_additional_paths: bool = True) -> tuple[bool, list[str]]:
    missing: list[str] = []
    manifest = identity.get("Manifest", {})
    for key in ("x86,SystemVolume", "x86,SystemVolumeCanonicalMetadata"):
        item = manifest.get(key)
        if not item:
            missing.append(f"{key}: missing manifest entry")
            continue
        info = item.get("Info", {})
        source_value = info.get("Path")
        if not source_value:
            missing.append(f"{key}: missing Info/Path")
            continue
        if not _resolve_existing_manifest_path(asset_data, source_value):
            missing.append(f"{key}: Path does not exist: {source_value}")

        additional_value = info.get("AdditionalManifestPath")
        if not additional_value:
            missing.append(f"{key}: missing Info/AdditionalManifestPath")
            continue
        if require_additional_paths:
            for destination in _manifest_destination_candidates(asset_data, additional_value):
                if not destination.exists():
                    missing.append(f"{key}: AdditionalManifestPath does not exist: {destination.relative_to(asset_data)}")
    return not missing, missing


def _resolve_existing_manifest_path(asset_data: Path, value: str) -> Path | None:
    for candidate in (asset_data / value, asset_data / "boot" / value):
        if candidate.exists():
            return candidate
    return None


def _manifest_destination_candidates(asset_data: Path, value: str) -> list[Path]:
    candidates: list[Path] = []
    for candidate in (asset_data / value, asset_data / "boot" / value):
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _copy_manifest_if_needed(source: Path, destination: Path, asset_data: Path, apply: bool) -> list[str]:
    messages: list[str] = []
    if destination.exists():
        if destination.read_bytes() == source.read_bytes():
            messages.append(f"Additional manifest already exists and matches: {destination.relative_to(asset_data)}")
            return messages
        raise RuntimeError(
            "Refusing materialize patch: destination already exists with different content: "
            f"{destination}"
        )

    messages.append(f"Materialize {destination.relative_to(asset_data)} from {source.relative_to(asset_data)}")
    if apply:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        messages.append(f"Applied additional manifest copy: {destination}")
    return messages


def _identity_info(identity: dict) -> dict:
    info = identity.get("Info", {})
    return {
        "variant": info.get("Variant"),
        "device_class": info.get("DeviceClass"),
        "product_type": info.get("Ap,ProductType"),
    }


def _read_ioreg_properties(class_name: str) -> dict[str, str]:
    try:
        output = subprocess.run(
            ["/usr/sbin/ioreg", "-rd1", "-c", class_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return {}

    properties: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        for key in ("model", "board-id", "bridge-model"):
            prefix = f'"{key}" = '
            if not line.startswith(prefix):
                continue
            value = line[len(prefix):].strip()
            if value.startswith("<\"") and value.endswith("\">"):
                value = value[2:-2]
            elif value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            properties[key] = value
    return properties


def _get_live_host_identity() -> dict[str, str] | None:
    """Dynamically discover native host hardware parameters from ioreg."""
    identity = _read_ioreg_properties("IOPlatformExpertDevice")
    
    if "bridge-model" not in identity:
        t2_plane = _read_ioreg_properties("AppleT2AppleSecureEnclavePad")
        if "bridge-model" in t2_plane:
            identity["bridge-model"] = t2_plane["bridge-model"]
        else:
            bcw_plane = _read_ioreg_properties("AppleBCW")
            if "bridge-model" in bcw_plane:
                identity["bridge-model"] = bcw_plane["bridge-model"]

    if "model" in identity and "board-id" in identity and "bridge-model" in identity:
        return {
            "product_type": identity["model"],
            "board_id": identity["board-id"],
            "hardware_model": identity["bridge-model"],
            "device_class": identity["bridge-model"].lower()
        }
    return None


def _find_blueprint_identity(asset_data: Path, manifest: dict, preferred_device_class: str | None) -> dict | None:
    """
    Finds a usable blueprint inside the BuildManifest.
    Prioritizes the native host's device class if supplied, otherwise falls back
    to scanning for any valid CustomerInstall identity that has required source asset data paths.
    """
    identities = manifest.get("BuildIdentities", [])
    
    if preferred_device_class:
        for identity in identities:
            info = _identity_info(identity)
            if info["variant"] == "CustomerInstall" and str(info["device_class"]).lower() == preferred_device_class.lower():
                ok, _ = _required_paths_exist(asset_data, identity, require_additional_paths=False)
                if ok:
                    return identity

    # Dynamic Fallback: Sweep manifest for any valid donor identity
    for identity in identities:
        info = _identity_info(identity)
        if info["variant"] == "CustomerInstall" and info["device_class"]:
            ok, _ = _required_paths_exist(asset_data, identity, require_additional_paths=False)
            if ok:
                return identity
                
    return None


def _has_msu_identity(asset_data: Path, manifest: dict, device_class: str) -> bool:
    for identity in manifest.get("BuildIdentities", []):
        info = _identity_info(identity)
        if info["variant"] not in MSU_VARIANTS:
            continue
        if str(info["device_class"]).lower() == str(device_class).lower():
            ok, _ = _required_paths_exist(asset_data, identity)
            if ok:
                return True
    return False


def _materialize_additional_manifests(asset_data: Path, identity: dict, apply: bool) -> list[str]:
    messages: list[str] = []
    manifest = identity.get("Manifest", {})
    for key in ("x86,SystemVolume", "x86,SystemVolumeCanonicalMetadata"):
        item = manifest.get(key)
        if not item:
            raise RuntimeError(f"Refusing materialize patch: {key} is missing from source identity.")
        info = item.get("Info", {})
        source_value = info.get("Path")
        destination_value = info.get("AdditionalManifestPath")
        if not source_value or not destination_value:
            raise RuntimeError(f"Refusing materialize patch: {key} lacks Path or AdditionalManifestPath.")

        source = _resolve_existing_manifest_path(asset_data, source_value)
        if not source:
            raise RuntimeError(f"Refusing materialize patch: source manifest does not exist: {source_value}")

        for destination in _manifest_destination_candidates(asset_data, destination_value):
            messages.extend(_copy_manifest_if_needed(source, destination, asset_data, apply))
    return messages


def _bootcache_destination_for(asset_data: Path, object_name: str) -> Path | None:
    bootcaches_path = asset_data / "boot" / "usr" / "standalone" / "bootcaches.plist"
    if not bootcaches_path.exists():
        return None

    bootcaches = _load_plist(bootcaches_path)
    boot_objects = bootcaches.get("bless2", {}).get("BootObjects", {})
    if not isinstance(boot_objects, dict):
        return None

    entry = boot_objects.get(object_name)
    if not isinstance(entry, dict):
        return None

    destination = entry.get("DestinationPath")
    if not isinstance(destination, str) or not destination.startswith("./"):
        return None

    return asset_data / "boot" / destination[2:]


def _materialize_bootcache_system_volume(asset_data: Path, identity: dict, apply: bool) -> list[str]:
    messages: list[str] = []
    destination = _bootcache_destination_for(asset_data, "SystemVolume")
    if not destination:
        return ["bootcaches.plist does not request a SystemVolume destination; skipping root hash materialization."]

    manifest_item = identity.get("Manifest", {}).get("x86,SystemVolume")
    if not manifest_item:
        raise RuntimeError("Refusing bootcache root hash patch: x86,SystemVolume is missing from source identity.")

    source_value = manifest_item.get("Info", {}).get("Path")
    if not source_value:
        raise RuntimeError("Refusing bootcache root hash patch: x86,SystemVolume lacks Info/Path.")

    source = _resolve_existing_manifest_path(asset_data, source_value)
    if not source:
        raise RuntimeError(f"Refusing bootcache root hash patch: source manifest does not exist: {source_value}")

    if destination.exists():
        if destination.read_bytes() == source.read_bytes():
            return [f"bootcaches SystemVolume root hash already matches: {destination}"]
        raise RuntimeError(f"Refusing bootcache root hash patch: destination has unique content: {destination}")

    messages.append(f"Materialize bootcaches SystemVolume root hash {destination.relative_to(asset_data)} from {source.relative_to(asset_data)}")
    if apply:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        messages.append(f"Applied bootcaches SystemVolume root hash copy: {destination}")
    return messages


def _patch_info_plist(info_path: Path, host_meta: dict | None, apply: bool) -> list[str]:
    if not host_meta:
        return ["Skipping Info.plist generation: no live host identity detected."]
        
    info = _load_plist(info_path)
    messages: list[str] = []
    product_version = str(info.get("ProductVersion", ""))
    if not product_version.startswith(TAHOE_MAJOR):
        raise RuntimeError(f"Refusing Info.plist patch: ProductVersion is {product_version!r}, not Tahoe 26.x")

    desired = {
        "ProductType": host_meta["product_type"],
        "HardwareModel": host_meta["hardware_model"],
        "DeviceClass": host_meta["hardware_model"].split("ap")[0], # Dynamic derivation fallback
    }
    changes = {key: (info.get(key), value) for key, value in desired.items() if info.get(key) != value}
    if not changes:
        return [f"Info.plist already matches dynamic host identity: {host_meta['product_type']}."]

    for key, (old, new) in changes.items():
        messages.append(f"Info.plist: {key}: {old!r} -> {new!r}")
        info[key] = new

    if apply:
        backup = _backup(info_path)
        _save_plist(info_path, info)
        messages.append(f"Applied Info.plist patch. Backup: {backup}")
    return messages


def _patch_asset_supported_models(info_path: Path, host_meta: dict | None, apply: bool) -> list[str]:
    if not host_meta:
        return []
    info = _load_plist(info_path)
    messages: list[str] = []
    properties = info.get("MobileAssetProperties")
    if not isinstance(properties, dict):
        return []

    supported = properties.get("SupportedDeviceModels")
    if not isinstance(supported, list):
        return []

    desired = [host_meta["hardware_model"], host_meta["board_id"], host_meta["product_type"]]
    changed = False
    existing_lower = {str(item).lower() for item in supported}
    for value in desired:
        if value.lower() in existing_lower:
            continue
        supported.append(value)
        existing_lower.add(value.lower())
        changed = True
        messages.append(f"UpdateBundle Info.plist: add SupportedDeviceModels entry {value!r}")

    if not changed:
        return ["UpdateBundle Info.plist already covers host identity profile parameters."]

    if apply:
        backup = _backup(info_path)
        _save_plist(info_path, info)
        messages.append(f"Applied UpdateBundle supported-device patch. Backup: {backup}")
    return messages


def _patch_msu_manifest(
    asset_data: Path,
    manifest_path: Path,
    apply: bool,
    host_meta: dict | None,
    allow_missing_additional_paths: bool,
) -> list[str]:
    manifest = _load_plist(manifest_path)
    messages: list[str] = []
    
    preferred_class = host_meta["device_class"] if host_meta else None
    source_identity = _find_blueprint_identity(asset_data, manifest, preferred_class)
    
    if not source_identity:
        raise RuntimeError("Refusing MSU manifest patch: no matching or fallback CustomerInstall identity with existing source assets could be found.")

    complete, missing = _required_paths_exist(asset_data, source_identity)
    if not complete and not allow_missing_additional_paths:
        joined_missing = "; ".join(missing)
        raise RuntimeError(
            "Refusing MSU manifest patch: Target structural blueprint additional paths are not materialized. "
            f"Missing: {joined_missing}. Re-run with --materialize-additional-manifests."
        )

    source_info = _identity_info(source_identity)
    messages.append(f"Selected blueprint identity: DeviceClass={source_info['device_class']}, ProductType={source_info['product_type']}")

    existing_variants = {
        _identity_info(identity)["variant"]
        for identity in manifest.get("BuildIdentities", [])
    }
    variants_to_add = [variant for variant in MSU_VARIANTS if variant in existing_variants]
    if not variants_to_add:
        raise RuntimeError("Refusing MSU manifest patch: this BuildManifest has no matching MSU variant configurations to mirror.")

    # Always attempt to patch for the active target blueprint class and the host class if different
    target_device_classes = [source_info["device_class"]]
    if host_meta and host_meta["device_class"].lower() not in [str(x).lower() for x in target_device_classes]:
        target_device_classes.append(host_meta["device_class"])

    additions: list[dict] = []
    for device_class in target_device_classes:
        if not device_class:
            continue
        if _has_msu_identity(asset_data, manifest, device_class):
            messages.append(f"BuildManifest already contains a usable {device_class} MSU structure.")
            continue
        for variant in variants_to_add:
            clone = copy.deepcopy(source_identity)
            clone_info = clone.setdefault("Info", {})
            clone_info["Variant"] = variant
            clone_info["DeviceClass"] = device_class
            additions.append(clone)
            messages.append(f"BuildManifest: add cloned {device_class} identity for Variant={variant!r}")

    if apply:
        if additions:
            backup = _backup(manifest_path)
            manifest.setdefault("BuildIdentities", []).extend(additions)
            _save_plist(manifest_path, manifest)
            messages.append(f"Applied BuildManifest patch. Backup: {backup}")
        else:
            messages.append("No BuildManifest changes required.")
    return messages


def _inspect(root: Path, apply: bool, materialize_additional: bool, materialize_bootcache_system_volume: bool, patch_msu: bool) -> None:
    asset_data = root / "UpdateBundle" / "AssetData"
    info_path = asset_data / "Info.plist"
    update_bundle_info_path = root / "UpdateBundle" / "Info.plist"
    manifest_path = asset_data / "boot" / "BuildManifest.plist"
    if not info_path.exists() or not manifest_path.exists():
        return

    print(f"\nStaged install data: {root}")
    info = _load_plist(info_path)
    print(
        "Current Info.plist configuration: "
        f"ProductVersion={info.get('ProductVersion')}, "
        f"ProductType={info.get('ProductType')}, "
        f"HardwareModel={info.get('HardwareModel')}"
    )

    manifest = _load_plist(manifest_path)
    host_meta = _get_live_host_identity()
    
    if host_meta:
        print(f"Discovered Live Host Profile: {host_meta['product_type']} ({host_meta['hardware_model']})")
    else:
        print("WARNING: Host platform variables could not be derived from ioreg. Skipping environment matching.", file=sys.stderr)

    preferred_class = host_meta["device_class"] if host_meta else None
    blueprint = _find_blueprint_identity(asset_data, manifest, preferred_class)
    
    if blueprint:
        blueprint_info = _identity_info(blueprint)
        print(f"Selected Manifest Blueprint: DeviceClass={blueprint_info['device_class']}")
        complete, missing = _required_paths_exist(asset_data, blueprint)
        print(f"Blueprint files fully materialized: {complete}")
        if not complete:
            for item in missing:
                print(f"  Missing: {item}")
    else:
        print("CRITICAL: BuildManifest contains no valid CustomerInstall donor blueprints with raw path source items.")

    for message in _patch_info_plist(info_path, host_meta, apply):
        print(message)
    if update_bundle_info_path.exists():
        for message in _patch_asset_supported_models(update_bundle_info_path, host_meta, apply):
            print(message)
    if materialize_additional and blueprint:
        for message in _materialize_additional_manifests(asset_data, blueprint, apply):
            print(message)
    if materialize_bootcache_system_volume and blueprint:
        for message in _materialize_bootcache_system_volume(asset_data, blueprint, apply):
            print(message)
    if patch_msu:
        for message in _patch_msu_manifest(asset_data, manifest_path, apply, host_meta, materialize_additional):
            print(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch staged Tahoe installer structures dynamically mapped to host context.")
    parser.add_argument("paths", nargs="*", help="Volume, macOS Install Data, or staged target path. Defaults to /Volumes/*.")
    parser.add_argument("--apply", action="store_true", help="Write modifications down to source configuration plists.")
    parser.add_argument(
        "--diagnose-logs",
        action="store_true",
        dest="diagnose_logs",
        help="Scan visible installer logs for known Tahoe Stage-2 fatal indicators.",
    )
    parser.add_argument(
        "--patch-msu-manifest",
        action="store_true",
        help="Clone validated template components into active MSU layout sections.",
    )
    parser.add_argument(
        "--materialize-additional-manifests",
        action="store_true",
        help="Build missing root_hash and mtree entries declared within target blueprint configurations.",
    )
    parser.add_argument(
        "--materialize-bootcache-system-volume",
        action="store_true",
        help="Derive missing bootcaches SystemVolume requirements from source tracking manifest details.",
    )
    args = parser.parse_args()

    roots = _candidate_roots(args.paths)
    if not roots:
        print("No active macOS Install Data assets caught across system paths.")
        _diagnose_install_logs(args.paths)
        raise SystemExit(1)

    touched = False
    for root in roots:
        before = touched
        _inspect(
            root,
            args.apply,
            args.materialize_additional_manifests,
            args.materialize_bootcache_system_volume,
            args.patch_msu_manifest,
        )
        touched = before or (root / "UpdateBundle" / "AssetData" / "Info.plist").exists()

    if not touched:
        _diagnose_install_logs(args.paths)
        raise SystemExit("Target structural path sweeps yielded zero staged UpdateBundle configurations.")

    if args.diagnose_logs:
        _diagnose_install_logs(args.paths)

    if not args.apply:
        print("\nEvaluation complete. Run with --apply to commit modifications.")


if __name__ == "__main__":
    main()
