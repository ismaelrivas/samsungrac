# Mutant Hardening Analysis & Grouping

Generated on: 2026-06-24T18:57:22.712751

- **Total Mutants Analysed**: 590
- **Non-Redundant Mutants**: 240
- **Redundant/Excluded Mutants**: 350

## Summary of Non-Redundant Mutants by Component

| Class | Method / Function | Count | Target Mutants |
| --- | --- | --- | --- |
| ConnectionAiohttp8888 | __init__ | 1 | 20 |
| ConnectionAiohttp8888 | _async_execute_request | 76 | 1, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 22, 24, 25, 28, 29, 30, 31, 33, 34, 35, 36, 43, 44, 45, 51, 52, 53, 67, 68, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 87, 88, 89, 90, 96, 102, 116, 118, 119, 122, 124, 125, 144, 145, 165, 166, 215, 216, 217, 219, 220, 221, 222, 223, 225, 226, 227, 228, 229 |
| ConnectionAiohttp8888 | _create_ssl_context | 4 | 3, 5, 8, 11 |
| ConnectionAiohttp8888 | _format_url | 16 | 7, 8, 9, 11, 12, 13, 14, 15, 22, 25, 39, 41, 42, 51, 53, 56 |
| ConnectionAiohttp8888 | _get_session | 10 | 3, 4, 10, 41, 42, 43, 44, 45, 46, 47 |
| ConnectionAiohttp8888 | _resolve_cert_path | 4 | 2, 3, 5, 6 |
| ConnectionAiohttp8888 | _try_connection | 67 | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 73, 74, 75, 76, 77, 79, 80, 81, 82, 84, 85, 86, 87, 89, 90, 100, 101, 102, 133 |
| ConnectionAiohttp8888 | async_execute | 60 | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 99, 100, 101, 102, 104, 105, 106, 107, 118, 120, 152, 156, 157, 158, 196, 197, 198, 199, 200, 230, 231, 232, 233, 234, 239 |
| ConnectionAiohttp8888 | close | 1 | 34 |
| ConnectionAiohttp8888 | create_updated | 1 | 48 |

## Detail of Non-Redundant Mutants

### ConnectionAiohttp8888.__init__

#### Mutant ID: 20
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ__init____mutmut_20`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -25,7 +25,7 @@
         # This will hold the Jinja2 template for this specific connection instance.
         self._connection_template: Template | None = None
 
-        self.condition_template: Template | None = None
+        self.condition_template: Template | None = ""
         self._embedded_command: "ConnectionAiohttp8888" | None = None
         self._ssl_context: ssl.SSLContext | None = None
 
```

### ConnectionAiohttp8888._async_execute_request

#### Mutant ID: 1
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_1`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -4,7 +4,7 @@
         url_path: str | None,
         data: str | None,
         headers: dict[str, str] | None,
-        _is_poll: bool = False,
+        _is_poll: bool = True,
     ) -> tuple[str, dict[str, str] | None]:
         """
         Executes a command asynchronously using aiohttp.
```

#### Mutant ID: 5
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_5`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -13,7 +13,7 @@
         req_headers = headers.copy() if headers is not None else {}
 
         current_token = self._token
-        raw_host = self._ip_address or self._params.get(CONF_HOST)
+        raw_host = None
         host = str(raw_host) if raw_host is not None else ""
         
         raw_mac = self._params.get(CONF_MAC)
```

#### Mutant ID: 6
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_6`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -13,7 +13,7 @@
         req_headers = headers.copy() if headers is not None else {}
 
         current_token = self._token
-        raw_host = self._ip_address or self._params.get(CONF_HOST)
+        raw_host = self._ip_address and self._params.get(CONF_HOST)
         host = str(raw_host) if raw_host is not None else ""
         
         raw_mac = self._params.get(CONF_MAC)
```

#### Mutant ID: 7
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_7`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -13,7 +13,7 @@
         req_headers = headers.copy() if headers is not None else {}
 
         current_token = self._token
-        raw_host = self._ip_address or self._params.get(CONF_HOST)
+        raw_host = self._ip_address or self._params.get(None)
         host = str(raw_host) if raw_host is not None else ""
         
         raw_mac = self._params.get(CONF_MAC)
```

#### Mutant ID: 8
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_8`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -14,7 +14,7 @@
 
         current_token = self._token
         raw_host = self._ip_address or self._params.get(CONF_HOST)
-        host = str(raw_host) if raw_host is not None else ""
+        host = None
         
         raw_mac = self._params.get(CONF_MAC)
         mac = str(raw_mac) if raw_mac is not None else ""
```

#### Mutant ID: 9
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_9`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -14,7 +14,7 @@
 
         current_token = self._token
         raw_host = self._ip_address or self._params.get(CONF_HOST)
-        host = str(raw_host) if raw_host is not None else ""
+        host = str(None) if raw_host is not None else ""
         
         raw_mac = self._params.get(CONF_MAC)
         mac = str(raw_mac) if raw_mac is not None else ""
```

#### Mutant ID: 10
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_10`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -14,7 +14,7 @@
 
         current_token = self._token
         raw_host = self._ip_address or self._params.get(CONF_HOST)
-        host = str(raw_host) if raw_host is not None else ""
+        host = str(raw_host) if raw_host is None else ""
         
         raw_mac = self._params.get(CONF_MAC)
         mac = str(raw_mac) if raw_mac is not None else ""
```

#### Mutant ID: 11
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_11`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -14,7 +14,7 @@
 
         current_token = self._token
         raw_host = self._ip_address or self._params.get(CONF_HOST)
-        host = str(raw_host) if raw_host is not None else ""
+        host = str(raw_host) if raw_host is not None else "XXXX"
         
         raw_mac = self._params.get(CONF_MAC)
         mac = str(raw_mac) if raw_mac is not None else ""
```

#### Mutant ID: 12
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_12`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -16,7 +16,7 @@
         raw_host = self._ip_address or self._params.get(CONF_HOST)
         host = str(raw_host) if raw_host is not None else ""
         
-        raw_mac = self._params.get(CONF_MAC)
+        raw_mac = None
         mac = str(raw_mac) if raw_mac is not None else ""
         
         dev_id = None
```

#### Mutant ID: 13
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_13`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -16,7 +16,7 @@
         raw_host = self._ip_address or self._params.get(CONF_HOST)
         host = str(raw_host) if raw_host is not None else ""
         
-        raw_mac = self._params.get(CONF_MAC)
+        raw_mac = self._params.get(None)
         mac = str(raw_mac) if raw_mac is not None else ""
         
         dev_id = None
```

#### Mutant ID: 14
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_14`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -17,7 +17,7 @@
         host = str(raw_host) if raw_host is not None else ""
         
         raw_mac = self._params.get(CONF_MAC)
-        mac = str(raw_mac) if raw_mac is not None else ""
+        mac = None
         
         dev_id = None
 
```

#### Mutant ID: 15
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_15`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -17,7 +17,7 @@
         host = str(raw_host) if raw_host is not None else ""
         
         raw_mac = self._params.get(CONF_MAC)
-        mac = str(raw_mac) if raw_mac is not None else ""
+        mac = str(None) if raw_mac is not None else ""
         
         dev_id = None
 
```

#### Mutant ID: 16
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_16`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -17,7 +17,7 @@
         host = str(raw_host) if raw_host is not None else ""
         
         raw_mac = self._params.get(CONF_MAC)
-        mac = str(raw_mac) if raw_mac is not None else ""
+        mac = str(raw_mac) if raw_mac is None else ""
         
         dev_id = None
 
```

#### Mutant ID: 17
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_17`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -17,7 +17,7 @@
         host = str(raw_host) if raw_host is not None else ""
         
         raw_mac = self._params.get(CONF_MAC)
-        mac = str(raw_mac) if raw_mac is not None else ""
+        mac = str(raw_mac) if raw_mac is not None else "XXXX"
         
         dev_id = None
 
```

#### Mutant ID: 18
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_18`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -19,7 +19,7 @@
         raw_mac = self._params.get(CONF_MAC)
         mac = str(raw_mac) if raw_mac is not None else ""
         
-        dev_id = None
+        dev_id = ""
 
         if self._controller is not None:
             current_token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
```

#### Mutant ID: 22
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_22`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -22,7 +22,7 @@
         dev_id = None
 
         if self._controller is not None:
-            current_token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
+            current_token = self._controller._config.get(CONF_TOKEN, None)  # pylint: disable=protected-access
             dev_id = self._controller.device_id
 
         # CRITICAL FIX: Replace placeholders in headers as well
```

#### Mutant ID: 24
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_24`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -22,7 +22,7 @@
         dev_id = None
 
         if self._controller is not None:
-            current_token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
+            current_token = self._controller._config.get(CONF_TOKEN, )  # pylint: disable=protected-access
             dev_id = self._controller.device_id
 
         # CRITICAL FIX: Replace placeholders in headers as well
```

#### Mutant ID: 25
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_25`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -23,7 +23,7 @@
 
         if self._controller is not None:
             current_token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
-            dev_id = self._controller.device_id
+            dev_id = None
 
         # CRITICAL FIX: Replace placeholders in headers as well
         req_headers = format_placeholders(
```

#### Mutant ID: 28
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_28`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -27,7 +27,7 @@
 
         # CRITICAL FIX: Replace placeholders in headers as well
         req_headers = format_placeholders(
-            req_headers, current_token, host, dev_id, mac
+            req_headers, None, host, dev_id, mac
         )
 
         if not current_token:
```

#### Mutant ID: 29
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_29`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -27,7 +27,7 @@
 
         # CRITICAL FIX: Replace placeholders in headers as well
         req_headers = format_placeholders(
-            req_headers, current_token, host, dev_id, mac
+            req_headers, current_token, None, dev_id, mac
         )
 
         if not current_token:
```

#### Mutant ID: 30
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_30`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -27,7 +27,7 @@
 
         # CRITICAL FIX: Replace placeholders in headers as well
         req_headers = format_placeholders(
-            req_headers, current_token, host, dev_id, mac
+            req_headers, current_token, host, None, mac
         )
 
         if not current_token:
```

#### Mutant ID: 31
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_31`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -27,7 +27,7 @@
 
         # CRITICAL FIX: Replace placeholders in headers as well
         req_headers = format_placeholders(
-            req_headers, current_token, host, dev_id, mac
+            req_headers, current_token, host, dev_id, None
         )
 
         if not current_token:
```

#### Mutant ID: 33
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_33`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -27,7 +27,7 @@
 
         # CRITICAL FIX: Replace placeholders in headers as well
         req_headers = format_placeholders(
-            req_headers, current_token, host, dev_id, mac
+            req_headers, host, dev_id, mac
         )
 
         if not current_token:
```

#### Mutant ID: 34
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_34`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -27,7 +27,7 @@
 
         # CRITICAL FIX: Replace placeholders in headers as well
         req_headers = format_placeholders(
-            req_headers, current_token, host, dev_id, mac
+            req_headers, current_token, dev_id, mac
         )
 
         if not current_token:
```

#### Mutant ID: 35
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_35`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -27,7 +27,7 @@
 
         # CRITICAL FIX: Replace placeholders in headers as well
         req_headers = format_placeholders(
-            req_headers, current_token, host, dev_id, mac
+            req_headers, current_token, host, mac
         )
 
         if not current_token:
```

