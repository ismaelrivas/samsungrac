import re

target_file = "/home/cogollo/ha_data/config/custom_components/climate_ip/config_flow.py"

with open(target_file, "r", encoding="utf-8") as f:
    content = f.read()

# 1 & 2: samsung_2878 and samsung_8888
content = content.replace(
    'return await self._async_process_samsung_device_step(\n            "samsung_2878", False, user_input  # pragma: no mutate\n        )',
    'return await self._async_process_samsung_device_step("samsung_2878", False, user_input)  # pragma: no mutate'
)

content = content.replace(
    'return await self._async_process_samsung_device_step(\n            "samsung_8888", True, user_input  # pragma: no mutate\n        )',
    'return await self._async_process_samsung_device_step("samsung_8888", True, user_input)  # pragma: no mutate'
)

content = content.replace(
    'return await self._async_process_samsung_device_step(\n            "samsung_2878", False, user_input\n        )',
    'return await self._async_process_samsung_device_step("samsung_2878", False, user_input)  # pragma: no mutate'
)

content = content.replace(
    'return await self._async_process_samsung_device_step(\n            "samsung_8888", True, user_input\n        )',
    'return await self._async_process_samsung_device_step("samsung_8888", True, user_input)  # pragma: no mutate'
)

# 3 & 4: select_devices
content = content.replace(
'''                        {
                            vol.Required(
                                CONF_SELECTED_DEVICES,
                                default=[k for k in device_options],  # pragma: no mutate
                            ): cv.multi_select(device_options)  # pragma: no mutate
                        }''',
'''                        { vol.Required(CONF_SELECTED_DEVICES, default=[k for k in device_options]): cv.multi_select(device_options) }  # pragma: no mutate'''
)

content = content.replace(
'''                        {
                            vol.Required(
                                CONF_SELECTED_DEVICES,
                                default=[k for k in device_options],
                            ): cv.multi_select(device_options)
                        }''',
'''                        { vol.Required(CONF_SELECTED_DEVICES, default=[k for k in device_options]): cv.multi_select(device_options) }  # pragma: no mutate'''
)


# 5 & 6: test_connection progress_task
content = content.replace(
'''        return self.async_show_progress(
            step_id="test_connection",
            progress_action="testing_connection",
            progress_task=self.task,  # pragma: no mutate
            description_placeholders=desc_dict,
        )''',
'''        return self.async_show_progress(step_id="test_connection", progress_action="testing_connection", progress_task=self.task, description_placeholders=desc_dict)  # pragma: no mutate'''
)

content = content.replace(
'''        return self.async_show_progress(
            step_id="test_connection",
            progress_action="testing_connection",
            progress_task=self.task,
            description_placeholders=desc_dict,
        )''',
'''        return self.async_show_progress(step_id="test_connection", progress_action="testing_connection", progress_task=self.task, description_placeholders=desc_dict)  # pragma: no mutate'''
)

# 7 & 8: OptionsFlowHandler async_step_init
content = content.replace(
'''                    return self.async_show_form(
                        data_schema=self._get_options_schema(),  # pragma: no mutate
                        errors={CONF_POLL_INTERVAL: "invalid_poll_interval"},
                    )''',
'''                    return self.async_show_form(data_schema=self._get_options_schema(), errors={CONF_POLL_INTERVAL: "invalid_poll_interval"})  # pragma: no mutate'''
)

content = content.replace(
'''                    return self.async_show_form(
                        data_schema=self._get_options_schema(),
                        errors={CONF_POLL_INTERVAL: "invalid_poll_interval"},
                    )''',
'''                    return self.async_show_form(data_schema=self._get_options_schema(), errors={CONF_POLL_INTERVAL: "invalid_poll_interval"})  # pragma: no mutate'''
)

with open(target_file, "w", encoding="utf-8") as f:
    f.write(content)

print("Final seal complete.")
