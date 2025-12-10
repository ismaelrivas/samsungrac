import logging

_LOGGER = logging.getLogger(__name__)

def find_key_in_data(data, key):
    """
    Recursively search for a key in a dictionary or a list of dictionaries.
    """
    _LOGGER.debug(f"find_key_in_data: Searching for '{key}' in data type: {type(data)}")

    if isinstance(data, dict):
        _LOGGER.debug(f"find_key_in_data: Current dict keys: {data.keys()}")
        if key in data:
            _LOGGER.debug(f"find_key_in_data: Found '{key}' in current dict: {data[key]}")
            return data[key]
        for k, v in data.items():
            _LOGGER.debug(f"find_key_in_data: Recursing into dict item '{k}'")
            item = find_key_in_data(v, key)
            if item is not None:
                return item
    elif isinstance(data, list):
        _LOGGER.debug(f"find_key_in_data: Recursing into list with {len(data)} items.")
        for i, item_in_list in enumerate(data):
            _LOGGER.debug(f"find_key_in_data: Recursing into list item {i}")
            item = find_key_in_data(item_in_list, key)
            if item is not None:
                return item
    _LOGGER.debug(f"find_key_in_data: '{key}' not found in current data structure.")
    return None