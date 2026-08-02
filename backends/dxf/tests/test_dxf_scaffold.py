def test_imports() -> None:
    import cadintent_dxf
    import ezdxf

    assert cadintent_dxf.__version__
    assert ezdxf.version
