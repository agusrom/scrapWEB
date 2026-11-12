import os
import re
from collections import defaultdict
from decimal import Decimal

from flask import current_app
from sqlalchemy import create_engine, text


DEMO_PIEZAS = [
    {
        "codigo": "CONJ-1000",
        "codigo_cliente": "CLI-1000",
        "material": "",
        "descripcion": "CONJUNTO SOPORTE MOTOR",
        "stock": 120,
    },
    {
        "codigo": "SUB-1100",
        "codigo_cliente": "CLI-1100",
        "material": "",
        "descripcion": "SUBCONJUNTO SOLDADO",
        "stock": 32,
    },
    {
        "codigo": "CH-1110",
        "codigo_cliente": "",
        "material": "CHAPA-2MM",
        "descripcion": "CHAPA LATERAL IZQUIERDA",
        "stock": 200,
    },
    {
        "codigo": "CH-1120",
        "codigo_cliente": "",
        "material": "CHAPA-2MM",
        "descripcion": "CHAPA LATERAL DERECHA",
        "stock": 190,
    },
    {
        "codigo": "TUB-1130",
        "codigo_cliente": "",
        "material": "TUBO-25",
        "descripcion": "TUBO REFUERZO",
        "stock": 450,
    },
]
DEMO_ESTRUCTURA = {
    "CONJ-1000": [
        {"codigo": "SUB-1100", "descripcion": "SUBCONJUNTO SOLDADO", "uso": 1},
        {"codigo": "TUB-1130", "descripcion": "TUBO REFUERZO", "uso": 2},
    ],
    "SUB-1100": [
        {"codigo": "CH-1110", "descripcion": "CHAPA LATERAL IZQUIERDA", "uso": 1},
        {"codigo": "CH-1120", "descripcion": "CHAPA LATERAL DERECHA", "uso": 1},
    ],
}
DEMO_OPERACIONES = [
    {"codigo": "010", "titulo": "CORTE"},
    {"codigo": "020", "titulo": "CONFORMADO"},
    {"codigo": "030", "titulo": "SOLDADURA"},
    {"codigo": "040", "titulo": "MECANIZADO"},
    {"codigo": "050", "titulo": "PINTURA"},
    {"codigo": "090", "titulo": "CONTROL FINAL"},
]
DEMO_OPERACIONES_POR_PIEZA = {
    "CONJ-1000": DEMO_OPERACIONES,
    "SUB-1100": DEMO_OPERACIONES[:4],
}
DEMO_TURNOS = [
    {"id": 1, "turno": "Mañana"},
    {"id": 2, "turno": "Tarde"},
    {"id": 3, "turno": "Noche"},
]
DEMO_EQUIPOS = [
    {"equipo": "101", "descripcion": "Línea principal", "celula": "Célula 0001"},
    {"equipo": "102", "descripcion": "Línea auxiliar", "celula": "Célula 0001"},
    {"equipo": "201", "descripcion": "Puesto de retrabajo", "celula": "Retrabajo"},
    {"equipo": "301", "descripcion": "Laboratorio", "celula": "Calidad"},
    {"equipo": "401", "descripcion": "Control de ingreso", "celula": "Recepción"},
]
DEMO_PROVEEDORES = [
    {"numero": "1001", "descripcion": "Proveedor de prueba"},
    {"numero": "2040", "descripcion": "Acero Demo S.A."},
]


def identificador(nombre, predeterminado):
    valor = os.getenv(nombre, predeterminado)
    if not re.fullmatch(r"[A-Za-z0-9_]+", valor):
        raise RuntimeError(f"{nombre} contiene un identificador SQL inválido")
    return valor


def qid(valor):
    return f"`{valor}`"


