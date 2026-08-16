import trp


def test_package_importable() -> None:
    assert trp.__doc__ is not None
