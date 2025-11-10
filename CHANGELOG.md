## v9.0.0

This is a major release that includes a complete asynchronous refactor and addresses several critical stability issues reported by the community. Thank you for your patience and collaboration.

### ✨ Added
- **Config Flow**: The integration can now be configured entirely through the Home Assistant user interface.
- **Token and MAC Auto-Discovery**: When using the UI configuration, the integration can now automatically discover the device's token and MAC address.
- **Push Notifications (Port 2878):** The integration now supports push notifications for devices on port 2878, allowing for instant status updates (e.g., when using the physical remote) without polling.

### 🛠️ Fixed
- **Connection Stability (Port 2878):**
    - Resolved race conditions between commands and status updates by implementing a concurrency lock. This should prevent unexpected shutdowns.
    - Improved automatic reconnection logic. The integration should now correctly detect and re-establish a connection if the AC unit loses power and comes back online.
- **Regression on Port 8888:**
    - Fixed the `HeaderParsingError` that was affecting devices on port 8888.

### �� Changed
- **Asynchronous Refactor:** The entire integration has been rewritten to be fully asynchronous, improving performance and aligning with modern Home Assistant standards.
- **Fan Mode Handling:** The device map (`samsung_2878.yaml`) has been updated to better handle fan speed limitations in specific modes. The integration will now only offer compatible fan speeds for each mode.
- The integration now supports a dual configuration mode: both via the user interface (Config Flow) and YAML.