def init_productivo(app):
    if app.config["PRODUCTIVE_DEMO_MODE"]:
        app.extensions["productivo_engine"] = None
    else:
        url = app.config["PRODUCTION_DATABASE_URL"]
        if not url:
            raise RuntimeError(
                "Falta PRODUCTION_DATABASE_URL o hay que activar PRODUCTIVE_DEMO_MODE"
            )
        app.extensions["productivo_engine"] = crear_engine_mysql(url)

    if app.config["AUXILIARY_DEMO_MODE"]:
        app.extensions["auxiliary_engine"] = None
    else:
        auxiliary_url = app.config.get("AUXILIARY_DATABASE_URL") or app.config.get(
            "PRODUCTION_DATABASE_URL"
        )
        if not auxiliary_url:
            raise RuntimeError(
                "Falta AUXILIARY_DATABASE_URL o hay que activar AUXILIARY_DEMO_MODE"
            )
        if (
            auxiliary_url == app.config.get("PRODUCTION_DATABASE_URL")
            and app.extensions.get("productivo_engine") is not None
        ):
            app.extensions["auxiliary_engine"] = app.extensions["productivo_engine"]
        else:
            app.extensions["auxiliary_engine"] = crear_engine_mysql(auxiliary_url)


def validar_fuentes_mysql(app):
    """Comprueba las tablas externas necesarias sin escribir en ellas."""
    if app.config["PRODUCTIVE_DEMO_MODE"] or app.config["AUXILIARY_DEMO_MODE"]:
        raise RuntimeError(
            "Los modos de demostración están deshabilitados en la instalación "
            "operativa. Configurá PRODUCTIVE_DEMO_MODE=false y "
            "AUXILIARY_DEMO_MODE=false."
        )

    productivo = app.extensions["productivo_engine"]
    auxiliar = app.extensions["auxiliary_engine"]
    if productivo.dialect.name != "mysql" or auxiliar.dialect.name != "mysql":
        raise RuntimeError("Las fuentes productiva y auxiliar deben ser MySQL.")

    tablas_productivas = [
        (tabla("PIEZAS_TABLE", "produc01"), [
            identificador("PIEZA_CODIGO_COL", "GCOD_"),
            identificador("PIEZA_CLIENTE_COL", "CCOD_"),
            identificador("PIEZA_MATERIAL_COL", "MATE_"),
            identificador("PIEZA_DESCRIPCION_COL", "DESC_"),
            identificador("PIEZA_STOCK_COL", "STOK_"),
        ]),
        (tabla("ESTRUCTURA_TABLE", "produc10"), [
            identificador("ESTRUCTURA_PADRE_COL", "VCOD_"),
            identificador("ESTRUCTURA_HIJO_COL", "GCOD_"),
            identificador("ESTRUCTURA_CANTIDAD_COL", "QXUN_"),
        ]),
        (tabla("OPERACIONES_TABLE", "produc21"), [
            identificador("OPERACION_PIEZA_COL", "GCOD_"),
            identificador("OPERACION_CODIGO_COL", "OPER_"),
            identificador("OPERACION_TITULO_COL", "CTITULO_"),
        ]),
        (tabla_control_hcp(), [
            identificador("CONTROL_HCP_PIEZA_COL", "GCOD_"),
            identificador("CONTROL_HCP_OPERACION_COL", "OPER_"),
            identificador("CONTROL_HCP_LOTE_COL", "LOTE_"),
            identificador("CONTROL_HCP_NUMERO_COL", "NHCP_"),
        ]),
        (tabla_proveedores(), [
            identificador("PROVEEDOR_NUMERO_COL", "NPRV_"),
            identificador("PROVEEDOR_DESCRIPCION_COL", "DPRV_"),
        ]),
    ]
    tablas_auxiliares = [
        (tabla_auxiliar("TURNOS_TABLE", "turnos"), [
            identificador("TURNOS_ID_COL", "id"),
            identificador("TURNOS_NOMBRE_COL", "turno"),
        ]),
        (tabla_auxiliar("EQUIPOS_TABLE", "tablaequipos"), [
            identificador("EQUIPOS_NUMERO_COL", "EQPO"),
            identificador("EQUIPOS_DESCRIPCION_COL", "DESC"),
            identificador("EQUIPOS_CELULA_COL", "CELULA"),
        ]),
    ]
    _verificar_tablas(productivo, tablas_productivas, "productiva")
    _verificar_tablas(auxiliar, tablas_auxiliares, "auxiliar")