#### Mutant ID: 36
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_36`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -27,8 +27,7 @@
 
         # CRITICAL FIX: Replace placeholders in headers as well
         req_headers = format_placeholders(
-            req_headers, current_token, host, dev_id, mac
-        )
+            req_headers, current_token, host, dev_id, )
 
         if not current_token:
             err_msg = "%s [aiohttp] No token available! The request will fail."  # pragma: no mutate
```

#### Mutant ID: 43
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_43`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
             exc_msg = "Token not configured for the aiohttp engine"  # pragma: no mutate
             raise AuthError(exc_msg)
 
-        if "Authorization" not in req_headers:
+        if "XXAuthorizationXX" not in req_headers:
             req_headers["Authorization"] = f"Bearer {current_token}"
         if "Content-Type" not in req_headers:
             req_headers["Content-Type"] = "application/json"
```

#### Mutant ID: 44
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_44`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
             exc_msg = "Token not configured for the aiohttp engine"  # pragma: no mutate
             raise AuthError(exc_msg)
 
-        if "Authorization" not in req_headers:
+        if "authorization" not in req_headers:
             req_headers["Authorization"] = f"Bearer {current_token}"
         if "Content-Type" not in req_headers:
             req_headers["Content-Type"] = "application/json"
```

#### Mutant ID: 45
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_45`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
             exc_msg = "Token not configured for the aiohttp engine"  # pragma: no mutate
             raise AuthError(exc_msg)
 
-        if "Authorization" not in req_headers:
+        if "AUTHORIZATION" not in req_headers:
             req_headers["Authorization"] = f"Bearer {current_token}"
         if "Content-Type" not in req_headers:
             req_headers["Content-Type"] = "application/json"
```

#### Mutant ID: 51
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_51`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -38,7 +38,7 @@
 
         if "Authorization" not in req_headers:
             req_headers["Authorization"] = f"Bearer {current_token}"
-        if "Content-Type" not in req_headers:
+        if "XXContent-TypeXX" not in req_headers:
             req_headers["Content-Type"] = "application/json"
 
         # Adaptive Keep-Alive Logic: If we previously detected stability issues, force Connection: close
```

#### Mutant ID: 52
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_52`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -38,7 +38,7 @@
 
         if "Authorization" not in req_headers:
             req_headers["Authorization"] = f"Bearer {current_token}"
-        if "Content-Type" not in req_headers:
+        if "content-type" not in req_headers:
             req_headers["Content-Type"] = "application/json"
 
         # Adaptive Keep-Alive Logic: If we previously detected stability issues, force Connection: close
```

#### Mutant ID: 53
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_53`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -38,7 +38,7 @@
 
         if "Authorization" not in req_headers:
             req_headers["Authorization"] = f"Bearer {current_token}"
-        if "Content-Type" not in req_headers:
+        if "CONTENT-TYPE" not in req_headers:
             req_headers["Content-Type"] = "application/json"
 
         # Adaptive Keep-Alive Logic: If we previously detected stability issues, force Connection: close
```

#### Mutant ID: 67
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_67`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -45,7 +45,7 @@
         if self._force_close_connection:
             req_headers["Connection"] = "close"
 
-        ssl_context = self._shared_state.ssl_context
+        ssl_context = None
         # Detect if the path is actually an absolute URL (for SmartThings).
         if url_path and url_path.startswith("http"):
             base_url = ""  # No base URL needed
```

#### Mutant ID: 68
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_68`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -47,7 +47,7 @@
 
         ssl_context = self._shared_state.ssl_context
         # Detect if the path is actually an absolute URL (for SmartThings).
-        if url_path and url_path.startswith("http"):
+        if url_path or url_path.startswith("http"):
             base_url = ""  # No base URL needed
             # Provide a default ssl_context (unverified) if one wasn't created via mTLS probe
             if not ssl_context:
```

#### Mutant ID: 70
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_70`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -47,7 +47,7 @@
 
         ssl_context = self._shared_state.ssl_context
         # Detect if the path is actually an absolute URL (for SmartThings).
-        if url_path and url_path.startswith("http"):
+        if url_path and url_path.startswith("XXhttpXX"):
             base_url = ""  # No base URL needed
             # Provide a default ssl_context (unverified) if one wasn't created via mTLS probe
             if not ssl_context:
```

#### Mutant ID: 71
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_71`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -47,7 +47,7 @@
 
         ssl_context = self._shared_state.ssl_context
         # Detect if the path is actually an absolute URL (for SmartThings).
-        if url_path and url_path.startswith("http"):
+        if url_path and url_path.startswith("HTTP"):
             base_url = ""  # No base URL needed
             # Provide a default ssl_context (unverified) if one wasn't created via mTLS probe
             if not ssl_context:
```

#### Mutant ID: 72
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_72`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -48,7 +48,7 @@
         ssl_context = self._shared_state.ssl_context
         # Detect if the path is actually an absolute URL (for SmartThings).
         if url_path and url_path.startswith("http"):
-            base_url = ""  # No base URL needed
+            base_url = None  # No base URL needed
             # Provide a default ssl_context (unverified) if one wasn't created via mTLS probe
             if not ssl_context:
                 ssl_context = await self._create_ssl_context()
```

#### Mutant ID: 73
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_73`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -48,7 +48,7 @@
         ssl_context = self._shared_state.ssl_context
         # Detect if the path is actually an absolute URL (for SmartThings).
         if url_path and url_path.startswith("http"):
-            base_url = ""  # No base URL needed
+            base_url = "XXXX"  # No base URL needed
             # Provide a default ssl_context (unverified) if one wasn't created via mTLS probe
             if not ssl_context:
                 ssl_context = await self._create_ssl_context()
```

#### Mutant ID: 74
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_74`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -50,7 +50,7 @@
         if url_path and url_path.startswith("http"):
             base_url = ""  # No base URL needed
             # Provide a default ssl_context (unverified) if one wasn't created via mTLS probe
-            if not ssl_context:
+            if ssl_context:
                 ssl_context = await self._create_ssl_context()
         else:
             port = self._config.get(CONF_PORT, "8888")
```

#### Mutant ID: 75
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_75`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -51,7 +51,7 @@
             base_url = ""  # No base URL needed
             # Provide a default ssl_context (unverified) if one wasn't created via mTLS probe
             if not ssl_context:
-                ssl_context = await self._create_ssl_context()
+                ssl_context = None
         else:
             port = self._config.get(CONF_PORT, "8888")
             base_url = f"https://{self._ip_address}:{port}"
```

#### Mutant ID: 76
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_76`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
             if not ssl_context:
                 ssl_context = await self._create_ssl_context()
         else:
-            port = self._config.get(CONF_PORT, "8888")
+            port = None
             base_url = f"https://{self._ip_address}:{port}"
 
         full_url = f"{base_url}{url_path}"
```

#### Mutant ID: 77
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_77`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
             if not ssl_context:
                 ssl_context = await self._create_ssl_context()
         else:
-            port = self._config.get(CONF_PORT, "8888")
+            port = self._config.get(None, "8888")
             base_url = f"https://{self._ip_address}:{port}"
 
         full_url = f"{base_url}{url_path}"
```

#### Mutant ID: 78
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_78`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
             if not ssl_context:
                 ssl_context = await self._create_ssl_context()
         else:
-            port = self._config.get(CONF_PORT, "8888")
+            port = self._config.get(CONF_PORT, None)
             base_url = f"https://{self._ip_address}:{port}"
 
         full_url = f"{base_url}{url_path}"
```

#### Mutant ID: 79
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_79`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
             if not ssl_context:
                 ssl_context = await self._create_ssl_context()
         else:
-            port = self._config.get(CONF_PORT, "8888")
+            port = self._config.get("8888")
             base_url = f"https://{self._ip_address}:{port}"
 
         full_url = f"{base_url}{url_path}"
```

#### Mutant ID: 80
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_80`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
             if not ssl_context:
                 ssl_context = await self._create_ssl_context()
         else:
-            port = self._config.get(CONF_PORT, "8888")
+            port = self._config.get(CONF_PORT, )
             base_url = f"https://{self._ip_address}:{port}"
 
         full_url = f"{base_url}{url_path}"
```

#### Mutant ID: 81
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_81`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
             if not ssl_context:
                 ssl_context = await self._create_ssl_context()
         else:
-            port = self._config.get(CONF_PORT, "8888")
+            port = self._config.get(CONF_PORT, "XX8888XX")
             base_url = f"https://{self._ip_address}:{port}"
 
         full_url = f"{base_url}{url_path}"
```

#### Mutant ID: 82
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_82`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -54,7 +54,7 @@
                 ssl_context = await self._create_ssl_context()
         else:
             port = self._config.get(CONF_PORT, "8888")
-            base_url = f"https://{self._ip_address}:{port}"
+            base_url = None
 
         full_url = f"{base_url}{url_path}"
         full_url = self._format_url(full_url)
```

#### Mutant ID: 87
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_87`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -60,7 +60,7 @@
         full_url = self._format_url(full_url)
 
         # If the final URL is plain HTTP (e.g. test mode), don't use SSL
-        if full_url.startswith("http://"):
+        if full_url.startswith("XXhttp://XX"):
             ssl_context = False
 
         try:
```

#### Mutant ID: 88
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_88`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -60,7 +60,7 @@
         full_url = self._format_url(full_url)
 
         # If the final URL is plain HTTP (e.g. test mode), don't use SSL
-        if full_url.startswith("http://"):
+        if full_url.startswith("HTTP://"):
             ssl_context = False
 
         try:
```

#### Mutant ID: 89
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_89`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -61,7 +61,7 @@
 
         # If the final URL is plain HTTP (e.g. test mode), don't use SSL
         if full_url.startswith("http://"):
-            ssl_context = False
+            ssl_context = None
 
         try:
             # Strict Serialization with Lock: ensures that requests are executed one by one
```

#### Mutant ID: 90
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_90`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -61,7 +61,7 @@
 
         # If the final URL is plain HTTP (e.g. test mode), don't use SSL
         if full_url.startswith("http://"):
-            ssl_context = False
+            ssl_context = True
 
         try:
             # Strict Serialization with Lock: ensures that requests are executed one by one
```

#### Mutant ID: 96
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_96`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -74,7 +74,7 @@
                     method,
                     full_url,
                     mask_sensitive_data(data),
-                    self._force_close_connection,
+                    None,
                 )
 
                 session = await self._get_session()
```

#### Mutant ID: 102
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_102`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -74,8 +74,7 @@
                     method,
                     full_url,
                     mask_sensitive_data(data),
-                    self._force_close_connection,
-                )
+                    )
 
                 session = await self._get_session()
                 debug_msg = "%s [aiohttp] Using session ID: %s | SSL Context ID: %s"  # pragma: no mutate
```

#### Mutant ID: 116
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_116`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -83,7 +83,7 @@
 
                 async with session.request(
                     method,
-                    url=full_url,
+                    url=None,
                     headers=req_headers,
                     data=data,
                     ssl=ssl_context,  # type: ignore[arg-type]
```

#### Mutant ID: 118
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_118`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -85,7 +85,7 @@
                     method,
                     url=full_url,
                     headers=req_headers,
-                    data=data,
+                    data=None,
                     ssl=ssl_context,  # type: ignore[arg-type]
                     timeout=aiohttp.ClientTimeout(total=10),
                 ) as response:
```

