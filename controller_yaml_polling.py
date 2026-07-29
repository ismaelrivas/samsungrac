# pylint: disable=import-outside-toplevel,line-too-long,protected-access,too-many-branches,too-many-instance-attributes,too-many-lines,too-many-locals,too-many-nested-blocks,too-many-statements
"""State management and polling for YAML-configured climate controllers."""

import asyncio
import copy
import logging
import time
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_FAN_MODE,
    ATTR_SWING_MODE,
    ATTR_PRESET_MODE,
    ClimateEntityFeature,
)
from homeassistant.const import (
    ATTR_NAME,
    ATTR_TEMPERATURE,
    STATE_UNKNOWN,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from requests.exceptions import RequestException  # type: ignore[import-untyped]

from .const import (
    CONF_DEVICE_TYPE,
    CONFIG_DEVICE,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
)
from .exceptions import AuthError, CannotConnect, InvalidHeaderError
from .helpers import async_check_network_reachability, get_value_by_path
from .state import ClimateIPDeviceState

_LOGGER = logging.getLogger(__name__)


class YamlStatePoller:
    """Class responsible for polling the device and managing state."""

    def __init__(self, controller: Any) -> None:
        """Initialize the poller with a reference to the main controller facade."""
        self.controller = controller

        self._cached_device_state: dict[str, Any] | None = None
        self._last_state_fetch_time: float = 0.0
        self._last_device_state: dict[str, Any] | None = None
        self._consecutive_connection_errors: int = 0
        
        # 💥 ESTADO PURO AISLADO: Guarda la verdad de la red sin envenenamientos de UI
        self._pure_network_state: dict[str, Any] = {}
        
        # Shield Engine (Optimistic Locks)
        self._pending_updates: dict[str, tuple[Any, float]] = {}
        self._prop_template_key_cache: dict[str, str | None] = {}

        self.fan_modes_list_changed_pending_flicker: bool = False

    def register_pending_update(self, property_id: str, value: Any) -> None:
        """Register a pending update to shield the UI from stale network polling echoes."""
        self._pending_updates[property_id] = (value, time.time())

    async def _refresh_smartthings_token(self) -> str | None:
        """Attempt to refresh an expired SmartThings token using the official HA integration."""
        try:
            if not getattr(self.controller, "hass", None):
                return None

            entries = self.controller.hass.config_entries.async_entries("smartthings")
            if not entries:
                _LOGGER.debug(  # pragma: no mutate
                    "%s [Auth] No Official SmartThings config entries found.",
                    self.controller.log_prefix,
                )
                return None

            entry = entries[0]
            implementation = (
                await config_entry_oauth2_flow.async_get_config_entry_implementation(
                    self.controller.hass, entry
                )
            )
            session = config_entry_oauth2_flow.OAuth2Session(
                self.controller.hass, entry, implementation
            )

            await session.async_ensure_token_valid()
            token: str | None = session.token.get("access_token")
            masked = (
                f"***{token[-6:]}" if token and len(token) > 6 else "None"
            )  # pragma: no mutate
            _LOGGER.debug(  # pragma: no mutate
                "%s [Auth] OAuth2 session token validated. Token: %s",
                self.controller.log_prefix,
                masked,
            )
            return token
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(  # pragma: no mutate
                "%s [Auth] Error refreshing SmartThings token via OAuth2: %s",
                self.controller.log_prefix,
                e,
            )
            return None

    def _all_props(self) -> list[Any]:
        """Return all loaded properties (state getter + operations + sensors)."""
        loader = self.controller.loader
        return (
            ([loader.state_getter] if loader.state_getter else [])
            + list(loader.operations.values())
            + list(loader.sensors.values())
        )

    def _try_create_repair_issue(self) -> None:
        """Create a HA repair issue for persistent device offline state."""
        if not self.controller.hass:
            return
        try:
            raw_id = (
                self.controller.unique_id
                or self.controller.host
                or self.controller.ip_address
                or "unknown"
            )
            safe_device_id = str(raw_id).replace(".", "_").replace(" ", "_")

            config_name = self.controller.config.get("name")

            hardware_id = (
                self.controller.unique_id
                or self.controller.host
                or self.controller.ip_address
                or "Unknown"
            )

            device_name = config_name if config_name else f"Samsung AC {hardware_id}"
            async_create_issue(
                self.controller.hass,
                "climate_ip",
                f"device_offline_{safe_device_id}",
                is_fixable=False,
                is_persistent=False,
                severity=IssueSeverity.WARNING,
                translation_key="connection_failed",
                translation_placeholders={
                    "name": "device_name",
                    "device_name": device_name,
                    "host": self.controller.ip_address or self.controller.host or "Unknown",
                    "ip_address": self.controller.ip_address or self.controller.host or "Unknown",
                },
            )
            _LOGGER.info(
                "%s Created repair issue 'device_offline_%s' for %s (%s)",
                self.controller.log_prefix,
                safe_device_id,
                self.controller.name or "Climate IP",
                self.controller.ip_address or self.controller.host or "Unknown",
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            pass

    def _update_all_connections_token(self, new_token: str) -> None:
        """Propagate the new token to all active connection engines."""
        updated_connections: set = set()
        for prop in self._all_props():
            if (
                prop
                and (conn := prop.get_connection(None))
                and conn not in updated_connections
            ):
                if hasattr(conn, "update_auth_token"):
                    conn.update_auth_token(new_token)
                    updated_connections.add(conn)

    async def async_get_status(self) -> dict[str, Any] | None:
        """Fetch status prioritizing memory state to shield from polling flicker."""
        now_ts = time.time()
        if self._cached_device_state and (now_ts - self._last_state_fetch_time < 2.0):
            st_getter = self.controller.loader.state_getter
            if st_getter and st_getter.value:
                # Retornamos la RAM envenenada con los candados para clavar la UI sin flicker
                return copy.deepcopy(st_getter.value)
            return self._cached_device_state.copy()

        device_state = await self.async_update_state()
        return copy.deepcopy(device_state) if device_state else None

    async def async_update_state(self) -> dict[str, Any] | None:
        """Fetch the actual state from the device over the network."""
        if not self.controller.loader.state_getter:
            raise UpdateFailed("State getter is not initialized, cannot update state.")

        if self.controller.config.get(
            CONF_DEVICE_TYPE
        ) != DEVICE_TYPE_SAMSUNG_2878 and getattr(self.controller, "ip_address", None):
            try:
                network_reachable = await async_check_network_reachability(
                    self.controller.ip_address, self.controller.log_prefix
                )
                if not network_reachable:
                    self._consecutive_connection_errors += 1
                    if self._consecutive_connection_errors == 3:
                        self._try_create_repair_issue()
                    if self._consecutive_connection_errors >= 2:
                        raise CannotConnect(
                            "Host unreachable (ICMP ping failed). Device is persistently offline."
                        )
                    raise CannotConnect("Host unreachable (ICMP ping failed).")
            except Exception as diag_err:  # pylint: disable=broad-exception-caught
                if isinstance(diag_err, CannotConnect):
                    raise

        try:
            full_device_state = (
                await self.controller.loader.state_getter.async_update_state(
                    None, getattr(self.controller, "debug", False)
                )
            )

            if self._consecutive_connection_errors > 0:
                self._consecutive_connection_errors = 0
                if getattr(self.controller, "hass", None):
                    try:
                        raw_id = (
                            self.controller.unique_id
                            or self.controller.host
                            or self.controller.ip_address
                            or "unknown"
                        )
                        safe_device_id = str(raw_id).replace(".", "_").replace(" ", "_")
                        async_delete_issue(
                            self.controller.hass,
                            "climate_ip",
                            f"device_offline_{safe_device_id}",
                        )
                    except Exception:
                        pass

        except AuthError as exc:
            new_token = await self._refresh_smartthings_token()
            if new_token and new_token != self.controller.token:
                if hasattr(self.controller, "token"):
                    self.controller.token = new_token
                self._update_all_connections_token(new_token)

                if hasattr(self.controller, "on_token_refreshed") and self.controller.on_token_refreshed:
                    self.controller.on_token_refreshed(new_token)

                try:
                    full_device_state = (
                        await self.controller.loader.state_getter.async_update_state(
                            None, self.controller.debug
                        )
                    )
                    self._consecutive_connection_errors = 0
                except Exception as retry_exc:
                    raise UpdateFailed(f"Retry after token refresh failed: {retry_exc}") from retry_exc
            else:
                raise ConfigEntryAuthFailed("Authentication failed. Please check tokens.") from exc

        except InvalidHeaderError:
            raise

        except (RequestException, CannotConnect) as e:
            if "persistently offline" in str(e):
                self._consecutive_connection_errors = 2
            else:
                self._consecutive_connection_errors += 1

            if (
                getattr(self.controller, "available", True)
                and self._consecutive_connection_errors <= 2
                and self._cached_device_state is not None
            ):
                return self._cached_device_state

            if self._consecutive_connection_errors == 3:
                self._try_create_repair_issue()

            reason = str(e).split(":")[-1].strip()
            raise UpdateFailed(f"Device unreachable: {reason}") from e

        if full_device_state is None:
            if getattr(self.controller, "available", True) and self._cached_device_state:
                return self._cached_device_state
            raise UpdateFailed("Failed to get device state: No data received and no cache available")

        self._cached_device_state = full_device_state
        self._last_state_fetch_time = time.time()
        
        # 💥 ALMACENAMIENTO DE LA VERDAD DE RED: Aislado de las toxinas de la UI
        self._pure_network_state = copy.deepcopy(full_device_state)

        if not self.controller.loader.is_fully_initialized:
            try:
                device_type = self.controller.config.get(CONF_DEVICE_TYPE)
                cache = self.controller.loader._parsed_yaml_cache
                id_map = (
                    cache.get(getattr(self.controller, "device_id", "XXXX"), {})
                    .get(CONFIG_DEVICE, {})
                    .get("identifiers")
                )

                if id_map:
                    self.controller.discovered_devices = get_value_by_path(
                        full_device_state, id_map.get("path_to_devices", [])
                    )

                    if self.controller.discovered_devices:
                        device_to_discover = None

                        if device_type == DEVICE_TYPE_MIM_H03:
                            device_to_discover = next(
                                (d for d in self.controller.discovered_devices if d and d.get("id") != "0" and "Mode" in d),
                                None,
                            )
                        else:
                            device_to_discover = self.controller.discovered_devices[0]

                        if device_to_discover:
                            id_path = id_map.get("id")
                            discovered_id = (
                                get_value_by_path(device_to_discover, id_path) if id_path else None
                            )
                            curr_dev_id = getattr(self.controller, "device_id", "")
                            if discovered_id is not None and (not curr_dev_id or curr_dev_id == "0"):
                                if hasattr(self.controller, "device_id"):
                                    self.controller.device_id = str(discovered_id)

                await self.controller.loader.async_finish_initialization()

            except Exception as e:
                _LOGGER.exception("%s Error during initial device discovery: %s", self.controller.log_prefix, e)

        await self.async_update_properties_from_state(full_device_state)
        return self.controller.loader.state_getter.value

    @staticmethod
    def _values_match(val1: Any, val2: Any) -> bool:
        """Check if two values match numerically (float cast) or string-wise (case-insensitive)."""
        if val1 is None or val2 is None:
            return val1 == val2
        if hasattr(val1, "value") and not isinstance(val1, dict): val1 = val1.value
        if hasattr(val2, "value") and not isinstance(val2, dict): val2 = val2.value
        try:
            return float(val1) == float(val2)
        except (ValueError, TypeError):
            return str(val1).strip().lower() == str(val2).strip().lower()

    def _get_device_key_from_template(self, template_obj: Any) -> str | None:
        """Extract the JSON key from a Jinja template string natively ($O(N)$ string slicing)."""
        if not template_obj:
            return None

        template_string = (
            template_obj.template
            if hasattr(template_obj, "template")
            else str(template_obj)
        )
        if not template_string:
            return None

        def _extract_key(text: str) -> str:
            for i, char in enumerate(text):
                if not (char.isalnum() or char == "_"):
                    return text[:i]
            return text

        if "device_state." in template_string:
            parts = template_string.split("device_state.", 1)[1]
            key = _extract_key(parts)
            return key if key else None

        if "device_state[" in template_string:
            parts = template_string.split("device_state[", 1)[1]
            if parts and parts[0] in ("'", '"'):
                parts = parts[1:]
            key = _extract_key(parts)
            return key if key else None

        return None

    def _get_cached_device_key_from_prop(self, prop: Any) -> str | None:
        """Extract and cache the raw JSON key mapped to a specific property from its template."""
        prop_id = getattr(prop, "id", None)
        if not prop_id:
            return None

        if prop_id in self._prop_template_key_cache:
            return self._prop_template_key_cache[prop_id]

        status_tmpl = getattr(prop, "status_template", None)
        key = self._get_device_key_from_template(status_tmpl)
        self._prop_template_key_cache[prop_id] = key
        return key

    def _inject_value_into_state(self, prop: Any, device_state: dict, value: Any) -> None:
        """Safely inject an optimistic value into the raw device state bypassing stale network data."""
        if not isinstance(device_state, dict):
            return

        if hasattr(prop, "set_device_state_for_values"):
            try:
                # Deep paths para el 8888
                prop.set_device_state_for_values(device_state)
            except Exception:
                pass
                
        op_id = getattr(prop, "id", "")
        
        # BLINDAJE SEMÁNTICO (Anti-Corrupción de Memoria Protocolo 2878)
        device_key = None
        if op_id in ("hvac", "hvac_mode", ATTR_HVAC_MODE) and "AC_FUN_OPMODE" in device_state:
            device_key = "AC_FUN_OPMODE"
        elif op_id in ("temperature", "target_temperature", ATTR_TEMPERATURE) and "AC_FUN_TEMPSET" in device_state:
            device_key = "AC_FUN_TEMPSET"
        elif op_id in ("fan", "fan_mode", ATTR_FAN_MODE) and "AC_FUN_WINDLEVEL" in device_state:
            device_key = "AC_FUN_WINDLEVEL"
        elif op_id in ("swing", "swing_mode", ATTR_SWING_MODE) and "AC_FUN_DIRECTION" in device_state:
            device_key = "AC_FUN_DIRECTION"
        elif op_id in ("preset", "preset_mode", ATTR_PRESET_MODE) and "AC_FUN_COMODE" in device_state:
            device_key = "AC_FUN_COMODE"
            
        if not device_key:
            device_key = self._get_cached_device_key_from_prop(prop)
            
        if not device_key:
            return
            
        dev_val = value
        if hasattr(prop, "convert_hass_to_dev"):
            try:
                dev_val = prop.convert_hass_to_dev(value)
            except Exception:
                pass
            
        if device_key in device_state:
            device_state[device_key] = dev_val
        else:
            # Fallback para estructuras anidadas (ej. 8888 API) usando state_node
            state_node = getattr(prop, "state_node", None)
            if state_node and isinstance(state_node, str):
                parts = state_node.split(".")
                current = device_state
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        if isinstance(current, dict):
                            current[part] = dev_val
                        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                            current[int(part)] = dev_val
                    else:
                        if isinstance(current, dict):
                            current = current.get(part, {})
                        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                            current = current[int(part)]
                        else:
                            break
            
        # Hardcode semántico universal para Power
        if op_id in ("hvac", "hvac_mode", ATTR_HVAC_MODE):
            power_op = self.controller.loader.operations.get("power") or self.controller.loader.properties.get("power")
            power_key = None
            if power_op:
                power_key = self._get_cached_device_key_from_prop(power_op)
            if not power_key and "AC_FUN_POWER" in device_state:
                power_key = "AC_FUN_POWER"
                
            if power_key and power_key in device_state:
                is_off = (str(value).lower() == "off" or str(dev_val).lower() == "off")
                device_state[power_key] = "Off" if is_off else "On"

    async def async_update_properties_from_state(
        self,
        full_device_state: dict[str, Any] | None = None,
        is_prediction: bool = False,
        force_update: bool = False,
        current_hass_state: Any | None = None,
        changed_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        """Update individual entity properties shielding from stale polls via pending locks."""
        if not self.controller.loader.is_fully_initialized:
            return {}

        if is_prediction:
            _LOGGER.debug("%s [Forensic] Prediction started. pending_updates=%s", self.controller.log_prefix, self._pending_updates) # pragma: no mutate

        if full_device_state is None:
            st_getter = self.controller.loader.state_getter
            if st_getter and st_getter.value:
                full_device_state = st_getter.value
            else:
                return {}

        device_to_process = full_device_state
        pure_device_to_process = getattr(self, "_pure_network_state", {})

        try:
            cache = self.controller.loader._parsed_yaml_cache
            id_map = (
                cache.get(getattr(self.controller, "device_id", "XXXX"), {})
                .get(CONFIG_DEVICE, {})
                .get("identifiers")
            )
            if id_map:
                devices_list = get_value_by_path(
                    full_device_state, id_map.get("path_to_devices", [])
                )
                if devices_list:
                    found_device = next(
                        (
                            d
                            for d in devices_list
                            if d
                            and str(get_value_by_path(d, id_map.get("id", [])))
                            == str(getattr(self.controller, "device_id", ""))
                        ),
                        None,
                    )
                    if not found_device and devices_list:
                        found_device = devices_list[0]

                    if found_device:
                        device_to_process = found_device
                        
                # Extraemos el nodo correspondiente también para el estado PURO
                pure_devices_list = get_value_by_path(
                    pure_device_to_process, id_map.get("path_to_devices", [])
                )
                if pure_devices_list:
                    found_pure_device = next(
                        (
                            d
                            for d in pure_devices_list
                            if d
                            and str(get_value_by_path(d, id_map.get("id", [])))
                            == str(getattr(self.controller, "device_id", ""))
                        ),
                        None,
                    )
                    if not found_pure_device and pure_devices_list:
                        found_pure_device = pure_devices_list[0]
                    
                    if found_pure_device:
                        pure_device_to_process = found_pure_device

        except Exception as e:  # pylint: disable=broad-exception-caught
            device_to_process = full_device_state
            pure_device_to_process = getattr(self, "_pure_network_state", {})

        if not is_prediction:
            if (
                not force_update
                and not self._pending_updates
                and getattr(self, "_last_device_state", None) == device_to_process
            ):
                return {}

            self._last_device_state = copy.deepcopy(device_to_process)
            
        corrections: dict[str, Any] = {}
        all_properties = (
            list(self.controller.loader.operations.values())
            + list(self.controller.loader.properties.values())
            + list(self.controller.loader.sensors.values())
        )

        # ------------------- MOTOR ANTI-FLICKER (ESTADO SOMBRA) -------------------
        # MUST RUN FIRST to inject optimistic locks into device_to_process BEFORE parsing properties
        now = time.time()
        for prop_id, (pend_val, ts) in list(self._pending_updates.items()):
            # TTL extendido a 45s para procesar todas las colas del AC sin pestañear
            if now - ts > 45.0:
                del self._pending_updates[prop_id]
                _LOGGER.debug("%s [Forensic] Lock expired for %s", self.controller.log_prefix, prop_id) # pragma: no mutate
                continue
                
            for op in all_properties:
                op_id = getattr(op, "id", "")
                if op_id == prop_id or self._get_hass_attr_for_op_id(op_id) == prop_id:
                    
                    pure_val = None
                    if hasattr(op, "calculate_value_from_state") and pure_device_to_process:
                        try:
                            # 💥 LA MAGIA OCURRE AQUÍ: Evaluamos el candado CONTRA EL ESTADO DE RED PURO
                            pure_val = op.calculate_value_from_state(pure_device_to_process)
                        except Exception:
                            pass
                            
                    # Si el estado físico REAL del equipo al fin coincide con la UI, borramos el escudo
                    can_release = True
                    device_key = self._get_cached_device_key_from_prop(op)
                    if not device_key:
                        if op_id in ("hvac", "hvac_mode", ATTR_HVAC_MODE): device_key = "AC_FUN_OPMODE"
                        elif op_id in ("temperature", "target_temperature", ATTR_TEMPERATURE): device_key = "AC_FUN_TEMPSET"
                        elif op_id in ("fan", "fan_mode", ATTR_FAN_MODE): device_key = "AC_FUN_WINDLEVEL"
                        elif op_id in ("swing", "swing_mode", ATTR_SWING_MODE): device_key = "AC_FUN_DIRECTION"
                        elif op_id in ("preset", "preset_mode", ATTR_PRESET_MODE): device_key = "AC_FUN_COMODE"

                    lock_age = now - ts
                    
                    if lock_age < 5.0:
                        # Blindaje Temporal: Ignoramos coincidencias si el candado es muy joven (<5s).
                        can_release = False
                    elif not is_prediction and changed_keys is not None:
                        if device_key and device_key not in changed_keys:
                            can_release = False
                            
                    _LOGGER.debug("%s [Forensic-Verbose] Eval %s: pend_val=%s, pure_val=%s, changed_keys=%s, device_key=%s, can_release=%s", self.controller.log_prefix, prop_id, pend_val, pure_val, changed_keys, device_key, can_release) # pragma: no mutate

                    if not is_prediction and can_release and pure_val is not None and self._values_match(pure_val, pend_val):
                        _LOGGER.debug("%s [Forensic] Lock released for %s. Pure matches pend_val: %s", self.controller.log_prefix, prop_id, pend_val) # pragma: no mutate
                        del self._pending_updates[prop_id]
                    else:
                        _LOGGER.debug("%s [Forensic] Lock enforced for %s. Injecting %s into state.", self.controller.log_prefix, prop_id, pend_val) # pragma: no mutate
                        # Forzamos la UI a mantenerse en el estado esperado y envenenamos la variable local
                        if hasattr(op, "value"):
                            op.value = pend_val
                        elif hasattr(op, "_value"):
                            op._value = pend_val
                            
                        self._inject_value_into_state(op, device_to_process, pend_val)
                    break
        # -------------------------------------------------------------------------

        for prop in all_properties:
            if hasattr(prop, "async_update_state"):
                try:
                    await prop.async_update_state(
                        device_to_process, getattr(self.controller, "debug", False)
                    )
                except Exception:
                    pass

        # INYECCIÓN NATIVA DE RESPALDO (Asegura consistencia en memoria para HA)
        for prop in all_properties:
            val = getattr(prop, "value", getattr(prop, "_value", None))
            if val is not None:
                self._inject_value_into_state(prop, device_to_process, val)

        # Predicción de cascadas de Dependencia (Ej: Fan vs HVAC Mode)
        for _, op in list(self.controller.loader.operations.items()):
            if hasattr(op, "is_valid") and not op.is_valid(device_to_process):
                continue

            op_value = getattr(op, "value", getattr(op, "_value", None))
            
            op_values = None
            if hasattr(op, "get_valid_values"):
                op_values = op.get_valid_values(device_to_process)
            elif hasattr(op, "values"):
                op_values = list(op.values.keys()) if isinstance(op.values, dict) else op.values

            if op_values and op_value is not None and op_value != STATE_UNKNOWN:
                if op_value not in op_values:
                    # Corrección predictiva inyectada
                    new_value = op_values[0] if op_values else STATE_UNKNOWN
                    _LOGGER.debug("%s [Forensic] Predictive correction for %s: %s -> %s", self.controller.log_prefix, op.id, op_value, new_value) # pragma: no mutate
                    if hasattr(op, "value"):
                        op.value = new_value
                    elif hasattr(op, "_value"):
                        op._value = new_value
                    corrections[op.id] = new_value
                    self._inject_value_into_state(op, device_to_process, new_value)

                if (
                    getattr(op, "feature_flag", getattr(op, "_feature_flag", None))
                    == ClimateEntityFeature.FAN_MODE
                ):
                    self.fan_modes_list_changed_pending_flicker = True

        self._rebuild_attributes()
        
        # 💥 ESCUDO ABSOLUTO: Envenenamos la RAM cruda con la copia blindada
        st_getter = self.controller.loader.state_getter
        if st_getter and not is_prediction:
            if hasattr(st_getter, "value"):
                st_getter.value = device_to_process
            elif hasattr(st_getter, "_value"):
                st_getter._value = device_to_process

        if is_prediction:
            _LOGGER.debug("%s [Forensic] Prediction ended. Corrections=%s", self.controller.log_prefix, corrections) # pragma: no mutate
            
        return corrections

    def _rebuild_attributes(self) -> None:
        """Rebuild the flattened state attributes dictionary."""
        new_attrs = {ATTR_NAME: getattr(self.controller, "name", "Unknown")}
        all_properties = list(self.controller.loader.operations.values()) + list(
            self.controller.loader.properties.values()
        )
        for prop in all_properties:
            if hasattr(prop, "state_attributes"):
                new_attrs.update(prop.state_attributes)
        new_attrs["last_sync"] = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")

        if hasattr(self.controller, "update_state_attributes"):
            self.controller.update_state_attributes(new_attrs)
        elif hasattr(self.controller, "_attributes"):
            self.controller._attributes = new_attrs

    def _get_hass_attr_for_op_id(self, op_id: str) -> str:
        """Map YAML operation IDs to HA Attributes for validation mapping."""
        mapping = {
            "hvac": "hvac_mode",  # pragma: no mutate
            "hvac_mode": "hvac_mode",  # pragma: no mutate
            "temperature": "target_temperature",  # pragma: no mutate
            "target_temperature": "target_temperature",  # pragma: no mutate
            "current_temperature": "current_temperature",  # pragma: no mutate
            "fan": "fan_mode",  # pragma: no mutate
            "fan_mode": "fan_mode",  # pragma: no mutate
            "swing": "swing_mode",  # pragma: no mutate
            "swing_mode": "swing_mode",  # pragma: no mutate
            "preset": "preset_mode",  # pragma: no mutate
            "preset_mode": "preset_mode",  # pragma: no mutate
            "special": "preset_mode",  # pragma: no mutate
        }
        return mapping.get(op_id, op_id)

    def _calculate_structured_state(
        self, raw_state: dict[str, Any]
    ) -> ClimateIPDeviceState | None:
        """Pure dry-run calculation of the ClimateIPDeviceState from raw data."""
        if not self.controller.loader.is_fully_initialized:
            return None

        try:
            mapping = {
                ATTR_HVAC_MODE: "hvac_mode",
                ATTR_TEMPERATURE: "target_temperature",
                "current_temperature": "current_temperature",
                ATTR_FAN_MODE: "fan_mode",
                ATTR_SWING_MODE: "swing_mode",
                ATTR_PRESET_MODE: "preset_mode",
            }

            all_properties = (
                list(self.controller.loader.operations.values())
                + list(self.controller.loader.properties.values())
                + list(self.controller.loader.sensors.values())
            )

            prop_values = {}
            for prop in all_properties:
                prop_id = getattr(prop, "id", None)
                if prop_id and hasattr(prop, "calculate_value_from_state"):
                    prop_values[mapping.get(prop_id)] = prop.calculate_value_from_state(
                        raw_state
                    )

            return ClimateIPDeviceState(
                hvac_mode=prop_values.get("hvac_mode"),
                target_temperature=prop_values.get("target_temperature"),
                current_temperature=prop_values.get("current_temperature"),
                fan_mode=prop_values.get("fan_mode"),
                swing_mode=prop_values.get("swing_mode"),
                preset_mode=prop_values.get("preset_mode"),
            )
        except Exception:
            return None

    async def async_merge_device_state(
        self, new_data: dict[str, Any], _is_response: bool, _is_update: bool
    ) -> bool:
        """Merge a partial state update (e.g. from a push notification) into the known state."""
        if not new_data:
            return False

        st_getter = self.controller.loader.state_getter
        if not st_getter:
            return False
            
        if getattr(self, "_pure_network_state", None) is None:
            self._pure_network_state = {}
            
        if not self._pure_network_state:
            if st_getter.value:
                self._pure_network_state = copy.deepcopy(st_getter.value)
            else:
                return False

        # Ingresamos la trama limpia a nuestro diccionario inmaculado de red
        self._pure_network_state.update(new_data)

        # Clonamos la red base pura antes de que el motor Anti-Flicker la envenene para la UX
        candidate_state = copy.deepcopy(self._pure_network_state)

        structured_candidate = self._calculate_structured_state(candidate_state)
        if hasattr(st_getter, "value"):
            st_getter.value = candidate_state
        elif hasattr(st_getter, "_value"):
            st_getter._value = candidate_state

        await self.async_update_properties_from_state(
            candidate_state, force_update=True, changed_keys=set(new_data.keys())
        )

        return True

    async def async_predict_and_correct_state(
        self,
        current_hass_state: ClimateIPDeviceState,
        property_name: str,
        new_value: Any,
    ) -> tuple[ClimateEntityFeature, dict[str, Any]]:
        """Predict the expected state after command natively bypassing abstraction leaks."""
        # 💥 ESCUDO EN CASCADA: Registramos el comando principal ANTES de predecir!
        _LOGGER.debug("%s [Forensic] async_predict_and_correct_state started for %s=%s", self.controller.log_prefix, property_name, new_value) # pragma: no mutate
        self.register_pending_update(property_name, new_value)

        if (
            not self.controller.loader.state_getter
            or not self.controller.loader.is_fully_initialized
        ):
            return ClimateEntityFeature(0), {}

        st_getter = self.controller.loader.state_getter
        if not st_getter.value or not isinstance(st_getter.value, dict):
            return ClimateEntityFeature(0), {}

        corrections: dict[str, Any] = {}

        prop_to_change = None
        for op in self.controller.loader.operations.values():
            op_id = getattr(op, "id", "")
            if op_id == property_name or self._get_hass_attr_for_op_id(op_id) == property_name:
                prop_to_change = op
                break

        if not prop_to_change:
            return ClimateEntityFeature(0), {}

        if new_value is not None and hasattr(new_value, "value") and not isinstance(new_value, dict):
            new_value = new_value.value

        if hasattr(prop_to_change, "value"):
            prop_to_change.value = new_value
        elif hasattr(prop_to_change, "_value"):
            prop_to_change._value = new_value

        self._inject_value_into_state(prop_to_change, st_getter.value, new_value)

        # Re-evaluación Predictiva sobre la memoria (El flag is_prediction previene borrar escudos tempranamente)
        update_result = await self.async_update_properties_from_state(
            st_getter.value, is_prediction=True
        )
        corrections.update(update_result)

        # 💥 ESCUDO EN CASCADA: Registra las correciones predictivas
        for key, val in corrections.items():
            self.register_pending_update(key, val)

        return ClimateEntityFeature(0), corrections

    async def async_shutdown(self) -> None:
        """Shut down the poller and cleanly close any active connections."""
        conn = self.controller.loader.connection
        if conn:
            async def _try(coro):  # pylint: disable=invalid-name
                try:
                    await coro
                except Exception:
                    pass

            if hasattr(conn, "stop_listening"):
                await _try(conn.stop_listening())

            if hasattr(self.controller, "close_shared_client"):
                await _try(self.controller.close_shared_client())
            elif hasattr(self.controller, "_shared_raw_client"):
                raw_client = self.controller._shared_raw_client
                if raw_client and hasattr(raw_client, "close"):
                    await _try(raw_client.close())
                self.controller._shared_raw_client = None

            if hasattr(conn, "close"):
                await _try(conn.close())

            self.controller.loader.connection = None

        await asyncio.sleep(1.0)

    @property
    def last_device_state(self) -> dict[str, Any] | None:
        """Return the last known parsed device state."""
        return self._last_device_state