def _verificar_tablas(engine, tablas_y_columnas, origen):
    try:
        with engine.connect() as conexion:
            for nombre, columnas in tablas_y_columnas:
                seleccion = ", ".join(qid(columna) for columna in columnas)
                conexion.execute(text(f"SELECT {seleccion} FROM {nombre} LIMIT 1"))
    except Exception as exc:
        raise RuntimeError(
            f"No se pudieron verificar las tablas o columnas de la base {origen}. "
            "Revisá los nombres configurados y los permisos de lectura."
        ) from exc


def crear_engine_mysql(url):
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=5,
        connect_args={
            "charset": "utf8mb4",
            "connect_timeout": 5,
            "read_timeout": 20,
            "write_timeout": 20,
        },
    )


def engine_productivo():
    return current_app.extensions["productivo_engine"]


def engine_auxiliar():
    return current_app.extensions["auxiliary_engine"]


def modo_demo():
    return current_app.config["PRODUCTIVE_DEMO_MODE"]


def modo_demo_auxiliar():
    return current_app.config["AUXILIARY_DEMO_MODE"]


def tabla(nombre_env, predeterminado):
    schema = identificador("ERP_SCHEMA", "CGRSA")
    nombre = identificador(nombre_env, predeterminado)
    return f"{qid(schema)}.{qid(nombre)}"


def tabla_auxiliar(nombre_env, predeterminado):
    schema = identificador("AUXILIARY_SCHEMA", "AUXILIAR")
    nombre = identificador(nombre_env, predeterminado)
    return f"{qid(schema)}.{qid(nombre)}"


def tabla_proveedores():
    schema = identificador(
        "PROVEEDORES_SCHEMA",
        os.getenv("ERP_SCHEMA", "CGRSA"),
    )
    nombre = identificador("PROVEEDORES_TABLE", "controlt")
    return f"{qid(schema)}.{qid(nombre)}"


def buscar_proveedor(numero):
    numero = str(numero or "").strip()
    if not numero:
        return None
    if modo_demo():
        return next(
            (x for x in DEMO_PROVEEDORES if x["numero"] == numero),
            None,
        )

    numero_col = identificador("PROVEEDOR_NUMERO_COL", "NPRV_")
    descripcion_col = identificador("PROVEEDOR_DESCRIPCION_COL", "DPRV_")
    sql = text(
        f"""
        SELECT TRIM({qid(numero_col)}) AS numero,
               TRIM(COALESCE({qid(descripcion_col)}, '')) AS descripcion
        FROM {tabla_proveedores()}
        WHERE TRIM({qid(numero_col)}) = :numero
        LIMIT 1
        """
    )
    with engine_productivo().connect() as conexion:
        fila = conexion.execute(sql, {"numero": numero}).first()
        return dict(fila._mapping) if fila else None


def buscar_proveedores(consulta):
    consulta = str(consulta or "").strip()
    if not consulta:
        return []
    if modo_demo():
        needle = consulta.casefold()
        return [
            x
            for x in DEMO_PROVEEDORES
            if needle in x["numero"].casefold()
            or needle in x["descripcion"].casefold()
        ][:20]

    numero_col = identificador("PROVEEDOR_NUMERO_COL", "NPRV_")
    descripcion_col = identificador("PROVEEDOR_DESCRIPCION_COL", "DPRV_")
    sql = text(
        f"""
        SELECT TRIM({qid(numero_col)}) AS numero,
               TRIM(COALESCE({qid(descripcion_col)}, '')) AS descripcion
        FROM {tabla_proveedores()}
        WHERE TRIM({qid(numero_col)}) LIKE :q
           OR TRIM(COALESCE({qid(descripcion_col)}, '')) LIKE :q
        ORDER BY {qid(numero_col)}
        LIMIT 20
        """
    )
    with engine_productivo().connect() as conexion:
        return [
            dict(fila._mapping)
            for fila in conexion.execute(sql, {"q": f"%{consulta}%"})
        ]