#### Mutant ID: 119
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_119`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -86,7 +86,7 @@
                     url=full_url,
                     headers=req_headers,
                     data=data,
-                    ssl=ssl_context,  # type: ignore[arg-type]
+                    ssl=None,  # type: ignore[arg-type]
                     timeout=aiohttp.ClientTimeout(total=10),
                 ) as response:
 
```

#### Mutant ID: 122
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_122`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -83,7 +83,6 @@
 
                 async with session.request(
                     method,
-                    url=full_url,
                     headers=req_headers,
                     data=data,
                     ssl=ssl_context,  # type: ignore[arg-type]
```

#### Mutant ID: 124
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_124`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -85,7 +85,6 @@
                     method,
                     url=full_url,
                     headers=req_headers,
-                    data=data,
                     ssl=ssl_context,  # type: ignore[arg-type]
                     timeout=aiohttp.ClientTimeout(total=10),
                 ) as response:
```

#### Mutant ID: 125
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_125`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -86,7 +86,6 @@
                     url=full_url,
                     headers=req_headers,
                     data=data,
-                    ssl=ssl_context,  # type: ignore[arg-type]
                     timeout=aiohttp.ClientTimeout(total=10),
                 ) as response:
 
```

#### Mutant ID: 144
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_144`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -102,7 +102,7 @@
                             response.version.major,
                             response.version.minor,
                         )
-                    self._force_close_connection = False
+                    self._force_close_connection = None
                 else:
                     if not self._force_close_connection and response.version:
                         debug_msg = "%s [aiohttp] Server speaks HTTP/%s.%s. Enforcing 'Connection: close'."  # pragma: no mutate
```

#### Mutant ID: 145
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_145`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -102,7 +102,7 @@
                             response.version.major,
                             response.version.minor,
                         )
-                    self._force_close_connection = False
+                    self._force_close_connection = True
                 else:
                     if not self._force_close_connection and response.version:
                         debug_msg = "%s [aiohttp] Server speaks HTTP/%s.%s. Enforcing 'Connection: close'."  # pragma: no mutate
```

#### Mutant ID: 165
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_165`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -112,7 +112,7 @@
                             response.version.major,
                             getattr(response.version, "minor", 0),
                         )
-                    self._force_close_connection = True
+                    self._force_close_connection = None
 
                 if response.status != 200:
                     if response.status in (401, 403):
```

#### Mutant ID: 166
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_166`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -112,7 +112,7 @@
                             response.version.major,
                             getattr(response.version, "minor", 0),
                         )
-                    self._force_close_connection = True
+                    self._force_close_connection = False
 
                 if response.status != 200:
                     if response.status in (401, 403):
```

#### Mutant ID: 215
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_215`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -162,7 +162,7 @@
                 try:
                     session = await self._get_session()
                     async with session.request(
-                        method,
+                        None,
                         full_url,
                         data=data,
                         headers=req_headers,
```

#### Mutant ID: 216
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_216`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -163,7 +163,7 @@
                     session = await self._get_session()
                     async with session.request(
                         method,
-                        full_url,
+                        None,
                         data=data,
                         headers=req_headers,
                         ssl=ssl_context,  # type: ignore[arg-type]
```

#### Mutant ID: 217
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_217`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -164,7 +164,7 @@
                     async with session.request(
                         method,
                         full_url,
-                        data=data,
+                        data=None,
                         headers=req_headers,
                         ssl=ssl_context,  # type: ignore[arg-type]
                         timeout=aiohttp.ClientTimeout(total=10),
```

#### Mutant ID: 219
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_219`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -166,7 +166,7 @@
                         full_url,
                         data=data,
                         headers=req_headers,
-                        ssl=ssl_context,  # type: ignore[arg-type]
+                        ssl=None,  # type: ignore[arg-type]
                         timeout=aiohttp.ClientTimeout(total=10),
                     ) as response:
                         response_text = await response.text()
```

#### Mutant ID: 220
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_220`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -167,7 +167,7 @@
                         data=data,
                         headers=req_headers,
                         ssl=ssl_context,  # type: ignore[arg-type]
-                        timeout=aiohttp.ClientTimeout(total=10),
+                        timeout=None,
                     ) as response:
                         response_text = await response.text()
                         return response_text, None
```

#### Mutant ID: 221
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_221`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -162,7 +162,6 @@
                 try:
                     session = await self._get_session()
                     async with session.request(
-                        method,
                         full_url,
                         data=data,
                         headers=req_headers,
```

#### Mutant ID: 222
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_222`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -163,7 +163,6 @@
                     session = await self._get_session()
                     async with session.request(
                         method,
-                        full_url,
                         data=data,
                         headers=req_headers,
                         ssl=ssl_context,  # type: ignore[arg-type]
```

#### Mutant ID: 223
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_223`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -164,7 +164,6 @@
                     async with session.request(
                         method,
                         full_url,
-                        data=data,
                         headers=req_headers,
                         ssl=ssl_context,  # type: ignore[arg-type]
                         timeout=aiohttp.ClientTimeout(total=10),
```

#### Mutant ID: 225
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_225`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -166,7 +166,6 @@
                         full_url,
                         data=data,
                         headers=req_headers,
-                        ssl=ssl_context,  # type: ignore[arg-type]
                         timeout=aiohttp.ClientTimeout(total=10),
                     ) as response:
                         response_text = await response.text()
```

#### Mutant ID: 226
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_226`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -167,8 +167,7 @@
                         data=data,
                         headers=req_headers,
                         ssl=ssl_context,  # type: ignore[arg-type]
-                        timeout=aiohttp.ClientTimeout(total=10),
-                    ) as response:
+                        ) as response:
                         response_text = await response.text()
                         return response_text, None
                 except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as retry_exc:
```

#### Mutant ID: 227
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_227`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -167,7 +167,7 @@
                         data=data,
                         headers=req_headers,
                         ssl=ssl_context,  # type: ignore[arg-type]
-                        timeout=aiohttp.ClientTimeout(total=10),
+                        timeout=aiohttp.ClientTimeout(total=None),
                     ) as response:
                         response_text = await response.text()
                         return response_text, None
```

#### Mutant ID: 228
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_228`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -167,7 +167,7 @@
                         data=data,
                         headers=req_headers,
                         ssl=ssl_context,  # type: ignore[arg-type]
-                        timeout=aiohttp.ClientTimeout(total=10),
+                        timeout=aiohttp.ClientTimeout(total=11),
                     ) as response:
                         response_text = await response.text()
                         return response_text, None
```

#### Mutant ID: 229
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_async_execute_request__mutmut_229`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -169,7 +169,7 @@
                         ssl=ssl_context,  # type: ignore[arg-type]
                         timeout=aiohttp.ClientTimeout(total=10),
                     ) as response:
-                        response_text = await response.text()
+                        response_text = None
                         return response_text, None
                 except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as retry_exc:
                     err_msg = "%s [aiohttp] Retry failed even with 'Connection: close': %s"  # pragma: no mutate
```

### ConnectionAiohttp8888._create_ssl_context

#### Mutant ID: 3
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_create_ssl_context__mutmut_3`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -7,7 +7,7 @@
              - If insecure_ssl=False (Cloud default), returns None (aiohttp default strict).
         """
         # Read insecure_ssl. It comes from 'config' passed to __init__.
-        insecure_ssl = self._config.get("insecure_ssl", False)
+        insecure_ssl = self._config.get("insecure_ssl", None)
         has_cert = self._cert_path and os.path.exists(self._cert_path)
 
         if not has_cert and not insecure_ssl:
```

#### Mutant ID: 5
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_create_ssl_context__mutmut_5`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -7,7 +7,7 @@
              - If insecure_ssl=False (Cloud default), returns None (aiohttp default strict).
         """
         # Read insecure_ssl. It comes from 'config' passed to __init__.
-        insecure_ssl = self._config.get("insecure_ssl", False)
+        insecure_ssl = self._config.get("insecure_ssl", )
         has_cert = self._cert_path and os.path.exists(self._cert_path)
 
         if not has_cert and not insecure_ssl:
```

#### Mutant ID: 8
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_create_ssl_context__mutmut_8`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -7,7 +7,7 @@
              - If insecure_ssl=False (Cloud default), returns None (aiohttp default strict).
         """
         # Read insecure_ssl. It comes from 'config' passed to __init__.
-        insecure_ssl = self._config.get("insecure_ssl", False)
+        insecure_ssl = self._config.get("insecure_ssl", True)
         has_cert = self._cert_path and os.path.exists(self._cert_path)
 
         if not has_cert and not insecure_ssl:
```

#### Mutant ID: 11
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_create_ssl_context__mutmut_11`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -8,7 +8,7 @@
         """
         # Read insecure_ssl. It comes from 'config' passed to __init__.
         insecure_ssl = self._config.get("insecure_ssl", False)
-        has_cert = self._cert_path and os.path.exists(self._cert_path)
+        has_cert = self._cert_path and os.path.exists(None)
 
         if not has_cert and not insecure_ssl:
             # Standard Secure Cloud Connection
```

### ConnectionAiohttp8888._format_url

#### Mutant ID: 7
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_7`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -4,7 +4,7 @@
         """
         # Host: Evaluamos explícitamente sin caer en str(None)
         raw_host = self._ip_address or self._params.get(CONF_HOST)
-        host = str(raw_host) if raw_host is not None else ""
+        host = str(raw_host) if raw_host is not None else "XXXX"
         
         token = self._token
         dev_id = None
```

#### Mutant ID: 8
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_8`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -6,7 +6,7 @@
         raw_host = self._ip_address or self._params.get(CONF_HOST)
         host = str(raw_host) if raw_host is not None else ""
         
-        token = self._token
+        token = None
         dev_id = None
         
         if self._controller is not None:
```

#### Mutant ID: 9
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_9`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -7,7 +7,7 @@
         host = str(raw_host) if raw_host is not None else ""
         
         token = self._token
-        dev_id = None
+        dev_id = ""
         
         if self._controller is not None:
             token = self._controller._config.get(CONF_TOKEN, self._token)
```

#### Mutant ID: 11
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_11`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -10,7 +10,7 @@
         dev_id = None
         
         if self._controller is not None:
-            token = self._controller._config.get(CONF_TOKEN, self._token)
+            token = None
             # Falla Rápido: Asumimos que el contrato del controlador expone device_id
             dev_id = self._controller.device_id
 
```

#### Mutant ID: 12
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_12`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -10,7 +10,7 @@
         dev_id = None
         
         if self._controller is not None:
-            token = self._controller._config.get(CONF_TOKEN, self._token)
+            token = self._controller._config.get(None, self._token)
             # Falla Rápido: Asumimos que el contrato del controlador expone device_id
             dev_id = self._controller.device_id
 
```

#### Mutant ID: 13
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_13`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -10,7 +10,7 @@
         dev_id = None
         
         if self._controller is not None:
-            token = self._controller._config.get(CONF_TOKEN, self._token)
+            token = self._controller._config.get(CONF_TOKEN, None)
             # Falla Rápido: Asumimos que el contrato del controlador expone device_id
             dev_id = self._controller.device_id
 
```

