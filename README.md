# Aruba Central Switch Migration

A lightweight Aruba Central automation scaffold for wiping existing switches and migrating them to new templates.

## What this does

- Authenticates to Aruba Central NBI
- Reads a migration plan from YAML
- Optionally wipes switches
- Assigns switches to a target template
- Pushes template configuration to devices

## Setup

1. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2. Create a plan file from `migration_plan.example.yaml`.

3. Add new devices with the CLI or by editing the plan file directly.

```bash
python migrate_switches.py --config migration_plan.yaml add-device B8BB12345678 \
  --site SiteA \
  --model "Aruba 6100" \
  --type switch \
  --template-id SWITCH_TEMPLATE_ID \
  --firmware-group-id SWITCH_FIRMWARE_GROUP_ID \
  --ui-group-id SWITCH_UI_GROUP_ID \
  --mac 00:11:22:33:44:55
```
Remove a device:
```bash
python migrate_switches.py --config migration_plan.yaml remove-device B8BB12345678
```
4. Run migrations:

```bash
python migrate_switches.py --config migration_plan.yaml auto-migrate
```

## Configuration

The plan file includes Aruba Central credentials, template IDs, template selection rules, and devices:

```yaml
central:
  base_url: https://portal2.central-eu.arubanetworks.com
  client_id: YOUR_CLIENT_ID
  client_secret: YOUR_CLIENT_SECRET
  verify_ssl: true

Environment overrides:
  ARUBA_CENTRAL_BASE_URL
  ARUBA_CENTRAL_CLIENT_ID
  ARUBA_CENTRAL_CLIENT_SECRET
  ARUBA_CENTRAL_VERIFY_SSL

Note: Set `ARUBA_CENTRAL_VERIFY_SSL=false` to disable TLS certificate verification for troubleshooting in lab environments. Do not use this in production unless necessary.

templates:
  default_template_id: DEFAULT_TEMPLATE_ID

template_rules:
  "Aruba 6100": SWITCH_TEMPLATE_ID
  "AP": AP_TEMPLATE_ID

firmware_group_rules:
  "Aruba 6100": SWITCH_FIRMWARE_GROUP_ID
  "AP": AP_FIRMWARE_GROUP_ID

ui_group_rules:
  "Aruba 6100": SWITCH_UI_GROUP_ID
  "AP": AP_UI_GROUP_ID

sites:
  SiteA:
    default_template_id: SITE_A_TEMPLATE_ID
    firmware_group_id: SITE_A_FIRMWARE_GROUP_ID
    ui_group_id: SITE_A_UI_GROUP_ID
    custom_setting: example

devices:
  - serial: B8BB12345678
    site: SiteA
    template_id: SWITCH_TEMPLATE_ID
    firmware_group_id: SWITCH_FIRMWARE_GROUP_ID
    ui_group_id: SWITCH_UI_GROUP_ID
    wipe: true
    claim: true
    mac_address: 00:11:22:33:44:55
  - serial: B8BB23456789
    site: SiteA
    device_type: access_point
    model: Aruba AP-515
    template_id: AP_TEMPLATE_ID
    firmware_group_id: AP_FIRMWARE_GROUP_ID
    ui_group_id: AP_UI_GROUP_ID
    wipe: false
    claim: true
```
## Commands

- `python migrate_switches.py --config migration_plan.yaml inventory` — list Aruba Central devices in inventory using a specific plan file
- `python migrate_switches.py --config migration_plan.yaml plan-from-inventory [output]` — generate a plan from inventory and template rules
- `python migrate_switches.py --config migration_plan.yaml auto-migrate` — automatically claim, wipe, assign firmware/UI groups, and assign templates for new and brownfield devices
- `python migrate_switches.py --config migration_plan.yaml migrate` — run the migration plan actions
- `python migrate_switches.py --config migration_plan.yaml status <serial>` — query a device status
- `python migrate_switches.py --config migration_plan.yaml wipe <serial>` — perform a factory reset on a device
- `python migrate_switches.py --config migration_plan.yaml assign-template <serial> <template_id>` — assign a template to a device
- `python migrate_switches.py --config migration_plan.yaml assign-firmware-group <serial> <group_id>` — assign a device to a firmware upgrade group
- `python migrate_switches.py --config migration_plan.yaml assign-ui-group <serial> <group_id>` — assign a device to a post-onboarding UI group
- `python migrate_switches.py --config migration_plan.yaml site-vars <site-name>` — show or update variables for a site
- `python migrate_switches.py --config migration_plan.yaml list-devices` — list devices currently in the plan
- `python migrate_switches.py --config migration_plan.yaml show-device <serial>` — show a specific device entry in the plan
- `python migrate_switches.py --config migration_plan.yaml validate` — validate the plan and template references

## Notes

- Aruba Central endpoint paths may vary by API version. Update `aruba_central.py` if your environment uses different URI routes.
- This scaffold prioritizes validation and safe operations.
