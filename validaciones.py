"""Reglas de cantidades compartidas, independientes de Flask y de la base."""

from decimal import Decimal, InvalidOperation


def decimal_no_negativo(value, campo, escala=3):
    try:
        numero = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{campo} no es válido") from None
    if not numero.is_finite():
        raise ValueError(f"{campo} debe ser un número finito")
    if numero < 0:
        raise ValueError(f"{campo} no puede ser negativo")
    # Coincide con NUMERIC(12, escala); evita redondeos silenciosos en MySQL.
    limite = Decimal(10) ** (12 - escala) - Decimal(10) ** -escala
    if numero > limite:
        raise ValueError(f"{campo} no puede superar {limite}")
    if numero != numero.quantize(Decimal(10) ** -escala):
        raise ValueError(f"{campo} admite hasta {escala} decimales")
    return numero


def entero_no_negativo(value, campo):
    numero = decimal_no_negativo(value, campo)
    if numero != numero.to_integral_value():
        raise ValueError(f"{campo} debe ser un número entero")
    return int(numero)


def validar_disposicion(item, cantidad, scrap, retrabajo, liberada):
    for valor in (cantidad, scrap, retrabajo, liberada):
        decimal_no_negativo(valor, "La cantidad")
        if str(item.unidad).upper() == "PZS":
            entero_no_negativo(valor, "La cantidad de piezas")
    if cantidad <= 0:
        raise ValueError("La cantidad detectada debe ser mayor a cero")
    if scrap + retrabajo + liberada != cantidad:
        raise ValueError("Scrap + retrabajo + liberadas debe coincidir con la cantidad detectada")
    if retrabajo < item.cantidad_retrabajo_resuelta:
        raise ValueError("El retrabajo no puede ser menor que la cantidad que ya fue procesada")