#### Mutant ID: 14
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_14`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -10,7 +10,7 @@
         dev_id = None
         
         if self._controller is not None:
-            token = self._controller._config.get(CONF_TOKEN, self._token)
+            token = self._controller._config.get(self._token)
             # Falla Rápido: Asumimos que el contrato del controlador expone device_id
             dev_id = self._controller.device_id
 
```

#### Mutant ID: 15
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_15`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -10,7 +10,7 @@
         dev_id = None
         
         if self._controller is not None:
-            token = self._controller._config.get(CONF_TOKEN, self._token)
+            token = self._controller._config.get(CONF_TOKEN, )
             # Falla Rápido: Asumimos que el contrato del controlador expone device_id
             dev_id = self._controller.device_id
 
```

#### Mutant ID: 22
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_22`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -15,7 +15,7 @@
             dev_id = self._controller.device_id
 
         raw_mac = self._params.get(CONF_MAC)
-        mac = str(raw_mac) if raw_mac is not None else ""
+        mac = str(raw_mac) if raw_mac is not None else "XXXX"
 
         url = format_placeholders(url, token, host, dev_id, mac)
 
```

#### Mutant ID: 25
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_25`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -17,7 +17,7 @@
         raw_mac = self._params.get(CONF_MAC)
         mac = str(raw_mac) if raw_mac is not None else ""
 
-        url = format_placeholders(url, token, host, dev_id, mac)
+        url = format_placeholders(url, None, host, dev_id, mac)
 
         # Manejo de puertos sin falsos positivos de mutación
         if ":8888/" in url:
```

#### Mutant ID: 39
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_39`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
 
         # Manejo de puertos sin falsos positivos de mutación
         if ":8888/" in url:
-            port = str(self._config.get(CONF_PORT, "8888"))
+            port = str(self._config.get(CONF_PORT, None))
             url = url.replace(":8888/", f":{port}/")
 
         # Mutmut odia el `if dict.get(key, False):`. Lo blindamos asertando el tipo booleano.
```

#### Mutant ID: 41
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_41`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
 
         # Manejo de puertos sin falsos positivos de mutación
         if ":8888/" in url:
-            port = str(self._config.get(CONF_PORT, "8888"))
+            port = str(self._config.get(CONF_PORT, ))
             url = url.replace(":8888/", f":{port}/")
 
         # Mutmut odia el `if dict.get(key, False):`. Lo blindamos asertando el tipo booleano.
```

#### Mutant ID: 42
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_42`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
 
         # Manejo de puertos sin falsos positivos de mutación
         if ":8888/" in url:
-            port = str(self._config.get(CONF_PORT, "8888"))
+            port = str(self._config.get(CONF_PORT, "XX8888XX"))
             url = url.replace(":8888/", f":{port}/")
 
         # Mutmut odia el `if dict.get(key, False):`. Lo blindamos asertando el tipo booleano.
```

#### Mutant ID: 51
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_51`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -25,7 +25,7 @@
             url = url.replace(":8888/", f":{port}/")
 
         # Mutmut odia el `if dict.get(key, False):`. Lo blindamos asertando el tipo booleano.
-        if bool(self._config.get("use_http", False)) is True:
+        if bool(self._config.get("use_http", None)) is True:
             url = url.replace("https://", "http://")
 
         return url
```

#### Mutant ID: 53
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_53`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -25,7 +25,7 @@
             url = url.replace(":8888/", f":{port}/")
 
         # Mutmut odia el `if dict.get(key, False):`. Lo blindamos asertando el tipo booleano.
-        if bool(self._config.get("use_http", False)) is True:
+        if bool(self._config.get("use_http", )) is True:
             url = url.replace("https://", "http://")
 
         return url
```

#### Mutant ID: 56
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_format_url__mutmut_56`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -25,7 +25,7 @@
             url = url.replace(":8888/", f":{port}/")
 
         # Mutmut odia el `if dict.get(key, False):`. Lo blindamos asertando el tipo booleano.
-        if bool(self._config.get("use_http", False)) is True:
+        if bool(self._config.get("use_http", True)) is True:
             url = url.replace("https://", "http://")
 
         return url
```

### ConnectionAiohttp8888._get_session

#### Mutant ID: 3
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_get_session__mutmut_3`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -7,7 +7,7 @@
         if self._keep_alive and self._session is not None:
             return self._session
 
-        if self._keep_alive and self._session is None:
+        if self._keep_alive or self._session is None:
             # Defense-in-depth: the shared session was not injected (e.g., during
             # config flow discovery). Fall through and create a temporary local session
             # instead of returning None, which would crash the caller.
```

#### Mutant ID: 4
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_get_session__mutmut_4`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -7,7 +7,7 @@
         if self._keep_alive and self._session is not None:
             return self._session
 
-        if self._keep_alive and self._session is None:
+        if self._keep_alive and self._session is not None:
             # Defense-in-depth: the shared session was not injected (e.g., during
             # config flow discovery). Fall through and create a temporary local session
             # instead of returning None, which would crash the caller.
```

#### Mutant ID: 10
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_get_session__mutmut_10`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -17,7 +17,7 @@
         local_session = self._shared_state.local_session
         
         # Determine if we need a new session
-        needs_new_session = False
+        needs_new_session = None
         if local_session is None:
             needs_new_session = True
         elif local_session.closed is True: # Estricto
```

#### Mutant ID: 41
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_get_session__mutmut_41`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -32,7 +32,7 @@
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, limit=1)
             else:
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, ssl=ssl_context, limit=1)  # type: ignore[arg-type]
-            timeout = aiohttp.ClientTimeout(total=30, connect=10)
+            timeout = None
             local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
             self._shared_state.local_session = local_session
             debug_msg = "%s [aiohttp] Created new local session (ID: %s) with connector (ID: %s)."  # pragma: no mutate
```

#### Mutant ID: 42
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_get_session__mutmut_42`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -32,7 +32,7 @@
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, limit=1)
             else:
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, ssl=ssl_context, limit=1)  # type: ignore[arg-type]
-            timeout = aiohttp.ClientTimeout(total=30, connect=10)
+            timeout = aiohttp.ClientTimeout(total=None, connect=10)
             local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
             self._shared_state.local_session = local_session
             debug_msg = "%s [aiohttp] Created new local session (ID: %s) with connector (ID: %s)."  # pragma: no mutate
```

#### Mutant ID: 43
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_get_session__mutmut_43`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -32,7 +32,7 @@
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, limit=1)
             else:
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, ssl=ssl_context, limit=1)  # type: ignore[arg-type]
-            timeout = aiohttp.ClientTimeout(total=30, connect=10)
+            timeout = aiohttp.ClientTimeout(total=30, connect=None)
             local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
             self._shared_state.local_session = local_session
             debug_msg = "%s [aiohttp] Created new local session (ID: %s) with connector (ID: %s)."  # pragma: no mutate
```

#### Mutant ID: 44
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_get_session__mutmut_44`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -32,7 +32,7 @@
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, limit=1)
             else:
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, ssl=ssl_context, limit=1)  # type: ignore[arg-type]
-            timeout = aiohttp.ClientTimeout(total=30, connect=10)
+            timeout = aiohttp.ClientTimeout(connect=10)
             local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
             self._shared_state.local_session = local_session
             debug_msg = "%s [aiohttp] Created new local session (ID: %s) with connector (ID: %s)."  # pragma: no mutate
```

#### Mutant ID: 45
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_get_session__mutmut_45`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -32,7 +32,7 @@
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, limit=1)
             else:
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, ssl=ssl_context, limit=1)  # type: ignore[arg-type]
-            timeout = aiohttp.ClientTimeout(total=30, connect=10)
+            timeout = aiohttp.ClientTimeout(total=30, )
             local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
             self._shared_state.local_session = local_session
             debug_msg = "%s [aiohttp] Created new local session (ID: %s) with connector (ID: %s)."  # pragma: no mutate
```

#### Mutant ID: 46
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_get_session__mutmut_46`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -32,7 +32,7 @@
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, limit=1)
             else:
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, ssl=ssl_context, limit=1)  # type: ignore[arg-type]
-            timeout = aiohttp.ClientTimeout(total=30, connect=10)
+            timeout = aiohttp.ClientTimeout(total=31, connect=10)
             local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
             self._shared_state.local_session = local_session
             debug_msg = "%s [aiohttp] Created new local session (ID: %s) with connector (ID: %s)."  # pragma: no mutate
```

#### Mutant ID: 47
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_get_session__mutmut_47`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -32,7 +32,7 @@
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, limit=1)
             else:
                 connector = aiohttp.TCPConnector(keepalive_timeout=75, ssl=ssl_context, limit=1)  # type: ignore[arg-type]
-            timeout = aiohttp.ClientTimeout(total=30, connect=10)
+            timeout = aiohttp.ClientTimeout(total=30, connect=11)
             local_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
             self._shared_state.local_session = local_session
             debug_msg = "%s [aiohttp] Created new local session (ID: %s) with connector (ID: %s)."  # pragma: no mutate
```

### ConnectionAiohttp8888._resolve_cert_path

#### Mutant ID: 2
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_resolve_cert_path__mutmut_2`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -2,4 +2,4 @@
         """Resolve the full path to the certificate file."""
         from .helpers import resolve_cert_path
 
-        return resolve_cert_path(cert_file, os.path.dirname(__file__), self._hass)
+        return resolve_cert_path(cert_file, None, self._hass)
```

#### Mutant ID: 3
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_resolve_cert_path__mutmut_3`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -2,4 +2,4 @@
         """Resolve the full path to the certificate file."""
         from .helpers import resolve_cert_path
 
-        return resolve_cert_path(cert_file, os.path.dirname(__file__), self._hass)
+        return resolve_cert_path(cert_file, os.path.dirname(__file__), None)
```

#### Mutant ID: 5
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_resolve_cert_path__mutmut_5`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -2,4 +2,4 @@
         """Resolve the full path to the certificate file."""
         from .helpers import resolve_cert_path
 
-        return resolve_cert_path(cert_file, os.path.dirname(__file__), self._hass)
+        return resolve_cert_path(cert_file, self._hass)
```

#### Mutant ID: 6
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_resolve_cert_path__mutmut_6`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -2,4 +2,4 @@
         """Resolve the full path to the certificate file."""
         from .helpers import resolve_cert_path
 
-        return resolve_cert_path(cert_file, os.path.dirname(__file__), self._hass)
+        return resolve_cert_path(cert_file, os.path.dirname(__file__), )
```

### ConnectionAiohttp8888._try_connection

#### Mutant ID: 1
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_1`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -13,7 +13,7 @@
             if self._shared_state.initialized:
                 return None
 
-            current_token = self._token
+            current_token = None
             if self._controller:
                 current_token = self._controller._config.get(  # pylint: disable=protected-access
                     CONF_TOKEN, self._token
```

#### Mutant ID: 2
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_2`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -15,9 +15,7 @@
 
             current_token = self._token
             if self._controller:
-                current_token = self._controller._config.get(  # pylint: disable=protected-access
-                    CONF_TOKEN, self._token
-                )
+                current_token = None
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
```

#### Mutant ID: 3
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_3`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -16,7 +16,7 @@
             current_token = self._token
             if self._controller:
                 current_token = self._controller._config.get(  # pylint: disable=protected-access
-                    CONF_TOKEN, self._token
+                    None, self._token
                 )
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
```