def listar_turnos():
    if modo_demo_auxiliar():
        return DEMO_TURNOS

    id_col = identificador("TURNOS_ID_COL", "id")
    turno_col = identificador("TURNOS_NOMBRE_COL", "turno")
    sql = text(
        f"""
        SELECT {qid(id_col)} AS id,
               TRIM({qid(turno_col)}) AS turno
        FROM {tabla_auxiliar("TURNOS_TABLE", "turnos")}
        ORDER BY {qid(id_col)}
        """
    )
    with engine_auxiliar().connect() as conexion:
        return [
            {"id": int(fila.id), "turno": str(fila.turno or "").strip()}
            for fila in conexion.execute(sql)
            if str(fila.turno or "").strip()
        ]


def listar_equipos(celula):
    celula = str(celula or "").strip()
    if not celula:
        return []
    if modo_demo_auxiliar():
        return [
            equipo
            for equipo in DEMO_EQUIPOS
            if equipo["celula"].casefold() == celula.casefold()
        ]

    equipo_col = identificador("EQUIPOS_NUMERO_COL", "EQPO")
    descripcion_col = identificador("EQUIPOS_DESCRIPCION_COL", "DESC")
    celula_col = identificador("EQUIPOS_CELULA_COL", "CELULA")
    sql = text(
        f"""
        SELECT TRIM({qid(equipo_col)}) AS equipo,
               TRIM(COALESCE({qid(descripcion_col)}, '')) AS descripcion,
               TRIM({qid(celula_col)}) AS celula
        FROM {tabla_auxiliar("EQUIPOS_TABLE", "tablaequipos")}
        WHERE TRIM({qid(celula_col)}) = :celula
        ORDER BY {qid(equipo_col)}
        """
    )
    with engine_auxiliar().connect() as conexion:
        return [dict(fila._mapping) for fila in conexion.execute(sql, {"celula": celula})]


def buscar_piezas(consulta):
    if modo_demo():
        needle = consulta.lower()
        return [
            p
            for p in DEMO_PIEZAS
            if needle in p["codigo"].lower()
            or needle in p["descripcion"].lower()
            or needle in p["material"].lower()
        ][:20]

    codigo = identificador("PIEZA_CODIGO_COL", "GCOD_")
    codigo_cliente = identificador("PIEZA_CLIENTE_COL", "CCOD_")
    material = identificador("PIEZA_MATERIAL_COL", "MATE_")
    descripcion = identificador("PIEZA_DESCRIPCION_COL", "DESC_")
    stock = identificador("PIEZA_STOCK_COL", "STOK_")
    sql = text(
        f"""
        SELECT TRIM({qid(codigo)}) AS codigo,
               TRIM(COALESCE({qid(codigo_cliente)}, '')) AS codigo_cliente,
               TRIM(COALESCE({qid(material)}, '')) AS material,
               TRIM(COALESCE({qid(descripcion)}, '')) AS descripcion,
               COALESCE({qid(stock)}, 0) AS stock
        FROM {tabla("PIEZAS_TABLE", "produc01")}
        WHERE TRIM({qid(codigo)}) LIKE :q
           OR TRIM(COALESCE({qid(descripcion)}, '')) LIKE :q
           OR TRIM(COALESCE({qid(material)}, '')) LIKE :q
        ORDER BY {qid(codigo)}
        LIMIT 20
        """
    )
    with engine_productivo().connect() as conexion:
        return [
            dict(fila._mapping)
            for fila in conexion.execute(sql, {"q": f"%{consulta}%"})
        ]


