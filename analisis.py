"""Consulta y análisis de scrap sin escrituras ni alteración de los modelos."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO

from flask import Blueprint, current_app, render_template, request, send_file
from sqlalchemy import and_, or_
from sqlalchemy.orm import selectinload

from productivo import normalizar_operacion, produccion_por_operacion

CERO = Decimal("0")
FILTROS_EXTRA = ("celula", "equipo", "turno", "motivo", "cliente", "proveedor", "estado")


def filtros_analisis(args):
    hoy = date.today()
    try:
        desde = date.fromisoformat(args.get("desde") or hoy.replace(day=1).isoformat())
        hasta = date.fromisoformat(args.get("hasta") or hoy.isoformat())
    except (ValueError, TypeError):
        raise ValueError("Ingresá fechas válidas para el período") from None
    if desde > hasta or hasta == date.max:
        raise ValueError("Revisá el período: desde debe ser anterior o igual a hasta")
    filtros = {campo: str(args.get(campo) or "").strip() for campo in FILTROS_EXTRA}
    filtros.update(desde=desde, hasta=hasta,
        pieza=str(args.get("pieza") or "").strip(),
        operacion=normalizar_operacion(args.get("operacion")),
        unidad=str(args.get("unidad") or "PZS").strip().upper(),
        fecha=str(args.get("fecha") or "EVENTO").upper(),
        origen_scrap=str(args.get("origen_scrap") or "TODOS").upper())
    if (filtros["fecha"] not in {"EVENTO", "DNC"}
            or filtros["origen_scrap"] not in {"TODOS", "DIRECTO", "RETRABAJO"}
            or not 1 <= len(filtros["unidad"]) <= 10):
        raise ValueError("Uno de los filtros no es válido")
    return filtros


def contiene(valor, filtro):
    return not filtro or filtro.casefold() in str(valor or "").casefold()


def porcentaje_scrap(buenas, scrap):
    if buenas is None or buenas + scrap <= 0:
        return None
    return scrap / (buenas + scrap) * Decimal("100")


def construir_analisis(declaraciones, produccion, filtros, produccion_disponible=True):
    """Una única fuente de cálculos para pantalla y Excel. Cantidades en Decimal."""
    desde, hasta = filtros["desde"], filtros["hasta"]
    en_rango = lambda fecha: desde <= fecha <= hasta
    grupos = {}
    detalle = []
    causas = defaultdict(lambda: CERO)
    tendencia = defaultdict(lambda: {"directo": CERO, "retrabajo": CERO})
    resumen = {k: CERO for k in ("directo", "retrabajo", "recuperadas", "horas", "pendiente", "liberadas")}
    dnc_con_scrap = set()
    controles = {"pendientes": 0, "diferencias": 0}

    def grupo(codigo, operacion):
        clave = (str(codigo or "").strip().upper(), normalizar_operacion(operacion))
        if clave not in grupos:
            grupos[clave] = {"pieza": clave[0], "operacion": clave[1], "descripcion": "",
                "directo": CERO, "retrabajo": CERO, "buenas": None,
                "produccion_invalida": False, "dnc": set()}
        return grupos[clave]

    def coincide_pieza(codigo, operacion):
        return (contiene(codigo, filtros["pieza"])
                and (not filtros["operacion"] or normalizar_operacion(operacion) == filtros["operacion"]))

    for dnc in declaraciones:
        if not all(contiene(getattr(dnc, atributo), filtros[campo]) for campo, atributo in (
                ("celula", "celula_detecta"), ("equipo", "equipo"), ("turno", "turno"))):
            continue
        if filtros["estado"] and dnc.estado != filtros["estado"]:
            continue
        for item in dnc.items:
            if (str(item.unidad).upper() != filtros["unidad"]
                    or not coincide_pieza(item.codigo_pieza, item.operacion_codigo)):
                continue
            if not (contiene(dnc.cliente, filtros["cliente"]) or contiene(item.codigo_cliente, filtros["cliente"])):
                continue
            proveedor = " · ".join(x for x in (item.proveedor_numero, item.proveedor) if x)
            if not contiene(proveedor, filtros["proveedor"]):
                continue
            destino = grupo(item.codigo_pieza, item.operacion_codigo)
            destino["descripcion"] = item.descripcion or ""

            def registrar(cantidad, origen, fecha_evento, motivo):
                if cantidad <= 0 or (filtros["origen_scrap"] != "TODOS" and filtros["origen_scrap"] != origen):
                    return
                fecha_filtro = dnc.fecha if filtros["fecha"] == "DNC" else fecha_evento
                etiqueta = f"{motivo.codigo} · {motivo.nombre}" if motivo else "Sin causa"
                if not en_rango(fecha_filtro) or not contiene(etiqueta, filtros["motivo"]):
                    return
                campo = "directo" if origen == "DIRECTO" else "retrabajo"
                destino[campo] += cantidad
                destino["dnc"].add(dnc.id)
                dnc_con_scrap.add(dnc.id)
                resumen[campo] += cantidad
                causas[etiqueta] += cantidad
                tendencia[fecha_filtro][campo] += cantidad
                detalle.append({"fecha": fecha_filtro, "fecha_dnc": dnc.fecha,
                    "dnc": dnc.numero, "declaracion_id": dnc.id, "item_id": item.id,
                    "pieza": item.codigo_pieza, "descripcion": item.descripcion or "",
                    "operacion": normalizar_operacion(item.operacion_codigo), "hcp": item.trazabilidad,
                    "origen": origen, "cantidad": cantidad, "motivo": etiqueta,
                    "celula": dnc.celula_detecta, "equipo": dnc.equipo, "turno": dnc.turno or "",
                    "responsable": item.responsable_celula or item.responsable_proveedor or "Sin asignar",
                    "responsabilidad": item.responsabilidad_estado, "proveedor": proveedor,
                    "cliente": dnc.cliente or item.codigo_cliente or "",
                    "estado": dnc.estado, "observacion": item.observacion_calidad or item.observacion or ""})

            # Una alerta no decidida no es scrap. Los flujos antiguos sin fecha de
            # validación conservan como referencia la fecha de su declaración.
            fecha_directo = dnc.fecha_validacion.date() if dnc.fecha_validacion else dnc.fecha
            if dnc.estado != "PENDIENTE_CALIDAD":
                registrar(item.cantidad_scrap_directo, "DIRECTO", fecha_directo, item.motivo)
            for intervencion in item.intervenciones:
                if dnc.estado == "PENDIENTE_CALIDAD":
                    continue
                registrar(intervencion.cantidad_scrap, "RETRABAJO", intervencion.fecha,
                          intervencion.motivo_scrap or item.motivo)
                fecha_filtro = dnc.fecha if filtros["fecha"] == "DNC" else intervencion.fecha
                motivo_resultado = intervencion.motivo_scrap or item.motivo
                causa_resultado = f"{motivo_resultado.codigo} · {motivo_resultado.nombre}" if motivo_resultado else "Sin causa"
                if en_rango(fecha_filtro) and contiene(causa_resultado, filtros["motivo"]):
                    resumen["recuperadas"] += intervencion.cantidad_ok
                    resumen["horas"] += Decimal(intervencion.minutos * intervencion.cantidad_personas) / 60
            # Pendientes actuales de las DNC emitidas en el intervalo; no es un
            # inventario histórico de pendientes a la fecha de corte.
            causa_item = f"{item.motivo.codigo} · {item.motivo.nombre}" if item.motivo else "Sin causa"
            if en_rango(dnc.fecha) and contiene(causa_item, filtros["motivo"]):
                resumen["pendiente"] += item.cantidad_retrabajo_pendiente
                resumen["liberadas"] += item.cantidad_liberada
                if item.requiere_validacion_logistica:
                    controles["pendientes"] += item.fecha_validacion_logistica is None
                    controles["diferencias"] += (item.cantidad_scrap_validada_logistica is not None
                        and item.cantidad_scrap_validada_logistica != item.cantidad_scrap_directo)

    comparable = (filtros["unidad"] == "PZS" and filtros["fecha"] == "EVENTO"
                  and filtros["origen_scrap"] == "TODOS" and not any(filtros[k] for k in FILTROS_EXTRA))
    # Los datos productivos no tienen causa, cliente, célula, equipo ni turno.
    # No se presenta un porcentaje engañoso al filtrar por esas dimensiones.
    for fila in produccion if produccion_disponible and filtros["unidad"] == "PZS" else []:
        if fila.get("fecha") and not en_rango(fila["fecha"]):
            continue
        if not coincide_pieza(fila["codigo"], fila["operacion"]):
            continue
        destino = grupo(fila["codigo"], fila["operacion"])
        cantidad = Decimal(str(fila["cantidad"])) if fila["cantidad"] is not None else None
        if (cantidad is None or not cantidad.is_finite() or cantidad < 0 or fila.get("sin_cantidad", 0)):
            destino["produccion_invalida"] = True
        else:
            destino["buenas"] = (destino["buenas"] or CERO) + cantidad

    comparacion = []
    for fila in grupos.values():
        fila["scrap"] = fila["directo"] + fila["retrabajo"]
        if fila["produccion_invalida"] or not produccion_disponible or not comparable:
            fila["buenas"] = None
        motivo_sin_tasa = ("Filtros sin producción comparable" if not comparable else
                          "Falta operación" if not fila["operacion"] else
                          "Producción no disponible" if not produccion_disponible else
                          "Producción inválida o sin registros" if fila["buenas"] is None else "")
        fila["porcentaje"] = None if motivo_sin_tasa else porcentaje_scrap(fila["buenas"], fila["scrap"])
        fila["nota"] = motivo_sin_tasa or ("Sin unidades para comparar" if fila["porcentaje"] is None else "")
        fila["cantidad_dnc"] = len(fila.pop("dnc"))
        if fila["scrap"] > 0 or (fila["buenas"] is not None and comparable):
            comparacion.append(fila)
    comparacion.sort(key=lambda f: (-f["scrap"], f["pieza"], f["operacion"]))
    resumen["scrap"] = resumen["directo"] + resumen["retrabajo"]
    resumen["dnc"] = len(dnc_con_scrap)
    resumen["recuperacion"] = (resumen["recuperadas"] / (resumen["recuperadas"] + resumen["retrabajo"]) * 100
                               if resumen["recuperadas"] + resumen["retrabajo"] > 0 else None)
    if filtros["motivo"] or filtros["origen_scrap"] != "TODOS":
        resumen["recuperacion"] = None
    acumulado = CERO
    pareto = []
    for causa, cantidad in sorted(causas.items(), key=lambda x: (-x[1], x[0])):
        acumulado += cantidad
        pareto.append({"causa": causa, "cantidad": cantidad,
                       "porcentaje": cantidad / resumen["scrap"] * 100,
                       "acumulado": acumulado / resumen["scrap"] * 100})
    deteccion, responsabilidad = defaultdict(lambda: CERO), defaultdict(lambda: CERO)
    for fila in detalle:
        deteccion[(fila["celula"], fila["equipo"], fila["turno"])] += fila["cantidad"]
        responsabilidad[(fila["responsabilidad"], fila["responsable"])] += fila["cantidad"]
    por_deteccion = [{"celula": k[0], "equipo": k[1], "turno": k[2], "scrap": v}
                    for k, v in sorted(deteccion.items(), key=lambda x: (-x[1], x[0]))]
    por_responsabilidad = [{"conclusion": k[0], "responsable": k[1], "scrap": v}
                          for k, v in sorted(responsabilidad.items(), key=lambda x: (-x[1], x[0]))]
    return {"deteccion": por_deteccion, "responsabilidad": por_responsabilidad, "comparacion": comparacion, "detalle": sorted(detalle, key=lambda f: (f["fecha"], f["dnc"], f["item_id"]), reverse=True),
            "resumen": resumen, "pareto": pareto, "controles": controles,
            "tendencia": [{"fecha": fecha, **valores} for fecha, valores in sorted(tendencia.items())],
            "produccion_disponible": produccion_disponible, "comparable": comparable}


def libro_analisis(datos, filtros):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    libro = Workbook()
    libro.remove(libro.active)
    hojas = [
        ("Comparación", ["Pieza", "Operación", "Descripción", "Buenas", "Scrap directo", "Scrap retrabajo", "Scrap total", "% scrap", "Nota"],
         [[f["pieza"], f["operacion"], f["descripcion"], f["buenas"], f["directo"], f["retrabajo"], f["scrap"], f["porcentaje"], f["nota"]] for f in datos["comparacion"]]),
        ("Indicadores", ["Indicador", "Valor"], [
            [etiqueta, datos["resumen"][clave]] for clave, etiqueta in (
                ("scrap", "Scrap total"), ("directo", "Scrap directo"), ("retrabajo", "Scrap de retrabajo"),
                ("dnc", "DNC con scrap"), ("recuperadas", "Recuperadas"), ("horas", "Horas-hombre"),
                ("recuperacion", "% recuperación de resultados"), ("pendiente", "Retrabajo pendiente actual"),
                ("liberadas", "Liberadas de DNC emitidas en el período"))] +
            [["Controles logísticos pendientes actuales", datos["controles"]["pendientes"]],
             ["Controles logísticos con diferencias", datos["controles"]["diferencias"]]]),
        ("Detección", ["Célula", "Equipo", "Turno", "Scrap"], [[f[k] for k in ("celula", "equipo", "turno", "scrap")] for f in datos["deteccion"]]),
        ("Responsabilidad", ["Conclusión", "Responsable", "Scrap"], [[f[k] for k in ("conclusion", "responsable", "scrap")] for f in datos["responsabilidad"]]),
        ("Causas", ["Causa", "Scrap", "%", "% acumulado"], [[f[k] for k in ("causa", "cantidad", "porcentaje", "acumulado")] for f in datos["pareto"]]),
        ("Evolución", ["Fecha", "Scrap directo", "Scrap retrabajo"], [[f[k] for k in ("fecha", "directo", "retrabajo")] for f in datos["tendencia"]]),
        ("Detalle DNC", ["Fecha análisis", "Fecha DNC", "DNC", "Renglón ID", "Pieza", "Operación", "HCP", "Origen scrap", "Cantidad", "Motivo", "Célula detección", "Equipo", "Turno", "Responsable", "Conclusión responsabilidad", "Proveedor", "Cliente", "Estado", "Indicación"],
         [[f[k] for k in ("fecha", "fecha_dnc", "dnc", "item_id", "pieza", "operacion", "hcp", "origen", "cantidad", "motivo", "celula", "equipo", "turno", "responsable", "responsabilidad", "proveedor", "cliente", "estado", "observacion")] for f in datos["detalle"]]),
        ("Filtros", ["Filtro", "Valor"], [[k, v] for k, v in filtros.items()] + [
            ["Fórmula", "Scrap / (buenas + scrap) × 100, por pieza y operación"],
            ["Producción disponible", "Sí" if datos["produccion_disponible"] else "No; porcentajes sin datos"],
            ["Pendientes", "Situación actual de las DNC emitidas en el período, no inventario histórico"],
            ["Fechas", "EVENTO: última validación para directo, intervención para retrabajo; DNC: fecha declaración"],
            ["Alcance", "Incluye scrap de ensayos. No es una tasa por lote de fabricación."],
            ["Cantidad scrap", "Disposición directa + resultados de retrabajo; no se suma otra vez lo recibido por Logística."],
            ["Detalle producción", "Sin desglose por causa, célula, equipo, turno, cliente o proveedor"],
            ["Recuperación", "Porcentaje sobre resultados de retrabajo del período; no sobre todo lo enviado"],
        ]),
    ]
    for nombre, encabezados, filas in hojas:
        hoja = libro.create_sheet(nombre)
        hoja.append(encabezados)
        for fila in filas:
            hoja.append([float(x) if isinstance(x, Decimal) else x for x in fila])
        hoja.freeze_panes = "A2"
        hoja.auto_filter.ref = hoja.dimensions
        for fila in hoja:
            for celda in fila:
                if isinstance(celda.value, str):
                    celda.data_type = "s"
        for celda in hoja[1]:
            celda.font = Font(bold=True)
        for columna in hoja.columns:
            hoja.column_dimensions[columna[0].column_letter].width = min(48, max(13, max(len(str(c.value or "")) for c in columna) + 2))
    return libro


def crear_blueprint(db, Declaracion, DeclaracionItem, Motivo, RetrabajoIntervencion):
    bp = Blueprint("analisis", __name__)

    def cargar():
        filtros = filtros_analisis(request.args)
        desde, hasta = filtros["desde"], filtros["hasta"]
        consulta = db.select(Declaracion).where(or_(
            Declaracion.fecha.between(desde, hasta),
            and_(Declaracion.fecha_validacion >= datetime.combine(desde, time.min),
                 Declaracion.fecha_validacion < datetime.combine(hasta + timedelta(days=1), time.min)),
            Declaracion.items.any(DeclaracionItem.intervenciones.any(RetrabajoIntervencion.fecha.between(desde, hasta)))
        )).options(selectinload(Declaracion.items).selectinload(DeclaracionItem.motivo),
                   selectinload(Declaracion.items).selectinload(DeclaracionItem.intervenciones).selectinload(RetrabajoIntervencion.motivo_scrap))
        declaraciones = db.session.execute(consulta).scalars().all()
        disponible = True
        try:
            produccion = produccion_por_operacion(desde, hasta)
        except Exception:
            current_app.logger.exception("No se pudo consultar la producción del período")
            produccion, disponible = [], False
        return construir_analisis(declaraciones, produccion, filtros, disponible), filtros

    @bp.get("/analisis")
    def panel():
        try:
            datos, filtros = cargar()
        except ValueError as exc:
            return render_template("analisis_error.html", mensaje=str(exc)), 400
        try:
            pagina = max(1, int(request.args.get("pagina", "1")))
        except ValueError:
            pagina = 1
        pagina = min(pagina, max(1, (len(datos["comparacion"]) + 99) // 100))
        inicio = (pagina - 1) * 100
        return render_template("analisis.html", datos=datos, filtros=filtros, pagina=pagina,
            filas=datos["comparacion"][inicio:inicio + 100], detalle=datos["detalle"][:100],
            modo_demo=current_app.config["PRODUCTIVE_DEMO_MODE"],
            hay_mas=inicio + 100 < len(datos["comparacion"]))

    @bp.get("/analisis/excel")
    def excel():
        try:
            datos, filtros = cargar()
        except ValueError as exc:
            return render_template("analisis_error.html", mensaje=str(exc)), 400
        salida = BytesIO()
        libro_analisis(datos, filtros).save(salida)
        salida.seek(0)
        return send_file(salida, as_attachment=True,
            download_name=f"analisis_scrap_{filtros['desde']}_{filtros['hasta']}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    return bp