#### Mutant ID: 4
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_4`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -16,7 +16,7 @@
             current_token = self._token
             if self._controller:
                 current_token = self._controller._config.get(  # pylint: disable=protected-access
-                    CONF_TOKEN, self._token
+                    CONF_TOKEN, None
                 )
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
```

#### Mutant ID: 5
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_5`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -16,7 +16,7 @@
             current_token = self._token
             if self._controller:
                 current_token = self._controller._config.get(  # pylint: disable=protected-access
-                    CONF_TOKEN, self._token
+                    self._token
                 )
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
```

#### Mutant ID: 6
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_6`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -16,8 +16,7 @@
             current_token = self._token
             if self._controller:
                 current_token = self._controller._config.get(  # pylint: disable=protected-access
-                    CONF_TOKEN, self._token
-                )
+                    CONF_TOKEN, )
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
```

#### Mutant ID: 7
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_7`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -18,7 +18,7 @@
                 current_token = self._controller._config.get(  # pylint: disable=protected-access
                     CONF_TOKEN, self._token
                 )
-            probe_headers = {"Authorization": f"Bearer {current_token}"}
+            probe_headers = None
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
             if not self._config.get("use_http", False):
```

#### Mutant ID: 8
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_8`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -18,7 +18,7 @@
                 current_token = self._controller._config.get(  # pylint: disable=protected-access
                     CONF_TOKEN, self._token
                 )
-            probe_headers = {"Authorization": f"Bearer {current_token}"}
+            probe_headers = {"XXAuthorizationXX": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
             if not self._config.get("use_http", False):
```

#### Mutant ID: 9
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_9`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -18,7 +18,7 @@
                 current_token = self._controller._config.get(  # pylint: disable=protected-access
                     CONF_TOKEN, self._token
                 )
-            probe_headers = {"Authorization": f"Bearer {current_token}"}
+            probe_headers = {"authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
             if not self._config.get("use_http", False):
```

#### Mutant ID: 10
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_10`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -18,7 +18,7 @@
                 current_token = self._controller._config.get(  # pylint: disable=protected-access
                     CONF_TOKEN, self._token
                 )
-            probe_headers = {"Authorization": f"Bearer {current_token}"}
+            probe_headers = {"AUTHORIZATION": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
             if not self._config.get("use_http", False):
```

#### Mutant ID: 11
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_11`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
-            if not self._config.get("use_http", False):
+            if self._config.get("use_http", False):
                 if self._shared_state.ssl_context is None:
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
```

#### Mutant ID: 12
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_12`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
-            if not self._config.get("use_http", False):
+            if not self._config.get(None, False):
                 if self._shared_state.ssl_context is None:
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
```

#### Mutant ID: 13
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_13`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
-            if not self._config.get("use_http", False):
+            if not self._config.get("use_http", None):
                 if self._shared_state.ssl_context is None:
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
```

#### Mutant ID: 14
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_14`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
-            if not self._config.get("use_http", False):
+            if not self._config.get(False):
                 if self._shared_state.ssl_context is None:
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
```

#### Mutant ID: 15
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_15`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
-            if not self._config.get("use_http", False):
+            if not self._config.get("use_http", ):
                 if self._shared_state.ssl_context is None:
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
```

#### Mutant ID: 16
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_16`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
-            if not self._config.get("use_http", False):
+            if not self._config.get("XXuse_httpXX", False):
                 if self._shared_state.ssl_context is None:
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
```

#### Mutant ID: 17
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_17`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
-            if not self._config.get("use_http", False):
+            if not self._config.get("USE_HTTP", False):
                 if self._shared_state.ssl_context is None:
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
```

#### Mutant ID: 18
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_18`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -21,7 +21,7 @@
             probe_headers = {"Authorization": f"Bearer {current_token}"}
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
-            if not self._config.get("use_http", False):
+            if not self._config.get("use_http", True):
                 if self._shared_state.ssl_context is None:
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
```

#### Mutant ID: 19
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_19`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -22,7 +22,7 @@
 
             # Use the shared state's SSL context, skip for plain HTTP test mode
             if not self._config.get("use_http", False):
-                if self._shared_state.ssl_context is None:
+                if self._shared_state.ssl_context is not None:
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
             ssl_ctx = self._shared_state.ssl_context
```

#### Mutant ID: 20
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_20`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -23,7 +23,7 @@
             # Use the shared state's SSL context, skip for plain HTTP test mode
             if not self._config.get("use_http", False):
                 if self._shared_state.ssl_context is None:
-                    self._shared_state.ssl_context = await self._create_ssl_context()
+                    self._shared_state.ssl_context = None
 
             ssl_ctx = self._shared_state.ssl_context
             if ssl_ctx is None:
```

#### Mutant ID: 21
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_21`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -25,7 +25,7 @@
                 if self._shared_state.ssl_context is None:
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
-            ssl_ctx = self._shared_state.ssl_context
+            ssl_ctx = None
             if ssl_ctx is None:
                 # Logic for "insecure" / no-cert connection
                 ssl_ctx = False
```

#### Mutant ID: 22
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_22`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -26,7 +26,7 @@
                     self._shared_state.ssl_context = await self._create_ssl_context()
 
             ssl_ctx = self._shared_state.ssl_context
-            if ssl_ctx is None:
+            if ssl_ctx is not None:
                 # Logic for "insecure" / no-cert connection
                 ssl_ctx = False
 
```

#### Mutant ID: 23
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_23`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -28,7 +28,7 @@
             ssl_ctx = self._shared_state.ssl_context
             if ssl_ctx is None:
                 # Logic for "insecure" / no-cert connection
-                ssl_ctx = False
+                ssl_ctx = None
 
             try:
                 debug_msg = "%s [aiohttp_probe] Probing connection..."  # pragma: no mutate
```

#### Mutant ID: 24
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_24`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -28,7 +28,7 @@
             ssl_ctx = self._shared_state.ssl_context
             if ssl_ctx is None:
                 # Logic for "insecure" / no-cert connection
-                ssl_ctx = False
+                ssl_ctx = True
 
             try:
                 debug_msg = "%s [aiohttp_probe] Probing connection..."  # pragma: no mutate
```

#### Mutant ID: 35
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_35`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = None
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 36
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_36`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "XXhttpXX" if self._config.get("use_http", False) else "https"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 37
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_37`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "HTTP" if self._config.get("use_http", False) else "https"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 38
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_38`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "http" if self._config.get(None, False) else "https"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 39
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_39`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "http" if self._config.get("use_http", None) else "https"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 40
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_40`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "http" if self._config.get(False) else "https"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 41
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_41`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "http" if self._config.get("use_http", ) else "https"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 42
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_42`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "http" if self._config.get("XXuse_httpXX", False) else "https"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 43
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_43`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "http" if self._config.get("USE_HTTP", False) else "https"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 44
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_44`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "http" if self._config.get("use_http", True) else "https"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 45
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_45`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "http" if self._config.get("use_http", False) else "XXhttpsXX"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 46
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_46`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
 
                 # Generalize Probe URL
                 port = self._config.get(CONF_PORT, "8888")
-                protocol = "http" if self._config.get("use_http", False) else "https"
+                protocol = "http" if self._config.get("use_http", False) else "HTTPS"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
```

#### Mutant ID: 48
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_48`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -40,8 +40,7 @@
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
-                    and self._params.get("url")
-                    and str(self._params.get("url")).startswith("http")
+                    and self._params.get("url") or str(self._params.get("url")).startswith("http")
                 ):
                     probe_url = str(self._params.get("url"))
                     debug_msg = "%s [aiohttp_probe] Detected absolute URL, probing: %s"  # pragma: no mutate
```

#### Mutant ID: 49
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_49`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -39,8 +39,7 @@
                 protocol = "http" if self._config.get("use_http", False) else "https"
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
-                    self._params
-                    and self._params.get("url")
+                    self._params or self._params.get("url")
                     and str(self._params.get("url")).startswith("http")
                 ):
                     probe_url = str(self._params.get("url"))
```

#### Mutant ID: 50
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_50`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -40,7 +40,7 @@
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
-                    and self._params.get("url")
+                    and self._params.get(None)
                     and str(self._params.get("url")).startswith("http")
                 ):
                     probe_url = str(self._params.get("url"))
```

#### Mutant ID: 51
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_51`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -40,7 +40,7 @@
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
-                    and self._params.get("url")
+                    and self._params.get("XXurlXX")
                     and str(self._params.get("url")).startswith("http")
                 ):
                     probe_url = str(self._params.get("url"))
```

#### Mutant ID: 52
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_52`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -40,7 +40,7 @@
                 probe_url = f"{protocol}://{self._ip_address}:{port}/devices"
                 if (
                     self._params
-                    and self._params.get("url")
+                    and self._params.get("URL")
                     and str(self._params.get("url")).startswith("http")
                 ):
                     probe_url = str(self._params.get("url"))
```

#### Mutant ID: 53
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_53`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -41,7 +41,7 @@
                 if (
                     self._params
                     and self._params.get("url")
-                    and str(self._params.get("url")).startswith("http")
+                    and str(self._params.get("url")).startswith(None)
                 ):
                     probe_url = str(self._params.get("url"))
                     debug_msg = "%s [aiohttp_probe] Detected absolute URL, probing: %s"  # pragma: no mutate
```

#### Mutant ID: 54
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_54`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -41,7 +41,7 @@
                 if (
                     self._params
                     and self._params.get("url")
-                    and str(self._params.get("url")).startswith("http")
+                    and str(None).startswith("http")
                 ):
                     probe_url = str(self._params.get("url"))
                     debug_msg = "%s [aiohttp_probe] Detected absolute URL, probing: %s"  # pragma: no mutate
```

#### Mutant ID: 55
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_55`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -41,7 +41,7 @@
                 if (
                     self._params
                     and self._params.get("url")
-                    and str(self._params.get("url")).startswith("http")
+                    and str(self._params.get(None)).startswith("http")
                 ):
                     probe_url = str(self._params.get("url"))
                     debug_msg = "%s [aiohttp_probe] Detected absolute URL, probing: %s"  # pragma: no mutate
```

#### Mutant ID: 56
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_56`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -41,7 +41,7 @@
                 if (
                     self._params
                     and self._params.get("url")
-                    and str(self._params.get("url")).startswith("http")
+                    and str(self._params.get("XXurlXX")).startswith("http")
                 ):
                     probe_url = str(self._params.get("url"))
                     debug_msg = "%s [aiohttp_probe] Detected absolute URL, probing: %s"  # pragma: no mutate
```

#### Mutant ID: 57
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_57`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -41,7 +41,7 @@
                 if (
                     self._params
                     and self._params.get("url")
-                    and str(self._params.get("url")).startswith("http")
+                    and str(self._params.get("URL")).startswith("http")
                 ):
                     probe_url = str(self._params.get("url"))
                     debug_msg = "%s [aiohttp_probe] Detected absolute URL, probing: %s"  # pragma: no mutate
```

#### Mutant ID: 58
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_58`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -41,7 +41,7 @@
                 if (
                     self._params
                     and self._params.get("url")
-                    and str(self._params.get("url")).startswith("http")
+                    and str(self._params.get("url")).startswith("XXhttpXX")
                 ):
                     probe_url = str(self._params.get("url"))
                     debug_msg = "%s [aiohttp_probe] Detected absolute URL, probing: %s"  # pragma: no mutate
