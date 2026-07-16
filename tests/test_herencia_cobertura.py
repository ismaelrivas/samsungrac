"""Tests para herencia_cobertura_source.py — validación de Coverage Inheritance."""
import pytest
from herencia_cobertura_source import validar_herencia_cobertura, funcion_sincrona_simple


@pytest.mark.asyncio
async def test_herencia_activa():
    """Verifica la rama is_active=True."""
    result = await validar_herencia_cobertura("localhost", is_active=True)
    assert result["status"] == "active"
    assert result["port"] == 8080
    assert result["retries"] == 3


@pytest.mark.asyncio
async def test_herencia_inactiva():
    """Verifica la rama is_active=False (defaults)."""
    result = await validar_herencia_cobertura("localhost")
    assert result["status"] == "inactive"
    assert result["timeout"] == 30.0


def test_sincrona_habilitada():
    """Verifica funcion_sincrona_simple con habilitado=True (default)."""
    assert funcion_sincrona_simple() == "default:42"


def test_sincrona_deshabilitada():
    """Verifica funcion_sincrona_simple con habilitado=False."""
    assert funcion_sincrona_simple(habilitado=False) == "disabled"


def test_sincrona_custom():
    """Verifica funcion_sincrona_simple con parámetros customizados."""
    assert funcion_sincrona_simple(nombre="test", valor=99) == "test:99"
