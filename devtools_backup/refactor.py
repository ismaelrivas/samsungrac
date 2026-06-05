import re

with open("custom_components/climate_ip/config_flow.py", "r") as f:
    code = f.read()

# is_matching
code = re.sub(
    r'    def is_matching\(self, other_flow: Self\) -> bool:(.*?)\n        return False\n',
    r'''    def is_matching(self, other_flow: Self) -> bool:
        """Return True if other_flow matches this flow (same physical device)."""
        self_ip = self.context.get(CONF_IP_ADDRESS) or self.flow_data.get(CONF_IP_ADDRESS)
        other_ip = other_flow.context.get(CONF_IP_ADDRESS) or other_flow.flow_data.get(CONF_IP_ADDRESS)
        if self_ip and other_ip and self_ip == other_ip:
            return True

        self_mac = self.context.get(CONF_MAC) or self.flow_data.get(CONF_MAC)
        other_mac = other_flow.context.get(CONF_MAC) or other_flow.flow_data.get(CONF_MAC)
        return bool(self_mac and other_mac and self_mac.upper() == other_mac.upper())
''',
    code, flags=re.DOTALL
)

# _get_base_samsung_schema
code = re.sub(
    r'    def _get_base_samsung_schema\(\s*self,\s*mac_required: bool = False,\s*is_8888: bool = False\s*\) -> vol\.Schema:.*?return vol\.Schema\(schema_dict\)\n',
    r'''    def _get_base_samsung_schema(self, mac_required: bool = False, is_8888: bool = False) -> vol.Schema:
        """Helper to generate the shared configuration schema for all Samsung devices."""
        raw_mac = self.flow_data.get(CONF_MAC, "")
        formatted_mac = ":".join(raw_mac[i:i + 2] for i in range(0, len(raw_mac), 2)) if raw_mac else ""

        try:
            interval_str = str(datetime.timedelta(seconds=int(self.flow_data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))))
        except (ValueError, TypeError):
            interval_str = str(self.flow_data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))

        schema_dict: dict[vol.Marker, Any] = {
            vol.Required(CONF_IP_ADDRESS, default=self.flow_data.get(CONF_IP_ADDRESS, "")): str,
            (vol.Required if mac_required else vol.Optional)(CONF_MAC, default=formatted_mac): str,
            vol.Optional(CONF_NAME, default=self.flow_data.get(CONF_NAME, "")): str,
            vol.Optional(CONF_TOKEN, default=self.flow_data.get(CONF_TOKEN, "")): str,
            vol.Optional(CONF_CERT, default=self.flow_data.get(CONF_CERT, "ac14k_m.pem" if is_8888 else "")): str,
            vol.Optional(CONF_POLL_INTERVAL, default=interval_str): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        }

        if not is_8888:
            schema_dict[vol.Optional(CONF_ENABLE_POLLING, default=self.flow_data.get(CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING))] = bool

        temp_selector = SelectSelector(SelectSelectorConfig(options=[UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT], mode=SelectSelectorMode.DROPDOWN))
        schema_dict |= {
            vol.Optional(CONF_TEMP_NATIVE_CURRENT, default=self.flow_data.get(CONF_TEMP_NATIVE_CURRENT, DEFAULT_CONF_TEMP_UNIT)): temp_selector,
            vol.Optional(CONF_TEMP_NATIVE_TARGET, default=self.flow_data.get(CONF_TEMP_NATIVE_TARGET, DEFAULT_CONF_TEMP_UNIT)): temp_selector,
        }
        return vol.Schema(schema_dict)
''',
    code, flags=re.DOTALL
)

# _validate_poll_interval
code = re.sub(
    r'    def _validate_poll_interval\(self,\s*user_input:\s*dict\[str, Any\]\)\s*->\s*int \| None:.*?return seconds\n',
    r'''    def _validate_poll_interval(self, user_input: dict[str, Any]) -> int | None:
        """Extract and validate poll interval from user input."""
        if (val := user_input.get(CONF_POLL_INTERVAL)) is None:
            return None

        seconds = int(val) if isinstance(val, (int, float)) else int(cv.time_period_str(str(val)).total_seconds())
        if not MIN_POLL_INTERVAL <= seconds <= MAX_POLL_INTERVAL:
            raise vol.Invalid(f"Interval must be between {MIN_POLL_INTERVAL} and {MAX_POLL_INTERVAL} seconds")

        return seconds
''',
    code, flags=re.DOTALL
)