```

#### Mutant ID: 59
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_59`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -41,7 +41,7 @@
                 if (
                     self._params
                     and self._params.get("url")
-                    and str(self._params.get("url")).startswith("http")
+                    and str(self._params.get("url")).startswith("HTTP")
                 ):
                     probe_url = str(self._params.get("url"))
                     debug_msg = "%s [aiohttp_probe] Detected absolute URL, probing: %s"  # pragma: no mutate
```

#### Mutant ID: 73
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_73`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
                 # CRITICAL FIX: Do NOT access self._session directly — it may be None
                 # when keep_alive=False. Always go through _get_session() which handles
                 # both a HA-shared session and a locally-created one.
-                test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
+                test_ssl_ctx = None
                 probe_session = await self._get_session()
                 async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
```

#### Mutant ID: 74
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_74`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
                 # CRITICAL FIX: Do NOT access self._session directly — it may be None
                 # when keep_alive=False. Always go through _get_session() which handles
                 # both a HA-shared session and a locally-created one.
-                test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
+                test_ssl_ctx = True if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
                 async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
```

#### Mutant ID: 75
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_75`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
                 # CRITICAL FIX: Do NOT access self._session directly — it may be None
                 # when keep_alive=False. Always go through _get_session() which handles
                 # both a HA-shared session and a locally-created one.
-                test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
+                test_ssl_ctx = False if protocol != "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
                 async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
```

#### Mutant ID: 76
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_76`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
                 # CRITICAL FIX: Do NOT access self._session directly — it may be None
                 # when keep_alive=False. Always go through _get_session() which handles
                 # both a HA-shared session and a locally-created one.
-                test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
+                test_ssl_ctx = False if protocol == "XXhttpXX" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
                 async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
```

#### Mutant ID: 77
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_77`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -53,7 +53,7 @@
                 # CRITICAL FIX: Do NOT access self._session directly — it may be None
                 # when keep_alive=False. Always go through _get_session() which handles
                 # both a HA-shared session and a locally-created one.
-                test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
+                test_ssl_ctx = False if protocol == "HTTP" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
                 async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
```

#### Mutant ID: 79
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_79`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -55,7 +55,7 @@
                 # both a HA-shared session and a locally-created one.
                 test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
