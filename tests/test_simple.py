from custom_components.climate_ip.simple import add


def test_add():
    assert add(1, 2) == 3
