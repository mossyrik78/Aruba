import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from requests.exceptions import HTTPError


@dataclass
class ArubaCentralConfig:
    base_url: str
    client_id: str
    client_secret: str
    verify_ssl: bool = True


class ArubaCentralClient:
    def __init__(self, config: ArubaCentralConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.token: Optional[str] = None
        self.headers: Dict[str, str] = {}

    def authenticate(self) -> str:
        url = f"{self.base_url}/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }
        response = requests.post(url, data=payload, verify=self.config.verify_ssl, timeout=30)
        response.raise_for_status()
        body = response.json()
        self.token = body.get("access_token")
        if not self.token:
            raise RuntimeError(f"Authentication failed: {body}")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        return self.token

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        if not self.token:
            self.authenticate()

        url = f"{self.base_url}{path}"
        kwargs.setdefault("headers", self.headers)
        kwargs.setdefault("verify", self.config.verify_ssl)
        response = requests.request(method, url, timeout=60, **kwargs)
        response.raise_for_status()
        if response.text:
            try:
                return response.json()
            except ValueError:
                return {"text": response.text}
        return {}

    def get_device(self, serial: str) -> Dict[str, Any]:
        path = f"/monitoring/v1/devices/{serial}"
        return self._request("GET", path)

    def device_exists(self, serial: str) -> bool:
        try:
            self.get_device(serial)
            return True
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return False
            raise

    def list_devices(self, limit: int = 250, offset: int = 0) -> List[Dict[str, Any]]:
        path = f"/monitoring/v1/devices?limit={limit}&offset={offset}"
        result = self._request("GET", path)
        return result.get("devices") or result.get("data") or []

    def wipe_device(self, serial: str) -> Dict[str, Any]:
        path = "/configuration/v1/devices/action"
        payload = {
            "data": [
                {
                    "serial_number": serial,
                    "action": "factory_reset",
                }
            ]
        }
        return self._request("POST", path, json=payload)

    def claim_device(self, serial: str, mac_address: Optional[str] = None) -> Dict[str, Any]:
        path = "/configuration/v1/devices/claim"
        payload = {"data": [{"serial_number": serial}]}
        if mac_address:
            payload["data"][0]["mac_address"] = mac_address
        return self._request("POST", path, json=payload)

    def assign_template_to_device(self, serial: str, template_id: str) -> Dict[str, Any]:
        path = "/configuration/v1/devices/assign-template"
        payload = {
            "data": [
                {
                    "device_serial": serial,
                    "template_id": template_id,
                    "overwrite": True,
                }
            ]
        }
        return self._request("POST", path, json=payload)

    def assign_group_to_device(self, serial: str, group_id: str) -> Dict[str, Any]:
        path = "/configuration/v1/devices/assign-group"
        payload = {
            "data": [
                {
                    "device_serial": serial,
                    "group_id": group_id,
                    "overwrite": True,
                }
            ]
        }
        return self._request("POST", path, json=payload)

    def push_template_to_device(self, serial: str, template_id: str) -> Dict[str, Any]:
        path = "/configuration/v1/template/push"
        payload = {
            "data": [
                {
                    "template_id": template_id,
                    "devices": [serial],
                }
            ]
        }
        return self._request("POST", path, json=payload)

    def migrate_device(
        self,
        serial: str,
        template_id: str,
        wipe: bool = False,
        claim: bool = False,
        mac_address: Optional[str] = None,
        firmware_group_id: Optional[str] = None,
        ui_group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {"serial": serial, "actions": []}
        if claim and not self.device_exists(serial):
            result["actions"].append({"claim": self.claim_device(serial, mac_address)})
        if firmware_group_id:
            result["actions"].append({"assign_firmware_group": self.assign_group_to_device(serial, firmware_group_id)})
        if wipe:
            result["actions"].append({"wipe_request": self.wipe_device(serial)})
        result["actions"].append({"assign_template": self.assign_template_to_device(serial, template_id)})
        result["actions"].append({"push_template": self.push_template_to_device(serial, template_id)})
        if ui_group_id:
            result["actions"].append({"assign_ui_group": self.assign_group_to_device(serial, ui_group_id)})
        return result

    def validate_template(self, template_id: str) -> Dict[str, Any]:
        path = f"/configuration/v1/template/{template_id}"
        return self._request("GET", path)


def build_config(data: Dict[str, Any]) -> ArubaCentralConfig:
    central = data.get("central", {})

    base_url = os.getenv("ARUBA_CENTRAL_BASE_URL") or central.get("base_url")
    client_id = os.getenv("ARUBA_CENTRAL_CLIENT_ID") or central.get("client_id")
    client_secret = os.getenv("ARUBA_CENTRAL_CLIENT_SECRET") or central.get("client_secret")
    verify_ssl = central.get("verify_ssl", True)

    env_verify_ssl = os.getenv("ARUBA_CENTRAL_VERIFY_SSL")
    if env_verify_ssl is not None:
        verify_ssl = env_verify_ssl.lower() not in {"0", "false", "no", "off"}

    if base_url is None or client_id is None or client_secret is None:
        raise ValueError(
            "Central configuration must include base_url, client_id, and client_secret either in the plan file or via environment variables."
        )

    return ArubaCentralConfig(
        base_url=base_url,
        client_id=client_id,
        client_secret=client_secret,
        verify_ssl=verify_ssl,
    )


def dump_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)
