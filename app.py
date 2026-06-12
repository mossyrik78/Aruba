"""Flask web application for Aruba Central device management."""
import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from flask import Flask, jsonify, render_template, request

from aruba_central import ArubaCentralClient, ArubaCentralConfig, build_config
from migrate_switches import (
    append_device_to_plan,
    load_client,
    load_plan,
    prepare_device_action,
    remove_device_from_plan,
    resolve_group,
    resolve_template,
    resolve_ui_group,
)

app = Flask(__name__)

# Configuration
CONFIG_FILE = Path("migration_plan.yaml")


def get_config() -> Dict[str, Any]:
    """Load configuration from YAML file."""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def get_client() -> ArubaCentralClient:
    """Get authenticated Aruba Central client."""
    config = get_config()
    return load_client(config)


@app.route("/")
def index():
    """Serve the main UI page."""
    return render_template("index.html")


@app.route("/api/devices", methods=["GET"])
def api_list_devices():
    """Get all devices from the migration plan."""
    try:
        plan = load_plan(CONFIG_FILE)
        devices = plan.get("devices", [])
        return jsonify({"success": True, "devices": devices})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/devices", methods=["POST"])
def api_add_device():
    """Add a new device to the migration plan."""
    try:
        data = request.json
        serial = data.get("serial", "").strip()

        if not serial:
            return jsonify({"success": False, "error": "Serial number is required"}), 400

        device_data = {
            "serial": serial,
            "site": data.get("site"),
            "model": data.get("model"),
            "device_type": data.get("device_type"),
            "template_id": data.get("template_id"),
            "firmware_group_id": data.get("firmware_group_id"),
            "ui_group_id": data.get("ui_group_id"),
            "wipe": bool(data.get("wipe", False)),
            "claim": bool(data.get("claim", True)),
            "mac_address": data.get("mac_address"),
        }

        # Remove unset values
        device_data = {k: v for k, v in device_data.items() if v is not None and v != ""}

        append_device_to_plan(CONFIG_FILE, device_data)
        return jsonify({"success": True, "message": f"Device {serial} added successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/devices/<serial>", methods=["DELETE"])
def api_remove_device(serial: str):
    """Remove a device from the migration plan."""
    try:
        removed = remove_device_from_plan(CONFIG_FILE, serial)
        if not removed:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Device with serial {serial} not found",
                    }
                ),
                404,
            )
        return jsonify({"success": True, "message": f"Device {serial} removed successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/migrate/<serial>", methods=["POST"])
def api_migrate_device(serial: str):
    """Migrate a single device."""
    try:
        plan = load_plan(CONFIG_FILE)
        devices = plan.get("devices", [])

        # Find the device
        device = None
        for d in devices:
            if d.get("serial") == serial:
                device = d
                break

        if not device:
            return jsonify({"success": False, "error": f"Device {serial} not found"}), 404

        # Prepare device action
        action = prepare_device_action(device, plan)

        # Get client and migrate
        client = get_client()
        result = client.migrate_device(
            serial=action["serial"],
            template_id=action["template_id"],
            wipe=action["wipe"],
            claim=action["claim"],
            mac_address=action["mac_address"],
            firmware_group_id=action["firmware_group_id"],
            ui_group_id=action["ui_group_id"],
        )

        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/migrate", methods=["POST"])
def api_migrate_all():
    """Migrate all devices in the plan."""
    try:
        plan = load_plan(CONFIG_FILE)
        devices = plan.get("devices", [])

        if not devices:
            return jsonify({"success": False, "error": "No devices to migrate"}), 400

        client = get_client()
        results = []

        for device in devices:
            try:
                action = prepare_device_action(device, plan)
                result = client.migrate_device(
                    serial=action["serial"],
                    template_id=action["template_id"],
                    wipe=action["wipe"],
                    claim=action["claim"],
                    mac_address=action["mac_address"],
                    firmware_group_id=action["firmware_group_id"],
                    ui_group_id=action["ui_group_id"],
                )
                results.append({"serial": action["serial"], "success": True, "result": result})
            except Exception as e:
                results.append({"serial": device.get("serial"), "success": False, "error": str(e)})

        return jsonify({"success": True, "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/inventory", methods=["GET"])
def api_inventory():
    """Get current device inventory from Aruba Central."""
    try:
        client = get_client()
        devices = client.list_devices(limit=250)
        return jsonify({"success": True, "devices": devices})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/config", methods=["GET"])
def api_config():
    """Get configuration info (without secrets)."""
    try:
        plan = load_plan(CONFIG_FILE)
        config = {
            "templates": plan.get("templates", {}),
            "template_rules": plan.get("template_rules", {}),
            "firmware_group_rules": plan.get("firmware_group_rules", {}),
            "ui_group_rules": plan.get("ui_group_rules", {}),
            "sites": list(plan.get("sites", {}).keys()),
        }
        return jsonify({"success": True, "config": config})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/config/full", methods=["GET"])
def api_config_full():
    """Get full configuration including connection settings (client_secret omitted)."""
    try:
        plan = load_plan(CONFIG_FILE)
        central = dict(plan.get("central", {}))
        secret_set = bool(central.pop("client_secret", None))
        config = {
            "central": {**central, "client_secret_set": secret_set},
            "templates": plan.get("templates", {}),
            "template_rules": plan.get("template_rules", {}),
            "firmware_group_rules": plan.get("firmware_group_rules", {}),
            "ui_group_rules": plan.get("ui_group_rules", {}),
        }
        return jsonify({"success": True, "config": config})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/config", methods=["PUT"])
def api_update_config():
    """Update configuration sections in the migration plan YAML."""
    try:
        data = request.json
        plan = load_plan(CONFIG_FILE)

        if "central" in data:
            existing = plan.setdefault("central", {})
            for key, value in data["central"].items():
                if value is not None and value != "":
                    existing[key] = value

        if "templates" in data:
            tmpl = plan.setdefault("templates", {})
            for key, value in data["templates"].items():
                if value:
                    tmpl[key] = value
                else:
                    tmpl.pop(key, None)

        for section in ("template_rules", "firmware_group_rules", "ui_group_rules"):
            if section in data:
                plan[section] = data[section]

        with CONFIG_FILE.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(plan, handle, sort_keys=False)

        return jsonify({"success": True, "message": "Configuration updated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/import-inventory", methods=["POST"])
def api_import_inventory():
    """Import all devices from Aruba Central inventory into the migration plan."""
    try:
        plan = load_plan(CONFIG_FILE)
        client = get_client()
        
        # Get all devices from inventory
        inventory_devices = client.list_devices(limit=500)
        
        if not inventory_devices:
            return jsonify({"success": False, "error": "No devices found in inventory"}), 400
        
        # Get existing devices to avoid duplicates
        existing_devices = plan.get("devices", [])
        existing_serials = {d.get("serial") for d in existing_devices}
        
        # Add devices from inventory that don't already exist in plan
        added_count = 0
        skipped_count = 0
        
        for inv_device in inventory_devices:
            serial = inv_device.get("serial_number") or inv_device.get("serial")
            
            if not serial:
                continue
            
            if serial in existing_serials:
                skipped_count += 1
                continue
            
            # Create device entry with available information
            device_data = {
                "serial": serial,
                "model": inv_device.get("model_type"),
                "device_type": inv_device.get("device_type"),
                "claim": True,
                "wipe": False,
            }
            
            # Remove unset values
            device_data = {k: v for k, v in device_data.items() if v is not None and v != ""}
            
            try:
                append_device_to_plan(CONFIG_FILE, device_data)
                added_count += 1
                existing_serials.add(serial)
            except Exception as e:
                # Continue even if one device fails
                continue
        
        return jsonify({
            "success": True,
            "message": f"Imported {added_count} devices, {skipped_count} already in plan",
            "added": added_count,
            "skipped": skipped_count
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/import-csv", methods=["POST"])
def api_import_csv():
    """Import devices from a CSV file."""
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file provided"}), 400
        
        file = request.files["file"]
        
        if file.filename == "":
            return jsonify({"success": False, "error": "No file selected"}), 400
        
        if not file.filename.endswith(".csv"):
            return jsonify({"success": False, "error": "File must be a CSV file"}), 400
        
        # Read and parse CSV
        stream = StringIO(file.stream.read().decode("UTF-8"), newline=None)
        csv_reader = csv.DictReader(stream)
        
        if not csv_reader.fieldnames:
            return jsonify({"success": False, "error": "CSV file is empty"}), 400
        
        # Check for required columns (case-insensitive)
        fieldnames_lower = [f.lower().strip() for f in csv_reader.fieldnames]
        has_serial = "serial" in fieldnames_lower or "serial_number" in fieldnames_lower or "device_serial" in fieldnames_lower
        
        if not has_serial:
            return jsonify({
                "success": False,
                "error": "CSV must contain a 'serial' or 'serial_number' column"
            }), 400
        
        # Get mapping of lowercase fieldnames to actual fieldnames
        fieldname_map = {f.lower().strip(): f for f in csv_reader.fieldnames}
        serial_column = fieldname_map.get("serial") or fieldname_map.get("serial_number") or fieldname_map.get("device_serial")
        mac_column = fieldname_map.get("mac") or fieldname_map.get("mac_address")
        model_column = fieldname_map.get("model")
        type_column = fieldname_map.get("type") or fieldname_map.get("device_type")
        site_column = fieldname_map.get("site")
        
        plan = load_plan(CONFIG_FILE)
        existing_devices = plan.get("devices", [])
        existing_serials = {d.get("serial") for d in existing_devices}
        
        added_count = 0
        skipped_count = 0
        errors = []
        
        for row_idx, row in enumerate(csv_reader, start=2):  # Start at 2 because row 1 is headers
            serial = row.get(serial_column, "").strip() if serial_column else ""
            
            if not serial:
                errors.append(f"Row {row_idx}: Missing serial number")
                continue
            
            if serial in existing_serials:
                skipped_count += 1
                continue
            
            device_data = {
                "serial": serial,
                "claim": True,
                "wipe": False,
            }
            
            # Add optional fields if they exist
            if mac_column and row.get(mac_column, "").strip():
                device_data["mac_address"] = row.get(mac_column, "").strip()
            
            if model_column and row.get(model_column, "").strip():
                device_data["model"] = row.get(model_column, "").strip()
            
            if type_column and row.get(type_column, "").strip():
                device_data["device_type"] = row.get(type_column, "").strip()
            
            if site_column and row.get(site_column, "").strip():
                device_data["site"] = row.get(site_column, "").strip()
            
            try:
                append_device_to_plan(CONFIG_FILE, device_data)
                added_count += 1
                existing_serials.add(serial)
            except Exception as e:
                errors.append(f"Row {row_idx}: {str(e)}")
                continue
        
        result = {
            "success": True,
            "added": added_count,
            "skipped": skipped_count,
            "errors": errors,
            "message": f"Imported {added_count} devices, {skipped_count} already in plan"
        }
        
        if errors:
            result["message"] += f", {len(errors)} errors"
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sites", methods=["GET"])
def api_sites():
    """Get all sites and their variables from the migration plan."""
    try:
        plan = load_plan(CONFIG_FILE)
        sites = plan.get("sites", {})
        return jsonify({"success": True, "sites": sites, "count": len(sites)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/import-sites-excel", methods=["POST"])
def api_import_sites_excel():
    """Import site subnet definitions from an Excel (.xlsx) file."""
    try:
        import openpyxl
    except ImportError:
        return jsonify({"success": False, "error": "openpyxl is not installed. Run: pip install openpyxl"}), 500

    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file provided"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "error": "No file selected"}), 400

        if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
            return jsonify({"success": False, "error": "File must be an Excel file (.xlsx)"}), 400

        try:
            wb = openpyxl.load_workbook(file.stream, read_only=True, data_only=True)
        except Exception as exc:
            return jsonify({"success": False, "error": f"Could not read Excel file: {exc}"}), 400

        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        if not rows:
            return jsonify({"success": False, "error": "Excel file is empty"}), 400

        raw_headers = rows[0]
        headers = [str(h).lower().strip() if h is not None else "" for h in raw_headers]

        site_col = next(
            (headers.index(n) for n in ("site", "site_name", "location", "site name") if n in headers),
            None,
        )
        if site_col is None:
            return jsonify({"success": False, "error": "Excel must contain a 'site' or 'site_name' column"}), 400

        subnet_col = next(
            (headers.index(n) for n in ("subnet", "network", "cidr", "ip_network", "ip network") if n in headers),
            None,
        )

        imported: Dict[str, Any] = {}
        errors: list = []

        for row_idx, row in enumerate(rows[1:], start=2):
            if all(v is None for v in row):
                continue

            raw_site = row[site_col]
            if raw_site is None or str(raw_site).strip() == "":
                errors.append(f"Row {row_idx}: missing site name — skipped")
                continue

            site_name = str(raw_site).strip()
            site_data = imported.setdefault(site_name, {})

            if subnet_col is not None and row[subnet_col] is not None:
                subnet_val = str(row[subnet_col]).strip()
                if subnet_val:
                    entry: Dict[str, Any] = {"subnet": subnet_val}
                    for i, hdr in enumerate(headers):
                        if i in (site_col, subnet_col) or not hdr:
                            continue
                        val = row[i]
                        if val is not None and str(val).strip():
                            entry[hdr] = int(val) if isinstance(val, float) and val == int(val) else val
                    site_data.setdefault("subnets", []).append(entry)
            else:
                for i, hdr in enumerate(headers):
                    if i == site_col or not hdr:
                        continue
                    val = row[i]
                    if val is not None and str(val).strip():
                        site_data[hdr] = int(val) if isinstance(val, float) and val == int(val) else val

        if not imported:
            return jsonify({"success": False, "error": "No valid site data found in Excel"}), 400

        plan = load_plan(CONFIG_FILE)
        existing = plan.setdefault("sites", {})
        added = updated = 0

        for name, data in imported.items():
            if name in existing:
                if "subnets" in data:
                    cur_subnets = existing[name].setdefault("subnets", [])
                    cur_keys = {s.get("subnet") if isinstance(s, dict) else s for s in cur_subnets}
                    for entry in data["subnets"]:
                        key = entry.get("subnet") if isinstance(entry, dict) else entry
                        if key not in cur_keys:
                            cur_subnets.append(entry)
                for k, v in data.items():
                    if k != "subnets":
                        existing[name][k] = v
                updated += 1
            else:
                existing[name] = data
                added += 1

        plan["sites"] = existing
        with CONFIG_FILE.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(plan, handle, sort_keys=False)

        msg = f"Imported {added} new site{'s' if added != 1 else ''}, updated {updated} existing"
        if errors:
            msg += f", {len(errors)} row{'s' if len(errors) != 1 else ''} skipped"

        return jsonify({
            "success": True,
            "added": added,
            "updated": updated,
            "sites_imported": list(imported.keys()),
            "errors": errors,
            "message": msg,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