def obtener_estructura(codigo_padre):
    if modo_demo():
        resultado = []

        def recorrer(padre, nivel, ruta):
            if nivel > 10:
                return
            for item in DEMO_ESTRUCTURA.get(padre, []):
                maestro = next(
                    (pieza for pieza in DEMO_PIEZAS if pieza["codigo"] == item["codigo"]),
                    {},
                )
                resultado.append(
                    {
                        **item,
                        "codigo_cliente": maestro.get("codigo_cliente", ""),
                        "material": maestro.get("material", ""),
                        "descripcion": maestro.get(
                            "descripcion", item.get("descripcion", "")
                        ),
                        "padre": padre,
                        "nivel": nivel,
                    }
                )
                if item["codigo"] not in ruta:
                    recorrer(item["codigo"], nivel + 1, ruta | {item["codigo"]})

        recorrer(codigo_padre, 1, {codigo_padre})
        return resultado

    padre = identificador("ESTRUCTURA_PADRE_COL", "VCOD_")
    hijo = identificador("ESTRUCTURA_HIJO_COL", "GCOD_")
    cantidad = identificador("ESTRUCTURA_CANTIDAD_COL", "QXUN_")
    codigo = identificador("PIEZA_CODIGO_COL", "GCOD_")
    codigo_cliente = identificador("PIEZA_CLIENTE_COL", "CCOD_")
    material = identificador("PIEZA_MATERIAL_COL", "MATE_")
    descripcion = identificador("PIEZA_DESCRIPCION_COL", "DESC_")
    sql = text(
        f"""
        SELECT TRIM(e.{qid(padre)}) AS padre,
               TRIM(e.{qid(hijo)}) AS codigo,
               TRIM(COALESCE(p.{qid(codigo_cliente)}, '')) AS codigo_cliente,
               TRIM(COALESCE(p.{qid(material)}, '')) AS material,
               TRIM(COALESCE(p.{qid(descripcion)}, '')) AS descripcion,
               COALESCE(e.{qid(cantidad)}, 1) AS uso
        FROM {tabla("ESTRUCTURA_TABLE", "produc10")} e
        INNER JOIN {tabla("PIEZAS_TABLE", "produc01")} p
          ON TRIM(p.{qid(codigo)}) = TRIM(e.{qid(hijo)})
        WHERE TRIM(e.{qid(padre)}) = :padre
        ORDER BY e.{qid(hijo)}
        """
    )
    resultado = []

    def recorrer(conexion, codigo_actual, nivel, ruta):
        if nivel > 10:
            return
        for fila in conexion.execute(sql, {"padre": codigo_actual}):
            item = dict(fila._mapping)
            item["nivel"] = nivel
            item["uso"] = float(item["uso"] or 1)
            resultado.append(item)
            if item["codigo"] not in ruta:
                recorrer(
                    conexion,
                    item["codigo"],
                    nivel + 1,
                    ruta | {item["codigo"]},
                )

    with engine_productivo().connect() as conexion:
        recorrer(conexion, codigo_padre, 1, {codigo_padre})
    return resultado


