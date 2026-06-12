import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests as _requests
import typer
import yaml

from aruba_central import ArubaCentralClient, build_config, dump_json

app = typer.Typer(help="Migration of new and Brownfield sites via Aruba Central")


def _api_error(exc: Exception) -> None:
    if isinstance(exc, _requests.exceptions.ConnectionError):
        typer.echo("Connection error: cannot reach Aruba Central. Check base_url and network.", err=True)
    elif isinstance(exc, _requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else "?"
        body = exc.response.text[:300] if exc.response is not None else ""
        typer.echo(f"HTTP {status}: {body}", err=True)
    elif isinstance(exc, _requests.exceptions.RequestException):
        typer.echo(f"Request error: {exc}", err=True)
    else:
        typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config_file: Path = typer.Option(
        Path("migration_plan.yaml"),
        "--config",
        "-c",
        help="Path to the migration plan YAML file.",
    ),
):
    """Common options for Aruba Central migration commands."""
    ctx.obj = {"config_file": config_file}


def load_plan(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise typer.BadParameter(f"Plan file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_client(plan: Dict[str, Any]) -> ArubaCentralClient:
    config = build_config(plan)
    return ArubaCentralClient(config)


def resolve_site(device: Dict[str, Any], plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    site_name = device.get("site")
    if not site_name:
        return None

    return plan.get("sites", {}).get(site_name)


def resolve_template(device: Dict[str, Any], plan: Dict[str, Any]) -> Optional[str]:
    if device.get("template_id"):
        return device["template_id"]

    template_rules = plan.get("template_rules", {})
    if template_rules:
        model = device.get("model", "").lower()
        device_type = device.get("device_type", "").lower()
        for rule_key, template_id in template_rules.items():
            if rule_key.lower() in model or rule_key.lower() in device_type:
                return template_id

    site = resolve_site(device, plan)
    if site:
        return site.get("template_id")

    return plan.get("templates", {}).get("default_template_id")


def resolve_group(device: Dict[str, Any], plan: Dict[str, Any]) -> Optional[str]:
    if device.get("firmware_group_id"):
        return device["firmware_group_id"]

    group_rules = plan.get("firmware_group_rules", {})
    if group_rules:
        model = device.get("model", "").lower()
        device_type = device.get("device_type", "").lower()
        for rule_key, group_id in group_rules.items():
            if rule_key.lower() in model or rule_key.lower() in device_type:
                return group_id

    site = resolve_site(device, plan)
    if site:
        return site.get("firmware_group_id")

    return None


def resolve_ui_group(device: Dict[str, Any], plan: Dict[str, Any]) -> Optional[str]:
    if device.get("ui_group_id"):
        return device["ui_group_id"]

    ui_group_rules = plan.get("ui_group_rules", {})
    if ui_group_rules:
        model = device.get("model", "").lower()
        device_type = device.get("device_type", "").lower()
        for rule_key, group_id in ui_group_rules.items():
            if rule_key.lower() in model or rule_key.lower() in device_type:
                return group_id

    site = resolve_site(device, plan)
    if site:
        return site.get("ui_group_id")

    return None


def prepare_device_action(device: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    serial = device["serial"]
    action: Dict[str, Any] = {"serial": serial}
    action["template_id"] = resolve_template(device, plan)
    action["firmware_group_id"] = resolve_group(device, plan)
    action["ui_group_id"] = resolve_ui_group(device, plan)
    action["site"] = device.get("site")
    action["site_variables"] = resolve_site(device, plan) or {}
    action["wipe"] = bool(device.get("wipe", False))
    action["claim"] = bool(device.get("claim", False))
    action["mac_address"] = device.get("mac_address")
    return action


def append_device_to_plan(plan_file: Path, device_data: Dict[str, Any]) -> None:
    plan = load_plan(plan_file)
    devices = plan.setdefault("devices", [])
    if any(entry.get("serial") == device_data["serial"] for entry in devices):
        raise typer.BadParameter(f"Device with serial {device_data['serial']} already exists in the plan.")
    devices.append(device_data)
    plan["devices"] = devices
    with plan_file.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(plan, handle, sort_keys=False)


def remove_device_from_plan(plan_file: Path, serial: str) -> bool:
    plan = load_plan(plan_file)
    devices = plan.setdefault("devices", [])
    filtered_devices = [entry for entry in devices if entry.get("serial") != serial]
    if len(filtered_devices) == len(devices):
        return False
    plan["devices"] = filtered_devices
    with plan_file.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(plan, handle, sort_keys=False)
    return True


@app.command("add-device")
def add_device(
    ctx: typer.Context,
    serial: str,
    site: Optional[str] = typer.Option(None, "--site", "-s", help="Site name for the new device."),
    model: Optional[str] = typer.Option(None, "--model", help="Device model.", show_default=False),
    device_type: Optional[str] = typer.Option(None, "--type", help="Device type (switch/ap).", show_default=False),
    template_id: Optional[str] = typer.Option(None, "--template-id", help="Explicit template ID.", show_default=False),
    firmware_group_id: Optional[str] = typer.Option(None, "--firmware-group-id", help="Firmware upgrade group ID.", show_default=False),
    ui_group_id: Optional[str] = typer.Option(None, "--ui-group-id", help="UI group ID for post-onboarding.", show_default=False),
    wipe: bool = typer.Option(False, help="Whether to wipe the device before onboarding."),
    claim: bool = typer.Option(True, help="Whether to claim the device in Central."),
    mac_address: Optional[str] = typer.Option(None, "--mac", help="MAC address for the device when claiming.", show_default=False),
):
    """Add a new device entry to the migration plan."""
    plan_file = ctx.obj["config_file"]
    device_data: Dict[str, Any] = {
        "serial": serial,
        "site": site,
        "model": model,
        "device_type": device_type,
        "template_id": template_id,
        "firmware_group_id": firmware_group_id,
        "ui_group_id": ui_group_id,
        "wipe": wipe,
        "claim": claim,
        "mac_address": mac_address,
    }
    # Remove unset values to keep the plan clean.
    device_data = {k: v for k, v in device_data.items() if v is not None}
    append_device_to_plan(plan_file, device_data)
    typer.echo(f"Added device {serial} to plan {plan_file}")


@app.command("remove-device")
def remove_device(
    ctx: typer.Context,
    serial: str,
):
    """Remove a device entry from the migration plan by serial."""
    plan_file = ctx.obj["config_file"]
    removed = remove_device_from_plan(plan_file, serial)
    if not removed:
        raise typer.BadParameter(f"Device with serial {serial} not found in plan.")
    typer.echo(f"Removed device {serial} from plan {plan_file}")


@app.command("list-devices")
def list_devices(
    ctx: typer.Context,
):
    """Show all device entries in the migration plan."""
    plan = load_plan(ctx.obj["config_file"])
    devices = plan.get("devices", [])
    typer.echo(dump_json(devices))


@app.command("show-device")
def show_device(
    ctx: typer.Context,
    serial: str,
):
    """Show a single device entry from the migration plan by serial."""
    plan = load_plan(ctx.obj["config_file"])
    devices = plan.get("devices", [])
    for device in devices:
        if device.get("serial") == serial:
            typer.echo(dump_json(device))
            return
    raise typer.BadParameter(f"Device with serial {serial} not found in plan.")


def parse_site_setting(value: str) -> Any:
    if "=" not in value:
        raise ValueError("Site settings must be key=value")
    key, raw_value = value.split("=", 1)
    try:
        parsed = json.loads(raw_value)
    except ValueError:
        parsed = raw_value
    return key, parsed


def set_nested(data: Dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def remove_nested(data: Dict[str, Any], key: str) -> bool:
    parts = key.split(".")
    current = data
    for part in parts[:-1]:
        if not isinstance(current.get(part), dict):
            return False
        current = current[part]
    return current.pop(parts[-1], None) is not None


@app.command("site-vars")
def site_vars(
    ctx: typer.Context,
    site_name: str,
    set: Optional[List[str]] = typer.Option(None, "--set", "-s", help="Set site variable key=value", show_default=False),
    remove: Optional[List[str]] = typer.Option(None, "--remove", "-r", help="Remove site variable by key", show_default=False),
):
    """Show or update variables for a site."""
    plan_file = ctx.obj["config_file"]
    plan = load_plan(plan_file)
    sites = plan.setdefault("sites", {})
    site_data = sites.setdefault(site_name, {})

    if not set and not remove:
        typer.echo(dump_json(site_data))
        return

    for item in set or []:
        key, value = parse_site_setting(item)
        set_nested(site_data, key, value)

    for key in remove or []:
        removed = remove_nested(site_data, key)
        if not removed:
            typer.echo(f"Warning: variable '{key}' was not found in site '{site_name}'")

    sites[site_name] = site_data
    plan["sites"] = sites
    with plan_file.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(plan, handle, sort_keys=False)

    typer.echo(f"Updated site variables for '{site_name}'")


@app.command()
def inventory(
    ctx: typer.Context,
    limit: int = typer.Option(250, help="Maximum inventory records to retrieve."),
):
    """List devices currently known to Aruba Central."""
    plan = load_plan(ctx.obj["config_file"])
    client = load_client(plan)
    try:
        devices = client.list_devices(limit=limit)
    except Exception as exc:
        _api_error(exc)
    typer.echo(dump_json(devices))


@app.command("plan-from-inventory")
def plan_from_inventory(
    ctx: typer.Context,
    output: Path = typer.Argument(Path("migration_plan.generated.yaml")),
    limit: int = typer.Option(250, help="Maximum inventory records to include."),
):
    """Generate a migration plan from Aruba Central inventory using template rules."""
    plan = load_plan(ctx.obj["config_file"])
    client = load_client(plan)
    try:
        inventory = client.list_devices(limit=limit)
    except Exception as exc:
        _api_error(exc)

    devices: List[Dict[str, Any]] = []
    for item in inventory:
        serial = item.get("serial_number") or item.get("serial") or item.get("device_serial")
        if not serial:
            continue
        device = {
            "serial": serial,
            "model": item.get("model"),
            "device_type": item.get("device_type") or item.get("type"),
            "template_id": resolve_template(item, plan),
            "firmware_group_id": resolve_group(item, plan),
            "ui_group_id": resolve_ui_group(item, plan),
            "wipe": False,
            "claim": False,
        }
        devices.append(device)

    output_plan = {
        "central": plan["central"],
        "templates": plan.get("templates", {}),
        "template_rules": plan.get("template_rules", {}),
        "firmware_group_rules": plan.get("firmware_group_rules", {}),
        "ui_group_rules": plan.get("ui_group_rules", {}),
        "devices": devices,
    }

    with output.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(output_plan, handle)

    typer.echo(f"Generated migration plan: {output}")


@app.command("auto-migrate")
def auto_migrate(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, help="Print actions but do not execute them."),
):
    """Automatically claim, wipe, and assign templates for new and brownfield devices."""
    plan = load_plan(ctx.obj["config_file"])
    client = load_client(plan)

    devices: List[Dict[str, Any]] = plan.get("devices", [])
    if not devices:
        raise typer.BadParameter("No devices found in the plan file.")

    results: List[Dict[str, Any]] = []
    for device in devices:
        serial = device["serial"]
        target_template = resolve_template(device, plan)
        if not target_template:
            raise typer.BadParameter(f"Missing template resolution for device {serial}")

        action = prepare_device_action(device, plan)
        typer.echo(
            f"Processing {serial}: claim={action['claim']}, wipe={action['wipe']}, template={target_template}"
        )
        if dry_run:
            dry = {k: v for k, v in {**action, "target_template": target_template}.items() if v is not None}
            results.append(dry)
            continue

        try:
            result = client.migrate_device(
                serial,
                target_template,
                wipe=action["wipe"],
                claim=action["claim"],
                mac_address=action["mac_address"],
                firmware_group_id=action["firmware_group_id"],
                ui_group_id=action["ui_group_id"],
            )
        except Exception as exc:
            _api_error(exc)
        results.append(result)

    typer.echo(dump_json(results))


@app.command()
def validate(
    ctx: typer.Context,
):
    """Validate migration plan devices and template references."""
    plan = load_plan(ctx.obj["config_file"])
    client = load_client(plan)

    results: Dict[str, Any] = {"devices": []}
    for device in plan.get("devices", []):
        serial = device["serial"]
        target_template = resolve_template(device, plan)
        if not target_template:
            results["devices"].append({"serial": serial, "error": "no template_id or match rule"})
            continue

        try:
            validation = client.validate_template(target_template)
        except Exception as exc:
            _api_error(exc)
        results["devices"].append({"serial": serial, "template": target_template, "template_validation": validation})

    typer.echo(dump_json(results))


@app.command()
def migrate(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, help="Print actions but do not execute them."),
):
    """Migrate all devices in the plan (alias for auto-migrate with dry-run support)."""
    plan = load_plan(ctx.obj["config_file"])
    client = load_client(plan)

    devices: List[Dict[str, Any]] = plan.get("devices", [])
    if not devices:
        raise typer.BadParameter("No devices found in the plan file.")

    results: List[Dict[str, Any]] = []
    for device in devices:
        serial = device["serial"]
        target_template = resolve_template(device, plan)
        if not target_template:
            raise typer.BadParameter(f"Missing template resolution for device {serial}")

        action = prepare_device_action(device, plan)
        typer.echo(f"Processing {serial}: claim={action['claim']}, wipe={action['wipe']}, template={target_template}")

        if dry_run:
            dry = {k: v for k, v in {**action, "target_template": target_template}.items() if v is not None}
            results.append(dry)
            continue

        try:
            result = client.migrate_device(
                serial,
                target_template,
                wipe=action["wipe"],
                claim=action["claim"],
                mac_address=action["mac_address"],
                firmware_group_id=action["firmware_group_id"],
                ui_group_id=action["ui_group_id"],
            )
        except Exception as exc:
            _api_error(exc)
        results.append(result)

    typer.echo(dump_json(results))


@app.command()
def status(
    ctx: typer.Context,
    serial: str,
):
    """Show the current status of a device in Aruba Central."""
    plan = load_plan(ctx.obj["config_file"])
    client = load_client(plan)
    try:
        device = client.get_device(serial)
    except Exception as exc:
        _api_error(exc)
    typer.echo(dump_json(device))


@app.command()
def wipe(
    ctx: typer.Context,
    serial: str,
):
    """Factory-reset a device in Aruba Central."""
    plan = load_plan(ctx.obj["config_file"])
    client = load_client(plan)
    try:
        result = client.wipe_device(serial)
    except Exception as exc:
        _api_error(exc)
    typer.echo(dump_json(result))


@app.command("assign-template")
def assign_template(
    ctx: typer.Context,
    serial: str,
    template_id: str,
):
    """Assign a template to a device in Aruba Central."""
    plan = load_plan(ctx.obj["config_file"])
    client = load_client(plan)
    try:
        result = client.assign_template_to_device(serial, template_id)
    except Exception as exc:
        _api_error(exc)
    typer.echo(dump_json(result))


@app.command("assign-firmware-group")
def assign_firmware_group(
    ctx: typer.Context,
    serial: str,
    group_id: str,
):
    """Assign a firmware upgrade group to a device in Aruba Central."""
    plan = load_plan(ctx.obj["config_file"])
    client = load_client(plan)
    try:
        result = client.assign_group_to_device(serial, group_id)
    except Exception as exc:
        _api_error(exc)
    typer.echo(dump_json(result))


@app.command("assign-ui-group")
def assign_ui_group(
    ctx: typer.Context,
    serial: str,
    group_id: str,
):
    """Assign a UI group to a device in Aruba Central."""
    plan = load_plan(ctx.obj["config_file"])
    client = load_client(plan)
    try:
        result = client.assign_group_to_device(serial, group_id)
    except Exception as exc:
        _api_error(exc)
    typer.echo(dump_json(result))


if __name__ == "__main__":
    app()