-                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
+                async with probe_session.request(None, probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
```

#### Mutant ID: 80
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_80`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -55,7 +55,7 @@
                 # both a HA-shared session and a locally-created one.
                 test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
-                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
+                async with probe_session.request("GET", None, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
```

#### Mutant ID: 81
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_81`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -55,7 +55,7 @@
                 # both a HA-shared session and a locally-created one.
                 test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
-                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
+                async with probe_session.request("GET", probe_url, headers=None, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
```

#### Mutant ID: 82
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_82`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -55,7 +55,7 @@
                 # both a HA-shared session and a locally-created one.
                 test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
-                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
+                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=None, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
```

#### Mutant ID: 84
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_84`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -55,7 +55,7 @@
                 # both a HA-shared session and a locally-created one.
                 test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
-                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
+                async with probe_session.request(probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
```

#### Mutant ID: 85
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_85`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -55,7 +55,7 @@
                 # both a HA-shared session and a locally-created one.
                 test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
-                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
+                async with probe_session.request("GET", headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
```

#### Mutant ID: 86
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_86`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -55,7 +55,7 @@
                 # both a HA-shared session and a locally-created one.
                 test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
-                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
+                async with probe_session.request("GET", probe_url, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
```

#### Mutant ID: 87
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_87`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -55,7 +55,7 @@
                 # both a HA-shared session and a locally-created one.
                 test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
-                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
+                async with probe_session.request("GET", probe_url, headers=probe_headers, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
```

#### Mutant ID: 89
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_89`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -55,7 +55,7 @@
                 # both a HA-shared session and a locally-created one.
                 test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
-                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
+                async with probe_session.request("XXGETXX", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
```

#### Mutant ID: 90
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_90`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -55,7 +55,7 @@
                 # both a HA-shared session and a locally-created one.
                 test_ssl_ctx = False if protocol == "http" else self._shared_state.ssl_context
                 probe_session = await self._get_session()
-                async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
+                async with probe_session.request("get", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
```

#### Mutant ID: 100
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_100`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -58,7 +58,7 @@
                 async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
-                    if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
+                    if response.status in (200, 401, 404, 405):  # Added 405 for Method Not Allowed
                         # Attempt to log the negotiated TLS version
                         try:
                             transport = (
```

#### Mutant ID: 101
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_101`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -58,7 +58,7 @@
                 async with probe_session.request("GET", probe_url, headers=probe_headers, ssl=test_ssl_ctx, timeout=aiohttp.ClientTimeout(total=10, sock_read=5)) as response:  # type: ignore[arg-type]
 
 
-                    if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
+                    if response.status in (200, 401, 403, 406):  # Added 405 for Method Not Allowed
                         # Attempt to log the negotiated TLS version
                         try:
                             transport = (
```

#### Mutant ID: 102
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_102`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -61,9 +61,7 @@
                     if response.status in (200, 401, 403, 405):  # Added 405 for Method Not Allowed
                         # Attempt to log the negotiated TLS version
                         try:
-                            transport = (
-                                response.connection.transport if response.connection else None
-                            )
+                            transport = None
                             ssl_obj = transport.get_extra_info("ssl_object") if transport else None
                             negotiated_tls = ssl_obj.version() if ssl_obj else "Unknown"
                             info_msg = "%s [aiohttp] Connection successful. Status: %s. Negotiated TLS: %s"  # pragma: no mutate
```

#### Mutant ID: 133
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁ_try_connection__mutmut_133`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -82,7 +82,7 @@
                         return None
                     else:
                         exc_msg = f"Unexpected probe response: {response.status}"  # pragma: no mutate
-                        raise CannotConnect(exc_msg)
+                        raise CannotConnect(None)
 
             except aiohttp.ClientConnectorError as e:
                 # Log as warning (not error) because it's expected when AC is offline.
```

### ConnectionAiohttp8888.async_execute

#### Mutant ID: 1
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_1`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -5,7 +5,7 @@
         data: Any,
         headers: dict[str, str] | None,  # Main command's headers
         device_state: dict[str, Any] | None = None,  # Pass device state for conditions
-        _is_probe: bool = False,
+        _is_probe: bool = True,
         _is_poll: bool = False,
     ) -> tuple[str | None, dict[str, Any] | None]:
         """
```

#### Mutant ID: 2
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_2`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -6,7 +6,7 @@
         headers: dict[str, str] | None,  # Main command's headers
         device_state: dict[str, Any] | None = None,  # Pass device state for conditions
         _is_probe: bool = False,
-        _is_poll: bool = False,
+        _is_poll: bool = True,
     ) -> tuple[str | None, dict[str, Any] | None]:
         """
         Orchestrates the execution of commands, including embedded ones.
```

#### Mutant ID: 3
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_3`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -12,7 +12,7 @@
         Orchestrates the execution of commands, including embedded ones.
         """
         # Resolve variables for placeholder replacement early for embedded logging
-        raw_host = self._ip_address or self._params.get(CONF_HOST)
+        raw_host = None
         host = str(raw_host) if raw_host is not None else ""
         
         token = self._token
```

#### Mutant ID: 4
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_4`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -12,7 +12,7 @@
         Orchestrates the execution of commands, including embedded ones.
         """
         # Resolve variables for placeholder replacement early for embedded logging
-        raw_host = self._ip_address or self._params.get(CONF_HOST)
+        raw_host = self._ip_address and self._params.get(CONF_HOST)
         host = str(raw_host) if raw_host is not None else ""
         
         token = self._token
```

#### Mutant ID: 5
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_5`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -12,7 +12,7 @@
         Orchestrates the execution of commands, including embedded ones.
         """
         # Resolve variables for placeholder replacement early for embedded logging
-        raw_host = self._ip_address or self._params.get(CONF_HOST)
+        raw_host = self._ip_address or self._params.get(None)
         host = str(raw_host) if raw_host is not None else ""
         
         token = self._token
```

#### Mutant ID: 6
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_6`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -13,7 +13,7 @@
         """
         # Resolve variables for placeholder replacement early for embedded logging
         raw_host = self._ip_address or self._params.get(CONF_HOST)
-        host = str(raw_host) if raw_host is not None else ""
+        host = None
         
         token = self._token
         dev_id = None
```

#### Mutant ID: 7
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_7`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -13,7 +13,7 @@
         """
         # Resolve variables for placeholder replacement early for embedded logging
         raw_host = self._ip_address or self._params.get(CONF_HOST)
-        host = str(raw_host) if raw_host is not None else ""
+        host = str(None) if raw_host is not None else ""
         
         token = self._token
         dev_id = None
```

#### Mutant ID: 8
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_8`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -13,7 +13,7 @@
         """
         # Resolve variables for placeholder replacement early for embedded logging
         raw_host = self._ip_address or self._params.get(CONF_HOST)
-        host = str(raw_host) if raw_host is not None else ""
+        host = str(raw_host) if raw_host is None else ""
         
         token = self._token
         dev_id = None
```

#### Mutant ID: 9
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_9`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -13,7 +13,7 @@
         """
         # Resolve variables for placeholder replacement early for embedded logging
         raw_host = self._ip_address or self._params.get(CONF_HOST)
-        host = str(raw_host) if raw_host is not None else ""
+        host = str(raw_host) if raw_host is not None else "XXXX"
         
         token = self._token
         dev_id = None
```

#### Mutant ID: 10
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_10`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -15,7 +15,7 @@
         raw_host = self._ip_address or self._params.get(CONF_HOST)
         host = str(raw_host) if raw_host is not None else ""
         
-        token = self._token
+        token = None
         dev_id = None
         
         if self._controller is not None:
```

#### Mutant ID: 11
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_11`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -16,7 +16,7 @@
         host = str(raw_host) if raw_host is not None else ""
         
         token = self._token
-        dev_id = None
+        dev_id = ""
         
         if self._controller is not None:
             token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
```

#### Mutant ID: 13
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_13`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -19,7 +19,7 @@
         dev_id = None
         
         if self._controller is not None:
-            token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
+            token = None  # pylint: disable=protected-access
             dev_id = self._controller.device_id
 
         raw_mac = self._params.get(CONF_MAC)
```

#### Mutant ID: 14
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_14`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -19,7 +19,7 @@
         dev_id = None
         
         if self._controller is not None:
-            token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
+            token = self._controller._config.get(None, self._token)  # pylint: disable=protected-access
             dev_id = self._controller.device_id
 
         raw_mac = self._params.get(CONF_MAC)
```

#### Mutant ID: 15
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_15`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -19,7 +19,7 @@
         dev_id = None
         
         if self._controller is not None:
-            token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
+            token = self._controller._config.get(CONF_TOKEN, None)  # pylint: disable=protected-access
             dev_id = self._controller.device_id
 
         raw_mac = self._params.get(CONF_MAC)
```

#### Mutant ID: 16
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_16`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -19,7 +19,7 @@
         dev_id = None
         
         if self._controller is not None:
-            token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
+            token = self._controller._config.get(self._token)  # pylint: disable=protected-access
             dev_id = self._controller.device_id
 
         raw_mac = self._params.get(CONF_MAC)
```

#### Mutant ID: 17
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_17`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -19,7 +19,7 @@
         dev_id = None
         
         if self._controller is not None:
-            token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
+            token = self._controller._config.get(CONF_TOKEN, )  # pylint: disable=protected-access
             dev_id = self._controller.device_id
 
         raw_mac = self._params.get(CONF_MAC)
```

#### Mutant ID: 18
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_18`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -20,7 +20,7 @@
         
         if self._controller is not None:
             token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
-            dev_id = self._controller.device_id
+            dev_id = None
 
         raw_mac = self._params.get(CONF_MAC)
         mac = str(raw_mac) if raw_mac is not None else ""
```

#### Mutant ID: 19
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_19`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -22,7 +22,7 @@
             token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
             dev_id = self._controller.device_id
 
-        raw_mac = self._params.get(CONF_MAC)
+        raw_mac = None
         mac = str(raw_mac) if raw_mac is not None else ""
 
         # Ensure initialization before any execution
```

#### Mutant ID: 20
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_20`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -22,7 +22,7 @@
             token = self._controller._config.get(CONF_TOKEN, self._token)  # pylint: disable=protected-access
             dev_id = self._controller.device_id
 
-        raw_mac = self._params.get(CONF_MAC)
+        raw_mac = self._params.get(None)
         mac = str(raw_mac) if raw_mac is not None else ""
 
         # Ensure initialization before any execution
```

#### Mutant ID: 21
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_21`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -23,7 +23,7 @@
             dev_id = self._controller.device_id
 
         raw_mac = self._params.get(CONF_MAC)
-        mac = str(raw_mac) if raw_mac is not None else ""
+        mac = None
 
         # Ensure initialization before any execution
         probe_response_text = await self._try_connection()
```

#### Mutant ID: 22
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_22`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -23,7 +23,7 @@
             dev_id = self._controller.device_id
 
         raw_mac = self._params.get(CONF_MAC)
-        mac = str(raw_mac) if raw_mac is not None else ""
+        mac = str(None) if raw_mac is not None else ""
 
         # Ensure initialization before any execution
         probe_response_text = await self._try_connection()
```

#### Mutant ID: 23
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_23`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -23,7 +23,7 @@
             dev_id = self._controller.device_id
 
         raw_mac = self._params.get(CONF_MAC)
-        mac = str(raw_mac) if raw_mac is not None else ""
+        mac = str(raw_mac) if raw_mac is None else ""
 
         # Ensure initialization before any execution
         probe_response_text = await self._try_connection()
```

#### Mutant ID: 24
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_24`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -23,7 +23,7 @@
             dev_id = self._controller.device_id
 
         raw_mac = self._params.get(CONF_MAC)
-        mac = str(raw_mac) if raw_mac is not None else ""
+        mac = str(raw_mac) if raw_mac is not None else "XXXX"
 
         # Ensure initialization before any execution
         probe_response_text = await self._try_connection()
```

#### Mutant ID: 25
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_25`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -26,7 +26,7 @@
         mac = str(raw_mac) if raw_mac is not None else ""
 
         # Ensure initialization before any execution
-        probe_response_text = await self._try_connection()
+        probe_response_text = None
 
         if self._embedded_command is not None:
             debug_msg = "%s [async_execute] Found embedded command."  # pragma: no mutate
```

#### Mutant ID: 71
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_71`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -48,7 +48,7 @@
                         
                         if embedded_template is not None:
                             # Patrón seguro para Template (soporta render síncrono y asíncrono)
-                            async_render_func = getattr(embedded_template, "async_render", None)
+                            async_render_func = None
                             if callable(async_render_func):
                                 embedded_params_str = async_render_func()
                             else:
```

#### Mutant ID: 72
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_72`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -48,7 +48,7 @@
                         
                         if embedded_template is not None:
                             # Patrón seguro para Template (soporta render síncrono y asíncrono)
-                            async_render_func = getattr(embedded_template, "async_render", None)
+                            async_render_func = getattr(None, "async_render", None)
                             if callable(async_render_func):
                                 embedded_params_str = async_render_func()
                             else:
```

#### Mutant ID: 73
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_73`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -48,7 +48,7 @@
                         
                         if embedded_template is not None:
                             # Patrón seguro para Template (soporta render síncrono y asíncrono)
-                            async_render_func = getattr(embedded_template, "async_render", None)
+                            async_render_func = getattr(embedded_template, None, None)
                             if callable(async_render_func):
                                 embedded_params_str = async_render_func()
                             else:
```

#### Mutant ID: 74
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_74`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -48,7 +48,7 @@
                         
                         if embedded_template is not None:
                             # Patrón seguro para Template (soporta render síncrono y asíncrono)
-                            async_render_func = getattr(embedded_template, "async_render", None)
+                            async_render_func = getattr("async_render", None)
                             if callable(async_render_func):
                                 embedded_params_str = async_render_func()
                             else:
```

#### Mutant ID: 75
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_75`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -48,7 +48,7 @@
                         
                         if embedded_template is not None:
                             # Patrón seguro para Template (soporta render síncrono y asíncrono)
-                            async_render_func = getattr(embedded_template, "async_render", None)
+                            async_render_func = getattr(embedded_template, None)
                             if callable(async_render_func):
                                 embedded_params_str = async_render_func()
                             else:
```

#### Mutant ID: 76
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_76`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -48,7 +48,7 @@
                         
                         if embedded_template is not None:
                             # Patrón seguro para Template (soporta render síncrono y asíncrono)
-                            async_render_func = getattr(embedded_template, "async_render", None)
+                            async_render_func = getattr(embedded_template, "async_render", )
                             if callable(async_render_func):
                                 embedded_params_str = async_render_func()
                             else:
```

#### Mutant ID: 77
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_77`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -48,7 +48,7 @@
                         
                         if embedded_template is not None:
                             # Patrón seguro para Template (soporta render síncrono y asíncrono)
-                            async_render_func = getattr(embedded_template, "async_render", None)
+                            async_render_func = getattr(embedded_template, "XXasync_renderXX", None)
                             if callable(async_render_func):
                                 embedded_params_str = async_render_func()
                             else:
```

#### Mutant ID: 78
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_78`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -48,7 +48,7 @@
                         
                         if embedded_template is not None:
                             # Patrón seguro para Template (soporta render síncrono y asíncrono)
-                            async_render_func = getattr(embedded_template, "async_render", None)
+                            async_render_func = getattr(embedded_template, "ASYNC_RENDER", None)
                             if callable(async_render_func):
                                 embedded_params_str = async_render_func()
                             else:
```

#### Mutant ID: 79
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_79`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -49,7 +49,7 @@
                         if embedded_template is not None:
                             # Patrón seguro para Template (soporta render síncrono y asíncrono)
                             async_render_func = getattr(embedded_template, "async_render", None)
-                            if callable(async_render_func):
+                            if callable(None):
                                 embedded_params_str = async_render_func()
                             else:
                                 embedded_params_str = embedded_template.render()
```

#### Mutant ID: 80
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_80`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -50,7 +50,7 @@
                             # Patrón seguro para Template (soporta render síncrono y asíncrono)
                             async_render_func = getattr(embedded_template, "async_render", None)
                             if callable(async_render_func):
-                                embedded_params_str = async_render_func()
+                                embedded_params_str = None
                             else:
                                 embedded_params_str = embedded_template.render()
                                 
```

#### Mutant ID: 81
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_81`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -52,7 +52,7 @@
                             if callable(async_render_func):
                                 embedded_params_str = async_render_func()
                             else:
-                                embedded_params_str = embedded_template.render()
+                                embedded_params_str = None
                                 
                             embedded_params = json_loads(embedded_params_str)
                         elif bool(embedded_params) is True:
```

#### Mutant ID: 99
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_99`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -66,7 +66,7 @@
                         if embedded_params is not None:
                             # CRITICAL FIX: Replace placeholders early for robust logging and execution
                             embedded_params = format_placeholders(
-                                embedded_params, token, host, dev_id, mac
+                                embedded_params, None, host, dev_id, mac
                             )
 
                             embedded_data = (
```

#### Mutant ID: 100
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_100`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -66,7 +66,7 @@
                         if embedded_params is not None:
                             # CRITICAL FIX: Replace placeholders early for robust logging and execution
                             embedded_params = format_placeholders(
-                                embedded_params, token, host, dev_id, mac
+                                embedded_params, token, None, dev_id, mac
                             )
 
                             embedded_data = (
```

#### Mutant ID: 101
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_101`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -66,7 +66,7 @@
                         if embedded_params is not None:
                             # CRITICAL FIX: Replace placeholders early for robust logging and execution
                             embedded_params = format_placeholders(
-                                embedded_params, token, host, dev_id, mac
+                                embedded_params, token, host, None, mac
                             )
 
                             embedded_data = (
```

#### Mutant ID: 102
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_102`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -66,7 +66,7 @@
                         if embedded_params is not None:
                             # CRITICAL FIX: Replace placeholders early for robust logging and execution
                             embedded_params = format_placeholders(
-                                embedded_params, token, host, dev_id, mac
+                                embedded_params, token, host, dev_id, None
                             )
 
                             embedded_data = (
```

#### Mutant ID: 104
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_104`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -66,7 +66,7 @@
                         if embedded_params is not None:
                             # CRITICAL FIX: Replace placeholders early for robust logging and execution
                             embedded_params = format_placeholders(
-                                embedded_params, token, host, dev_id, mac
+                                embedded_params, host, dev_id, mac
                             )
 
                             embedded_data = (
```

#### Mutant ID: 105
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_105`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -66,7 +66,7 @@
                         if embedded_params is not None:
                             # CRITICAL FIX: Replace placeholders early for robust logging and execution
                             embedded_params = format_placeholders(
-                                embedded_params, token, host, dev_id, mac
+                                embedded_params, token, dev_id, mac
                             )
 
                             embedded_data = (
```

#### Mutant ID: 106
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_106`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -66,7 +66,7 @@
                         if embedded_params is not None:
                             # CRITICAL FIX: Replace placeholders early for robust logging and execution
                             embedded_params = format_placeholders(
-                                embedded_params, token, host, dev_id, mac
+                                embedded_params, token, host, mac
                             )
 
                             embedded_data = (
```

#### Mutant ID: 107
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_107`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -66,8 +66,7 @@
                         if embedded_params is not None:
                             # CRITICAL FIX: Replace placeholders early for robust logging and execution
                             embedded_params = format_placeholders(
-                                embedded_params, token, host, dev_id, mac
-                            )
+                                embedded_params, token, host, dev_id, )
 
                             embedded_data = (
                                 json_dumps(embedded_params.get("json"))
```

#### Mutant ID: 118
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_118`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -74,7 +74,7 @@
                                 if "json" in embedded_params
                                 else None
                             )
-                            embedded_url = embedded_params.get("url", url)
+                            embedded_url = embedded_params.get("url", None)
                             embedded_method = embedded_params.get("method", method)
 
                             debug_msg = "%s [async_execute] Executing embedded command with params: %s"  # pragma: no mutate
```

#### Mutant ID: 120
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_120`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -74,7 +74,7 @@
                                 if "json" in embedded_params
                                 else None
                             )
-                            embedded_url = embedded_params.get("url", url)
+                            embedded_url = embedded_params.get("url", )
                             embedded_method = embedded_params.get("method", method)
 
                             debug_msg = "%s [async_execute] Executing embedded command with params: %s"  # pragma: no mutate
```

#### Mutant ID: 152
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_152`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -86,7 +86,7 @@
                                     method=embedded_method,
                                     url=embedded_url,
                                     data=embedded_data,
-                                    headers=embedded_params.get("headers", headers),
+                                    headers=embedded_params.get(None, headers),
                                     device_state=device_state,
                                 ),
                             )
```

#### Mutant ID: 156
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_156`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -86,7 +86,7 @@
                                     method=embedded_method,
                                     url=embedded_url,
                                     data=embedded_data,
-                                    headers=embedded_params.get("headers", headers),
+                                    headers=embedded_params.get("XXheadersXX", headers),
                                     device_state=device_state,
                                 ),
                             )
```

#### Mutant ID: 157
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_157`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -86,7 +86,7 @@
                                     method=embedded_method,
                                     url=embedded_url,
                                     data=embedded_data,
-                                    headers=embedded_params.get("headers", headers),
+                                    headers=embedded_params.get("HEADERS", headers),
                                     device_state=device_state,
                                 ),
                             )
```

#### Mutant ID: 158
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_158`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -90,7 +90,7 @@
                                     device_state=device_state,
                                 ),
                             )
-                            if inspect.isawaitable(res):
+                            if inspect.isawaitable(None):
                                 await res
                 else:
                     warn_msg = "%s [async_execute] Embedded command found, but cannot check its condition (device_state is missing). Skipping."  # pragma: no mutate
```

#### Mutant ID: 196
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_196`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -113,7 +113,7 @@
             return "{}", {}
 
         # Periodic Reset Logic: For local sessions not preserving keep_alive, explicitly close and reopen
-        if _is_poll and not self._keep_alive:
+        if _is_poll or not self._keep_alive:
             local_session = self._shared_state.local_session
             if local_session is not None:
                 self._shared_state.local_session = None
```

#### Mutant ID: 197
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_197`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -113,7 +113,7 @@
             return "{}", {}
 
         # Periodic Reset Logic: For local sessions not preserving keep_alive, explicitly close and reopen
-        if _is_poll and not self._keep_alive:
+        if _is_poll and self._keep_alive:
             local_session = self._shared_state.local_session
             if local_session is not None:
                 self._shared_state.local_session = None
```

#### Mutant ID: 198
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_198`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -114,7 +114,7 @@
 
         # Periodic Reset Logic: For local sessions not preserving keep_alive, explicitly close and reopen
         if _is_poll and not self._keep_alive:
-            local_session = self._shared_state.local_session
+            local_session = None
             if local_session is not None:
                 self._shared_state.local_session = None
 
```

#### Mutant ID: 199
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_199`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -115,7 +115,7 @@
         # Periodic Reset Logic: For local sessions not preserving keep_alive, explicitly close and reopen
         if _is_poll and not self._keep_alive:
             local_session = self._shared_state.local_session
-            if local_session is not None:
+            if local_session is None:
                 self._shared_state.local_session = None
 
             if local_session and not local_session.closed:
```

#### Mutant ID: 200
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_200`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -116,7 +116,7 @@
         if _is_poll and not self._keep_alive:
             local_session = self._shared_state.local_session
             if local_session is not None:
-                self._shared_state.local_session = None
+                self._shared_state.local_session = ""
 
             if local_session and not local_session.closed:
                 debug_msg = "%s [Periodic Reset] Closing local session (ID: %s) before poll."  # pragma: no mutate
```

#### Mutant ID: 230
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_230`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -137,5 +137,5 @@
             return probe_response_text, None
 
         return await self._async_execute_request(
-            method, url, data, headers, _is_poll=_is_poll
+            None, url, data, headers, _is_poll=_is_poll
         )
```

#### Mutant ID: 231
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_231`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -137,5 +137,5 @@
             return probe_response_text, None
 
         return await self._async_execute_request(
-            method, url, data, headers, _is_poll=_is_poll
+            method, None, data, headers, _is_poll=_is_poll
         )
```

#### Mutant ID: 232
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_232`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -137,5 +137,5 @@
             return probe_response_text, None
 
         return await self._async_execute_request(
-            method, url, data, headers, _is_poll=_is_poll
+            method, url, None, headers, _is_poll=_is_poll
         )
```

#### Mutant ID: 233
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_233`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -137,5 +137,5 @@
             return probe_response_text, None
 
         return await self._async_execute_request(
-            method, url, data, headers, _is_poll=_is_poll
+            method, url, data, None, _is_poll=_is_poll
         )
```

#### Mutant ID: 234
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_234`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -137,5 +137,5 @@
             return probe_response_text, None
 
         return await self._async_execute_request(
-            method, url, data, headers, _is_poll=_is_poll
+            method, url, data, headers, _is_poll=None
         )
```

#### Mutant ID: 239
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁasync_execute__mutmut_239`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -137,5 +137,4 @@
             return probe_response_text, None
 
         return await self._async_execute_request(
-            method, url, data, headers, _is_poll=_is_poll
-        )
+            method, url, data, headers, )
```

### ConnectionAiohttp8888.close

#### Mutant ID: 34
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁclose__mutmut_34`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -36,7 +36,7 @@
             async with self._shared_state.lock:
                 self._shared_state.initialized = False
                 self._shared_state.ssl_context = None
-                if self._shared_state.local_session is not None:
+                if self._shared_state.local_session is None:
                     self._shared_state.local_session = None
         except (RuntimeError, ValueError) as e:
             err_msg = "%s [aiohttp] Error locking/resetting shared state during close: %s"  # pragma: no mutate
```

### ConnectionAiohttp8888.create_updated

#### Mutant ID: 48
> target: `custom_components.climate_ip.connection_aiohttp.xǁConnectionAiohttp8888ǁcreate_updated__mutmut_48`

```diff
--- custom_components/climate_ip/connection_aiohttp.py
+++ custom_components/climate_ip/connection_aiohttp.py
@@ -28,7 +28,7 @@
                     condition_str = yaml_node[CONFIG_DEVICE_CONNECTION][CONFIG_DEVICE_CONDITION_TEMPLATE]
                     if new_connection._embedded_command is not None:
                         new_connection._embedded_command.condition_template = Template(
-                            condition_str, getattr(self, "_hass", None)
+                            condition_str, getattr(self, "_hass", )
                         )
         # pylint: enable=protected-access
 
```

## Excluded / Redundant Mutants

| ID | Class | Method | Reason |
| --- | --- | --- | --- |
| 1 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 2 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 3 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 4 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 6 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 31 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 32 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 35 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 37 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 38 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 39 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 40 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 41 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 42 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 43 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 44 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 46 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 47 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 48 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 49 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 50 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 51 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 52 | ConnectionAiohttp8888 | __init__ | Logger / Diagnostics mutation |
| 1 | ConnectionAiohttp8888 | set_controller_ref | Logger / Diagnostics mutation |
| 2 | ConnectionAiohttp8888 | set_controller_ref | Logger / Diagnostics mutation |
| 3 | ConnectionAiohttp8888 | set_controller_ref | Logger / Diagnostics mutation |
| 4 | ConnectionAiohttp8888 | set_controller_ref | Logger / Diagnostics mutation |
| 15 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 16 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 17 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 18 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 19 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 20 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 21 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 22 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 23 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 24 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 25 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 26 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 36 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 37 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 38 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 39 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 40 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 41 | ConnectionAiohttp8888 | _create_ssl_context | Logger / Diagnostics mutation |
| 23 | ConnectionAiohttp8888 | create_updated | Dict get default None mutation |
| 29 | ConnectionAiohttp8888 | create_updated | Dict get default None mutation |
| 31 | ConnectionAiohttp8888 | create_updated | Dict get default None mutation |
| 25 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 26 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 27 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 28 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 29 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 30 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 31 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 32 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 33 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 34 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 60 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 61 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 62 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 63 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 64 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 65 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 66 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 67 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 68 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 69 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 70 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 71 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 103 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 104 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 105 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 106 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 107 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 108 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 109 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 110 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 111 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 112 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 113 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 114 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 115 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 116 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 117 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 118 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 120 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 121 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 129 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 130 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 131 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 132 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 135 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 136 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 140 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 141 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 143 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 144 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 148 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 155 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 156 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 157 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 158 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 160 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 161 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 162 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 166 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 167 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 168 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 170 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 171 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 172 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 173 | ConnectionAiohttp8888 | _try_connection | Logger / Diagnostics mutation |
| 6 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 7 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 8 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 49 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 50 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 51 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 52 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 54 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 55 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 56 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 57 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 58 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 59 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 60 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 61 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 62 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 63 | ConnectionAiohttp8888 | _get_session | Logger / Diagnostics mutation |
| 38 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 39 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 40 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 41 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 42 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 91 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 92 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 93 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 94 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 95 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 97 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 98 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 99 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 100 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 101 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 103 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 105 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 106 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 107 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 108 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 109 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 110 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 111 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 112 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 113 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 114 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 115 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 121 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 131 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 133 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 134 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 135 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 136 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 137 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 138 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 139 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 140 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 141 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 142 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 143 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 146 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 147 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 148 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 149 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 150 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 151 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 152 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 153 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 154 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 155 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 156 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 158 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 161 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 162 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 163 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 164 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 168 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 171 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 173 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 175 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 176 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 182 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 183 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 184 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 185 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 186 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 187 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 188 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 189 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 190 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 191 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 192 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 193 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 197 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 198 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 210 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 211 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 212 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 213 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 231 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 232 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 236 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 237 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 238 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 239 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 240 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 241 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 242 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 243 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 244 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 245 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 246 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 247 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 248 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 249 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 250 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 251 | ConnectionAiohttp8888 | _async_execute_request | Logger / Diagnostics mutation |
| 27 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 28 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 29 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 30 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 42 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 45 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 46 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 47 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 48 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 49 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 50 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 51 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 52 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 53 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 54 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 58 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 64 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 67 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 82 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 83 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 87 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 88 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 89 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 90 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 91 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 92 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 93 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 94 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 95 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 125 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 127 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 130 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 131 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 132 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 133 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 134 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 135 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 136 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 138 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 160 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 161 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 162 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 163 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 164 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 165 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 166 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 167 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 168 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 169 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 170 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 171 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 172 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 173 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 174 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 175 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 176 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 177 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 183 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 188 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 191 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 192 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 193 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 194 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 201 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 202 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 203 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 204 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 205 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 206 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 207 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 208 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 209 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 210 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 211 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 212 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 213 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 214 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 215 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 216 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 217 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 218 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 219 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 220 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 221 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 222 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 223 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 224 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 225 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 226 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 227 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 228 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 229 | ConnectionAiohttp8888 | async_execute | Logger / Diagnostics mutation |
| 1 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 2 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 3 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 4 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 6 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 7 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 8 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 9 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 10 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 11 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 14 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 15 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 16 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 17 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 18 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 19 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 20 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 24 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 25 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 26 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 27 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 28 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 29 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 30 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 35 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 36 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 37 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 38 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 39 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 40 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
| 41 | ConnectionAiohttp8888 | close | Logger / Diagnostics mutation |