def obtener_componentes_finales(codigo_padre):
    """Explota una pieza hasta las hojas de su estructura.

    Devuelve una fila consolidada por componente final. ``factor`` es la
    cantidad total del componente necesaria por unidad del código padre. Si la
    pieza no tiene estructura, se considera a sí misma como componente final.
    """
    codigo_padre = str(codigo_padre or "").strip()
    if not codigo_padre:
        return []

    estructura = obtener_estructura(codigo_padre)
    if not estructura:
        return [{
            "codigo": codigo_padre,
            "descripcion": "",
            "material": "",
            "codigo_cliente": "",
            "factor": Decimal("1"),
            "nivel": 0,
        }]

    hijos = defaultdict(list)
    maestros = {}
    aristas_vistas = set()
    for fila in estructura:
        padre = str(fila.get("padre") or "").strip()
        codigo = str(fila.get("codigo") or "").strip()
        if not padre or not codigo:
            continue
        uso = Decimal(str(fila.get("uso") or 1))
        arista = (padre, codigo, uso)
        if arista in aristas_vistas:
            continue
        aristas_vistas.add(arista)
        hijos[padre].append((codigo, uso))
        maestros[codigo] = {
            "descripcion": str(fila.get("descripcion") or "").strip(),
            "material": str(fila.get("material") or "").strip(),
            "codigo_cliente": str(fila.get("codigo_cliente") or "").strip(),
        }

    acumulados = defaultdict(lambda: Decimal("0"))
    niveles = {}

    def recorrer(codigo, factor, nivel, ruta):
        descendientes = hijos.get(codigo, [])
        if not descendientes or nivel >= 10:
            acumulados[codigo] += factor
            niveles[codigo] = max(niveles.get(codigo, 0), nivel)
            return
        for hijo, uso in descendientes:
            if hijo in ruta:
                # Una estructura circular no debe bloquear el reporte. Se
                # corta la rama y se deja el último código como hoja visible.
                acumulados[hijo] += factor * uso
                niveles[hijo] = max(niveles.get(hijo, 0), nivel + 1)
                continue
            recorrer(hijo, factor * uso, nivel + 1, ruta | {hijo})

    recorrer(codigo_padre, Decimal("1"), 0, {codigo_padre})
    return [
        {
            "codigo": codigo,
            "descripcion": maestros.get(codigo, {}).get("descripcion", ""),
            "material": maestros.get(codigo, {}).get("material", ""),
            "codigo_cliente": maestros.get(codigo, {}).get("codigo_cliente", ""),
            "factor": factor,
            "nivel": niveles.get(codigo, 0),
        }
        for codigo, factor in sorted(acumulados.items())
    ]


def buscar_operaciones(consulta):
    if modo_demo():
        needle = consulta.lower()
        return [
            op
            for op in DEMO_OPERACIONES
            if needle in op["codigo"].lower() or needle in op["titulo"].lower()
        ][:20]

    codigo = identificador("OPERACION_CODIGO_COL", "OPER_")
    titulo = identificador("OPERACION_TITULO_COL", "CTITULO_")
    sql = text(
        f"""
        SELECT DISTINCT TRIM({qid(codigo)}) AS codigo,
                        TRIM(COALESCE({qid(titulo)}, '')) AS titulo
        FROM {tabla("OPERACIONES_TABLE", "produc21")}
        WHERE TRIM({qid(codigo)}) LIKE :q
           OR TRIM(COALESCE({qid(titulo)}, '')) LIKE :q
        ORDER BY {qid(codigo)}
        LIMIT 20
        """
    )
    with engine_productivo().connect() as conexion:
        return [
            dict(fila._mapping)
            for fila in conexion.execute(sql, {"q": f"%{consulta}%"})
        ]


def listar_operaciones_pieza(codigo_pieza):
    codigo_pieza = str(codigo_pieza or "").strip()
    if not codigo_pieza:
        return []

    if modo_demo():
        operaciones = DEMO_OPERACIONES_POR_PIEZA.get(codigo_pieza, []).copy()
    else:
        pieza_col = identificador("OPERACION_PIEZA_COL", "GCOD_")
        codigo_col = identificador("OPERACION_CODIGO_COL", "OPER_")
        titulo_col = identificador("OPERACION_TITULO_COL", "CTITULO_")

        sql = text(
            f"""
            SELECT DISTINCT
                TRIM({qid(codigo_col)}) AS codigo,
                TRIM(COALESCE({qid(titulo_col)}, '')) AS titulo
            FROM {tabla("OPERACIONES_TABLE", "produc21")}
            WHERE TRIM({qid(pieza_col)}) = :pieza
              AND TRIM(COALESCE({qid(codigo_col)}, '')) <> ''
            ORDER BY {qid(codigo_col)}
            """
        )

        with engine_productivo().connect() as conexion:
            operaciones = [
                dict(fila._mapping)
                for fila in conexion.execute(sql, {"pieza": codigo_pieza})
            ]

    return operaciones


def tabla_control_hcp():
    schema = identificador(
        "CONTROL_HCP_SCHEMA",
        os.getenv("ERP_SCHEMA", "CGRSA"),
    )
    nombre = identificador("CONTROL_HCP_TABLE", "controlo")
    return f"{qid(schema)}.{qid(nombre)}"


