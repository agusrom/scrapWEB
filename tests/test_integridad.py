"""Regresiones de integridad: solicitudes reales y persistencia en ambos motores."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from app import (Declaracion, DeclaracionItem, Motivo, RetrabajoIntervencion,
                 Usuario, create_app, db)
from validaciones import decimal_no_negativo


@pytest.fixture(scope="module")
def mysql_server():
    valor = os.getenv("SCRAPWEB_MYSQL_TEST_SERVER")
    if not valor:
        pytest.skip("Definí SCRAPWEB_MYSQL_TEST_SERVER para ejecutar contra MySQL real")
    url = make_url(valor)
    assert url.drivername == "mysql+pymysql" and not url.database, "Usar un servidor de pruebas sin base en la URL"
    engine = create_engine(url)
    yield engine, url
    engine.dispose()


@pytest.fixture(params=["sqlite", "mysql"])
def sistema(request):
    engine = None
    nombre = None
    if request.param == "mysql":
        engine, url = request.getfixturevalue("mysql_server")
        nombre = "dnc_test_" + uuid4().hex
        with engine.begin() as c:
            c.execute(text(f"CREATE DATABASE `{nombre}` CHARACTER SET utf8mb4"))
        uri = url.set(database=nombre)
    else:
        uri = "sqlite:///:memory:"
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": uri,
                      "SECRET_KEY": "test-integridad", "AUTH_DISABLED": True})
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    if nombre:
        with engine.begin() as c:
            c.execute(text(f"DROP DATABASE `{nombre}`"))


def crear_dnc(app, filas=1, validada=True, intervencion=False, logistica=False):
    with app.app_context():
        motivo = db.session.execute(db.select(Motivo).where(Motivo.codigo == "D3")).scalar_one()
        dnc = Declaracion(fecha=date(2026, 1, 5), sector_declara="Producción",
            celula_detecta="Célula 0001", legajo_declara="123", equipo="101",
            lugar_detectado="Célula 0001", estado="PENDIENTE_RETRABAJO" if validada else "PENDIENTE_CALIDAD",
            fecha_validacion=datetime(2026, 1, 5) if validada else None)
        for _ in range(filas):
            item = DeclaracionItem(tipo_material="COMPONENTE", codigo_pieza="CH-1110",
                descripcion="Chapa", trazabilidad="123456", unidad="PZS",
                cantidad_detectada=10, cantidad_scrap_directo=2 if validada else 0,
                cantidad_a_retrabajo=8 if validada else 0, cantidad_liberada=0,
                motivo_id=motivo.id, sector_origen="Producción", celula_origen="Retrabajo",
                operacion_origen="Reparar", tipo_imputacion="CONFIRMADA",
                responsabilidad_estado="NO_ATRIBUIBLE", requiere_validacion_logistica=logistica)
            if intervencion:
                item.intervenciones.append(RetrabajoIntervencion(fecha=date(2026, 1, 6),
                    operacion="Reparar", celula="Retrabajo", legajo="123", minutos=5,
                    cantidad_personas=1, cantidad_ok=3, cantidad_scrap=1, motivo_scrap_id=motivo.id))
            if logistica:
                item.cantidad_scrap_validada_logistica = 2
                item.legajo_logistica = "123"
                item.fecha_validacion_logistica = datetime(2026, 1, 6)
            dnc.items.append(item)
        db.session.add(dnc)
        db.session.flush()
        dnc.numero = f"DNC-{dnc.id:06d}"
        db.session.commit()
        return dnc.id, [i.id for i in dnc.items], motivo.id


def calidad_form(ids, motivo, scrap=2, retrabajo=8, liberada=0):
    form = {"legajo_calidad": "900"}
    for i in ids:
        form.update({f"scrap_{i}": str(scrap), f"retrabajo_{i}": str(retrabajo),
            f"liberada_{i}": str(liberada), f"motivo_{i}": str(motivo),
            f"resp_estado_{i}": "NO_ATRIBUIBLE", f"obs_item_{i}": "Reparar"})
    return form


def admin_form(app, dnc_id):
    with app.app_context():
        d = db.session.get(Declaracion, dnc_id)
        form = {"fecha": d.fecha.isoformat(), "sector_declara": d.sector_declara,
                "celula_detecta": d.celula_detecta, "legajo_declara": d.legajo_declara,
                "equipo": d.equipo}
        campos = ["tipo_material", "codigo_pieza", "descripcion", "trazabilidad", "unidad",
            "cantidad_detectada", "cantidad_scrap_directo", "cantidad_a_retrabajo", "cantidad_liberada",
            "motivo_id", "tipo_imputacion", "tipo_origen", "sector_origen", "celula_origen",
            "operacion_origen", "responsabilidad_estado"]
        for i in d.items:
            for campo in campos:
                form[f"item_{i.id}_{campo}"] = str(getattr(i, campo) if getattr(i, campo) is not None else "")
            if i.requiere_validacion_logistica:
                form[f"item_{i.id}_requiere_validacion_logistica"] = "1"
                form[f"item_{i.id}_cantidad_scrap_validada_logistica"] = str(i.cantidad_scrap_validada_logistica)
                form[f"item_{i.id}_legajo_logistica"] = i.legajo_logistica
        return form


@pytest.mark.parametrize("valor", ["NaN", "sNaN", "Infinity", "-Infinity", "-1", "0.0001", "1000000000", "1e10000", "texto"])
def test_cantidades_no_representables(valor):
    with pytest.raises(ValueError):
        decimal_no_negativo(valor, "La cantidad")


def test_limites_exactos_mysql():
    assert decimal_no_negativo("999999999.999", "Cantidad") == Decimal("999999999.999")
    assert decimal_no_negativo("0.001", "Cantidad") == Decimal("0.001")
    assert decimal_no_negativo("99999999.9999", "Uso", escala=4) == Decimal("99999999.9999")


@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-1", "1.5", "1000000000", ""])
def test_calidad_rechaza_cantidad_y_revierte_todos_los_renglones(sistema, valor):
    d, ids, motivo = crear_dnc(sistema, filas=2, validada=False)
    form = calidad_form(ids, motivo)
    form[f"scrap_{ids[1]}"] = valor
    response = sistema.test_client().post(f"/calidad/{d}/validar", data=form)
    assert response.status_code < 500
    with sistema.app_context():
        dnc = db.session.get(Declaracion, d)
        assert dnc.fecha_validacion is None
        assert all(i.cantidad_scrap_directo == 0 for i in dnc.items)


def test_calidad_no_puede_reducir_resultados_ya_procesados(sistema):
    d, ids, motivo = crear_dnc(sistema, intervencion=True)
    response = sistema.test_client().post(f"/calidad/{d}/validar", data=calidad_form(ids, motivo, 8, 2))
    assert "ya fue procesada" in response.get_data(as_text=True)
    with sistema.app_context():
        item = db.session.get(DeclaracionItem, ids[0])
        assert item.cantidad_a_retrabajo == 8
        assert item.cantidad_retrabajo_resuelta == 4


def test_admin_reabre_logistica_sin_reutilizar_la_validacion_anterior(sistema):
    d, ids, _ = crear_dnc(sistema, logistica=True)
    form = admin_form(sistema, d)
    form[f"item_{ids[0]}_cantidad_scrap_directo"] = "3"
    form[f"item_{ids[0]}_cantidad_a_retrabajo"] = "7"
    assert sistema.test_client().post(f"/declaraciones/{d}/editar", data=form).status_code == 302
    with sistema.app_context():
        item = db.session.get(DeclaracionItem, ids[0])
        assert item.fecha_validacion_logistica is None
        assert item.cantidad_scrap_validada_logistica is None
        assert item.declaracion.estado == "PENDIENTE_LOGISTICA"
        assert item.declaracion.numero == f"DNC-{d:06d}"


def test_admin_no_reduce_retrabajo_procesado(sistema):
    d, ids, _ = crear_dnc(sistema, intervencion=True)
    form = admin_form(sistema, d)
    form[f"item_{ids[0]}_cantidad_scrap_directo"] = "8"
    form[f"item_{ids[0]}_cantidad_a_retrabajo"] = "2"
    response = sistema.test_client().post(f"/declaraciones/{d}/editar", data=form)
    assert "ya fue procesada" in response.get_data(as_text=True)
    with sistema.app_context():
        assert db.session.get(DeclaracionItem, ids[0]).cantidad_a_retrabajo == 8


def test_retrabajo_no_duplica_scrap_y_no_requiere_logistica_adicional(sistema):
    d, ids, _ = crear_dnc(sistema, intervencion=True)
    form = {"fecha": "2026-01-07", "operacion": "Reparación final", "celula": "Retrabajo",
        "legajo": "123", "minutos": "5", "cantidad_personas": "1", "cantidad_ok": "3", "cantidad_scrap": "1"}
    client = sistema.test_client()
    assert client.post(f"/retrabajos/{ids[0]}/registrar", data=form).status_code == 302
    assert client.post(f"/retrabajos/{ids[0]}/registrar", data=form).status_code == 400
    with sistema.app_context():
        item = db.session.get(DeclaracionItem, ids[0])
        assert item.cantidad_scrap_total == 4  # 2 directo + 1 + 1 posterior
        assert item.cantidad_recuperada == 6
        assert item.cantidad_retrabajo_pendiente == 0
        assert not item.requiere_validacion_logistica
        assert item.declaracion.estado == "CERRADA"
    assert client.get(f"/declaraciones/{d}?imprimir=1").status_code == 200
    excel = client.get("/reportes/scrap/excel?mes=2026-01")
    wb = load_workbook(BytesIO(excel.data))
    row = list(wb["Resumen por componente"].values)[1]
    assert row[4:7] == (2, 2, 4)
    assert any("vigente" in str(c.value) for row in wb["Filtros aplicados"] for c in row)


@pytest.mark.parametrize("payload", [{}, [None], [1], "texto"])
def test_json_malformado_no_genera_500(sistema, payload):
    response = sistema.test_client().post("/produccion/alerta", data={"items_json": json.dumps(payload)})
    assert response.status_code == 400


def test_alerta_no_acepta_destinos_ni_retrabajos_del_cliente(sistema):
    with sistema.app_context():
        motivo = db.session.execute(db.select(Motivo.id).where(Motivo.codigo == "D3")).scalar_one()
    item = {"cantidad_detectada": 10, "cantidad_scrap_directo": 10, "motivo_id": motivo}
    response = sistema.test_client().post("/produccion/alerta", data={"fecha": "2026-01-01",
        "celula_detecta": "Célula 0001", "legajo_declara": "123", "turno_id": "1", "equipo": "101",
        "items_json": json.dumps([item])})
    assert response.status_code == 400
    assert "definida por Calidad" in response.get_data(as_text=True)
    with sistema.app_context():
        assert db.session.execute(db.select(db.func.count(Declaracion.id))).scalar_one() == 0


@pytest.mark.parametrize("mes", ["incorrecto", "0000-01", "2026-13", "2026-00"])
def test_filtros_invalidos_no_rompen_reportes(sistema, mes):
    assert sistema.test_client().get("/reportes/scrap", query_string={"mes": mes}).status_code == 200


def test_excel_conserva_textos_sin_ejecutar_formulas(sistema):
    crear_dnc(sistema)
    with sistema.app_context():
        item = db.session.execute(db.select(DeclaracionItem)).scalar_one()
        item.descripcion = '=HYPERLINK("https://example.com")'
        db.session.commit()
    response = sistema.test_client().get("/reportes/scrap/excel?mes=2026-01")
    wb = load_workbook(BytesIO(response.data), data_only=False)
    cell = wb["Detalle trazable"]["I2"]
    assert cell.value.startswith("=HYPERLINK") and cell.data_type == "s"


def app_auth():
    return create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-auth", "AUTH_DISABLED": False})


@pytest.mark.parametrize("rol", ["produccion", "calidad", "logistica", "admin"])
def test_permisos_servidor_y_json_sin_sesion_o_vencida(rol):
    app = app_auth()
    client = app.test_client()
    assert client.get("/api/piezas?q=CH").status_code == 401
    assert client.get("/api/piezas?q=CH").is_json
    client.post("/login", data={"usuario": rol, "clave": rol})
    allowed = {"produccion": "/produccion", "calidad": "/calidad", "logistica": "/logistica", "admin": "/gestion"}
    assert client.get(allowed[rol]).status_code == 200
    for path in ["/declaraciones/1/editar", "/declaraciones/1/eliminar", "/calidad/1/validar", "/logistica/validaciones/1"]:
        permitted = rol == "admin" or rol == "calidad" and path.startswith("/calidad/") or rol == "logistica" and path.startswith("/logistica/")
        response = client.post(path, headers={"X-Requested-With": "fetch"})
        if not permitted:
            assert response.status_code == 403 and response.is_json
    with client.session_transaction() as session:
        inicio = session["sesion_iniciada_en"]
    client.get("/api/piezas?q=CH")
    with client.session_transaction() as session:
        assert session["sesion_iniciada_en"] == inicio
        session["sesion_iniciada_en"] = time.time() - 301
    response = client.get(allowed[rol] + "/contenido", headers={"X-Requested-With": "fetch"})
    assert response.status_code == 401 and response.get_json()["error"] == "sesion_vencida"
    assert client.get("/api/piezas?q=CH").status_code == 401


def test_produccion_no_puede_decidir_destinos_por_url_antigua():
    app = app_auth()
    client = app.test_client()
    client.post("/login", data={"usuario": "produccion", "clave": "produccion"})
    assert client.get("/produccion/nueva/SCRAP").location.endswith("/produccion/alerta")
    assert client.post("/produccion/nueva/SCRAP", data={}).status_code == 403


def test_arranque_rechaza_sqlite_sin_crear_archivo(tmp_path, monkeypatch):
    archivo = tmp_path / "no_crear.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{archivo}")
    with pytest.raises(RuntimeError, match="debe apuntar a MySQL"):
        create_app()
    assert not archivo.exists()


def test_arranque_rechaza_autenticacion_deshabilitada(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")
    with pytest.raises(RuntimeError, match="autenticación"):
        create_app()


def test_mysql_operativo_reinicia_sin_ddl_ni_semillas_y_externas_solo_lectura(mysql_server, monkeypatch):
    from sqlalchemy.exc import DBAPIError

    engine, server_url = mysql_server
    sufijo = uuid4().hex[:16]
    nombre = "dnc_test_" + sufijo
    externa = "erp_test_" + sufijo
    usuario = "lectura_" + sufijo
    with engine.begin() as c:
        c.execute(text(f"CREATE DATABASE `{nombre}` CHARACTER SET utf8mb4"))
        c.execute(text(f"CREATE DATABASE `{externa}` CHARACTER SET utf8mb4"))
        # Siete fuentes sintéticas: nunca se conecta a bases de la instalación.
        for tabla, columnas in {
            "produc01": "GCOD_ VARCHAR(50), CCOD_ VARCHAR(50), MATE_ VARCHAR(80), `DESC_` VARCHAR(255), STOK_ DECIMAL(12,3)",
            "produc10": "VCOD_ VARCHAR(50), GCOD_ VARCHAR(50), QXUN_ DECIMAL(12,4)",
            "produc21": "GCOD_ VARCHAR(50), OPER_ VARCHAR(30), CTITULO_ VARCHAR(160)",
            "controlo": "GCOD_ VARCHAR(50), OPER_ VARCHAR(30), LOTE_ VARCHAR(6), NHCP_ VARCHAR(6)",
            "controlt": "NPRV_ VARCHAR(30), DPRV_ VARCHAR(120)",
            "turnos": "id INTEGER, turno VARCHAR(80)",
            "tablaequipos": "EQPO VARCHAR(80), `DESC` VARCHAR(160), CELULA VARCHAR(80)",
        }.items():
            c.execute(text(f"CREATE TABLE `{externa}`.`{tabla}` ({columnas})"))
        c.execute(text(f"INSERT INTO `{externa}`.produc01 VALUES ('CH-1110', '', 'CHAPA', 'Chapa de prueba', 10)"))
        c.execute(text(f"CREATE USER '{usuario}'@'%' IDENTIFIED BY ''"))
        c.execute(text(f"GRANT SELECT ON `{externa}`.* TO '{usuario}'@'%'"))
        # Se aplica el DDL entregado por el proyecto, explícitamente fuera del arranque.
        for sentencia in Path("estructura_mysql.sql").read_text().split(";"):
            if sentencia.strip():
                c.execute(text(f"USE `{nombre}`"))
                c.execute(text(sentencia))
    url = server_url.set(database=nombre)
    lectura = server_url.set(username=usuario, password=None, database=externa)
    seeded = None
    apps = []
    registro = []

    def registrar(conn, cursor, statement, parameters, context, executemany):
        registro.append(statement.lstrip().upper())

    try:
        # Los datos iniciales se preparan en la prueba, nunca en el arranque operativo.
        seeded = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": url,
                             "SECRET_KEY": "test", "AUTH_DISABLED": True})
        d, ids, _ = crear_dnc(seeded, intervencion=True)
        for clave, valor in {
            "DATABASE_URL": url.render_as_string(hide_password=False),
            "PRODUCTION_DATABASE_URL": lectura.render_as_string(hide_password=False),
            "AUXILIARY_DATABASE_URL": lectura.render_as_string(hide_password=False),
            "ERP_SCHEMA": externa, "AUXILIARY_SCHEMA": externa, "CONTROL_HCP_SCHEMA": externa,
            "PROVEEDORES_SCHEMA": externa, "PRODUCTIVE_DEMO_MODE": "false",
            "AUXILIARY_DEMO_MODE": "false", "AUTH_DISABLED": "false", "SECRET_KEY": "test-only",
        }.items():
            monkeypatch.setenv(clave, valor)
        event.listen(type(engine), "before_cursor_execute", registrar)
        for _ in range(2):
            app = create_app()
            apps.append(app)
            with app.app_context():
                actual = db.session.get(DeclaracionItem, ids[0])
                assert actual.cantidad_scrap_total == 3
                assert actual.cantidad_recuperada == 3
                assert actual.declaracion.numero == f"DNC-{d:06d}"
                assert db.session.execute(db.select(db.func.count(Declaracion.id))).scalar_one() == 1
                assert db.session.execute(db.select(db.func.count(Usuario.id))).scalar_one() == 4
            client = app.test_client()
            assert client.post("/login", data={"usuario": "admin", "clave": "admin"}).status_code == 302
            assert client.get(f"/declaraciones/{d}?imprimir=1").status_code == 200
            assert client.get("/api/piezas?q=CH").get_json()[0]["codigo"] == "CH-1110"
            assert client.get("/reportes/scrap/excel?mes=2026-01").status_code == 200
        assert registro
        assert all(sql.startswith(("SELECT", "SHOW", "DESCRIBE")) for sql in registro), registro
        event.remove(type(engine), "before_cursor_execute", registrar)
        with apps[-1].extensions["productivo_engine"].begin() as c:
            with pytest.raises(DBAPIError):
                c.execute(text(f"UPDATE `{externa}`.produc01 SET STOK_ = 0"))
    finally:
        if event.contains(type(engine), "before_cursor_execute", registrar):
            event.remove(type(engine), "before_cursor_execute", registrar)
        for app in ([seeded] if seeded else []) + apps:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
            for key in ["productivo_engine", "auxiliary_engine"]:
                if app.extensions.get(key) is not None:
                    app.extensions[key].dispose()
        with engine.begin() as c:
            c.execute(text(f"DROP DATABASE `{nombre}`"))
            c.execute(text(f"DROP DATABASE `{externa}`"))
            c.execute(text(f"DROP USER '{usuario}'@'%'"))


def test_mysql_dos_operadores_no_cierran_dos_veces_el_mismo_retrabajo(mysql_server):
    engine, server_url = mysql_server
    nombre = "dnc_test_" + uuid4().hex
    with engine.begin() as c:
        c.execute(text(f"CREATE DATABASE `{nombre}` CHARACTER SET utf8mb4"))
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": server_url.set(database=nombre),
                      "SECRET_KEY": "test", "AUTH_DISABLED": True})
    try:
        d, ids, _ = crear_dnc(app)
        from threading import Barrier
        inicio = Barrier(2)

        def guardar():
            inicio.wait(timeout=10)
            return app.test_client().post(f"/retrabajos/{ids[0]}/registrar", data={
                "fecha": "2026-01-07", "operacion": "Reparar", "celula": "Retrabajo",
                "legajo": "123", "minutos": "1", "cantidad_personas": "1",
                "cantidad_ok": "6", "cantidad_scrap": "2"}).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(lambda _: guardar(), range(2)))
        assert sorted(resultados) == [302, 400]
        with app.app_context():
            item = db.session.get(DeclaracionItem, ids[0])
            assert len(item.intervenciones) == 1
            assert item.cantidad_retrabajo_resuelta == 8
            assert item.cantidad_scrap_total == 4
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        with engine.begin() as c:
            c.execute(text(f"DROP DATABASE `{nombre}`"))


def test_admin_conserva_decimales_historicos_en_unidades_no_piezas(sistema):
    d, ids, _ = crear_dnc(sistema)
    with sistema.app_context():
        item = db.session.get(DeclaracionItem, ids[0])
        item.unidad = "KG"
        item.cantidad_detectada = Decimal("1.250")
        item.cantidad_scrap_directo = Decimal("0.250")
        item.cantidad_a_retrabajo = Decimal("1.000")
        db.session.commit()
    form = admin_form(sistema, d)
    assert sistema.test_client().post(f"/declaraciones/{d}/editar", data=form).status_code == 302
    with sistema.app_context():
        assert db.session.get(DeclaracionItem, ids[0]).cantidad_detectada == Decimal("1.250")


def test_admin_no_transforma_documentos_anteriores_en_alertas(sistema):
    d, ids, _ = crear_dnc(sistema)
    with sistema.app_context():
        db.session.get(Declaracion, d).fecha_validacion = None  # flujo anterior a Calidad
        db.session.commit()
    form = admin_form(sistema, d)
    assert sistema.test_client().post(f"/declaraciones/{d}/editar", data=form).status_code == 302
    with sistema.app_context():
        assert db.session.get(Declaracion, d).estado == "PENDIENTE_RETRABAJO"


def test_admin_exige_justificacion_de_diferencia_logistica(sistema):
    d, ids, _ = crear_dnc(sistema, logistica=True)
    form = admin_form(sistema, d)
    form[f"item_{ids[0]}_cantidad_scrap_validada_logistica"] = "1"
    response = sistema.test_client().post(f"/declaraciones/{d}/editar", data=form)
    assert "Explicá la diferencia" in response.get_data(as_text=True)
    with sistema.app_context():
        assert db.session.get(DeclaracionItem, ids[0]).cantidad_scrap_validada_logistica == 2