# _get_rest_api_schema
code = re.sub(
    r'    def _get_rest_api_schema\(self\) -> vol\.Schema:.*?return vol\.Schema\(schema\)\n',
    r'''    def _get_rest_api_schema(self) -> vol.Schema:
        """Generate the schema for REST API based devices that require manual token."""
        device_type = self.flow_data.get(CONF_DEVICE_TYPE)
        is_st = device_type in (DEVICE_TYPE_SMARTTHINGS_HVAC, DEVICE_TYPE_SMARTTHINGS_DHW)

        try:
            interval_str = str(datetime.timedelta(seconds=int(self.flow_data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))))
        except (ValueError, TypeError):
            interval_str = str(self.flow_data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))

        default_token = self.flow_data.get(CONF_TOKEN) or (self._get_smartthings_token() if is_st else "")

        schema: dict[vol.Marker, Any] = {
            vol.Required(CONF_IP_ADDRESS, default="api.smartthings.com") if is_st else vol.Required(CONF_IP_ADDRESS): str,
        } | ({vol.Optional(CONF_DEVICE_ID): str} if is_st else {}) | {
            vol.Required(CONF_TOKEN, default=default_token): str,
            vol.Optional(CONF_NAME): str,
            vol.Optional(CONF_POLL_INTERVAL, default=interval_str): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        }

        return vol.Schema(schema)
''',
    code, flags=re.DOTALL
)

# _get_options_schema
code = re.sub(
    r'    def _get_options_schema\(self\) -> vol\.Schema:.*?return vol\.Schema\(schema_dict\)\n',
    r'''    def _get_options_schema(self) -> vol.Schema:
        """Return the schema for the options flow."""
        schema_dict: dict[vol.Marker, Any] = {}

        if self._config_entry.data.get(CONF_DEVICE_TYPE) in DEVICE_TYPE_AIOHTTP_SUPPORTED:
            schema_dict[vol.Required(
                CONF_CONN_METHOD,
                default=self._config_entry.options.get(CONF_CONN_METHOD, self._config_entry.data.get(CONF_CONN_METHOD, CONN_METHOD_AIOHTTP)),
            )] = SelectSelector(SelectSelectorConfig(
                options=[
                    {"value": CONN_METHOD_REQUESTS, "label": "Legacy (Obsolete)"},
                    {"value": CONN_METHOD_AIOHTTP, "label": "Modern (aiohttp)"},
                    {"value": CONN_METHOD_RAW, "label": "Robust (raw socket)"},
                ],
                mode=SelectSelectorMode.DROPDOWN, translation_key="connection_method",
            ))

        current_val = self._config_entry.options.get(CONF_POLL_INTERVAL, self._config_entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
        try:
            current_str = str(datetime.timedelta(seconds=int(current_val)))
        except (ValueError, TypeError):
            current_str = str(current_val)

        temp_selector = SelectSelector(SelectSelectorConfig(options=[UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT], mode=SelectSelectorMode.DROPDOWN))

        schema_dict |= {
            vol.Required(CONF_POLL_INTERVAL, default=current_str): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Required(CONF_TEMP_NATIVE_CURRENT, default=self._config_entry.options.get(CONF_TEMP_NATIVE_CURRENT, DEFAULT_CONF_TEMP_UNIT)): temp_selector,
            vol.Required(CONF_TEMP_NATIVE_TARGET, default=self._config_entry.options.get(CONF_TEMP_NATIVE_TARGET, DEFAULT_CONF_TEMP_UNIT)): temp_selector,
            vol.Optional(CONF_ENABLE_POLLING, default=self._config_entry.options.get(CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING)): bool,
        }

        return vol.Schema(schema_dict)
''',
    code, flags=re.DOTALL
)

with open("custom_components/climate_ip/config_flow.py", "w") as f:
    f.write(code)