def validar_hcp(codigo_pieza, operacion, hcp, es_materia_prima=False):
    codigo_pieza = str(codigo_pieza or "").strip()
    operacion = str(operacion or "").strip()
    hcp = str(hcp or "").strip()
    if not codigo_pieza or not hcp:
        return None
    if modo_demo():
        if not re.fullmatch(r"\d{6}", hcp):
            return None
        return {
            "codigo": codigo_pieza,
            "operacion": operacion,
            "hcp": hcp,
            "tipo": "LOTE" if es_materia_prima else "HCP",
        }

    pieza_col = identificador("CONTROL_HCP_PIEZA_COL", "GCOD_")
    operacion_col = identificador("CONTROL_HCP_OPERACION_COL", "OPER_")
    lote_col = identificador("CONTROL_HCP_LOTE_COL", "LOTE_")
    hcp_col = identificador("CONTROL_HCP_NUMERO_COL", "NHCP_")
    identificador_col = lote_col if es_materia_prima else hcp_col
    
    if not es_materia_prima and hcp.isdigit():
        condicion_identificador = (
            f"CAST(COALESCE({qid(identificador_col)}, 0) AS UNSIGNED) = :hcp_numero"
        )
    else:
        condicion_identificador = (
            f"TRIM(COALESCE({qid(identificador_col)}, '')) = :hcp"
        )
    sql = text(
        f"""
        SELECT TRIM({qid(pieza_col)}) AS codigo,
               TRIM(COALESCE({qid(operacion_col)}, '')) AS operacion,
               TRIM(COALESCE({qid(hcp_col)}, '')) AS hcp,
               TRIM(COALESCE({qid(lote_col)}, '')) AS lote
        FROM {tabla_control_hcp()}
        WHERE TRIM({qid(pieza_col)}) = :codigo
          AND {condicion_identificador}
        LIMIT 1
        """
    )
    parametros = {"codigo": codigo_pieza}
    if not es_materia_prima and hcp.isdigit():
        parametros["hcp_numero"] = int(hcp)
    else:
        parametros["hcp"] = hcp
    with engine_productivo().connect() as conexion:
        fila = conexion.execute(sql, parametros).first()
        return dict(fila._mapping) if fila else None


def normalizar_operacion(valor):
    """Compara códigos de operación textuales sin perder los no numéricos."""
    codigo = str(valor or "").strip().upper()
    return (codigo.lstrip("0") or "0") if re.fullmatch(r"[0-9]+", codigo) else codigo


def produccion_por_operacion(desde, hasta):
    """Piezas buenas por fecha, código y operación; exclusivamente SELECT."""
    from datetime import timedelta

    if modo_demo():
        return []  # No inventar cantidades productivas para calcular porcentajes.
    fecha = identificador("PRODUCCION_FECHA_COL", "FPRO_")
    cantidad = identificador("PRODUCCION_CANTIDAD_COL", "CANT_")
    operacion = identificador("PRODUCCION_OPERACION_COL", "NPRO_")
    pieza = identificador("PRODUCCION_PIEZA_COL", "GCOD_")
    sql = text(f"""
        SELECT DATE({qid(fecha)}) AS fecha,
               TRIM({qid(pieza)}) AS codigo,
               TRIM({qid(operacion)}) AS operacion,
               SUM({qid(cantidad)}) AS cantidad,
               COUNT(*) - COUNT({qid(cantidad)}) AS sin_cantidad
        FROM {tabla("PRODUCCION_TABLE", "produc04")}
        WHERE {qid(fecha)} >= :desde AND {qid(fecha)} < :hasta
        GROUP BY DATE({qid(fecha)}), TRIM({qid(pieza)}), TRIM({qid(operacion)})
        ORDER BY fecha, codigo, operacion
    """)
    with engine_productivo().connect() as conexion:
        return [dict(fila._mapping) for fila in conexion.execute(
            sql, {"desde": desde, "hasta": hasta + timedelta(days=1)}
        )]
