"""Carga directa de scrap por Calidad y restricciones del nuevo flujo."""
import json
from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app import Celula, Declaracion, DeclaracionItem, Motivo, PiezaControlLogistica, db
from test_integridad import mysql_server, sistema  # noqa: F401


def formulario_calidad(app, **cambios):
    with app.app_context():
        motivo = db.session.execute(db.select(Motivo).where(Motivo.codigo == "D3-POR")).scalar_one()
        item = {"tipo_material": "COMPONENTE", "codigo": "CH-1110", "descripcion": "Chapa probeta",
            "trazabilidad": "123456", "unidad": "PZS", "cantidad_detectada": 3,
            "cantidad_scrap_directo": 3, "cantidad_a_retrabajo": 0,
            "cantidad_liberada": 0, "motivo_id": motivo.id, "grupo_id": motivo.grupo_id,
            "tipo_origen": "INTERNO", "sector_origen": "Calidad", "celula_origen": "Calidad",
            "operacion_origen": "Ensayo de soldadura", "tipo_imputacion": "CONFIRMADA",
            "observacion": "Corte de probeta de soldadura"}
    item.update(cambios)
    return {"fecha": date.today().isoformat(), "celula_detecta": "Calidad", "turno_id": "1",
            "equipo": "301", "legajo_declara": "123", "items_json": json.dumps([item])}


def ingresar(app, usuario="calidad"):
    app.config["AUTH_DISABLED"] = False
    client = app.test_client()
    assert client.post("/login", data={"usuario": usuario, "clave": usuario}).status_code == 302
    return client


@pytest.mark.parametrize("usuario", ["produccion", "logistica"])
def test_otros_roles_no_crean_scrap_calidad_por_url(sistema, usuario):
    client = ingresar(sistema, usuario)
    assert client.get("/calidad/scrap/nuevo").status_code == 403
    assert client.post("/calidad/scrap/nuevo", data=formulario_calidad(sistema)).status_code == 403
    with sistema.app_context():
        assert db.session.execute(db.select(db.func.count(Declaracion.id))).scalar_one() == 0


def test_calidad_y_admin_ven_acceso_y_celula_restringida(sistema):
    for usuario in ("calidad", "admin"):
        client = ingresar(sistema, usuario)
        assert "Declarar scrap" in client.get("/calidad").get_data(as_text=True)
        page = client.get("/calidad/scrap/nuevo")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        selector = html.split('id="prod-celula"', 1)[1].split('</select>', 1)[0]
        assert 'value="Calidad"' in selector
        assert 'value="Célula 0001"' not in selector


@pytest.mark.parametrize("campo,valor", [("celula_detecta", "Célula 0001"), ("equipo", "101"),
    ("turno_id", "999"), ("legajo_declara", ""), ("legajo_declara", "abc")])
def test_rechaza_celula_equipo_turno_y_legajo_manipulados(sistema, campo, valor):
    client = ingresar(sistema)
    form = formulario_calidad(sistema)
    form[campo] = valor
    assert client.post("/calidad/scrap/nuevo", data=form).status_code == 400
    with sistema.app_context():
        assert db.session.execute(db.select(db.func.count(Declaracion.id))).scalar_one() == 0


@pytest.mark.parametrize("cambios", [{"cantidad_detectada": 0}, {"cantidad_detectada": -1},
    {"cantidad_detectada": 1.5}, {"cantidad_scrap_directo": 2}, {"cantidad_a_retrabajo": 1},
    {"cantidad_liberada": 1}, {"cantidad_detectada": "NaN"}, {"trazabilidad": ""},
    {"trazabilidad": "no-valido"}, {"motivo_id": 99999}, {"retrabajo_estado": "REALIZADO"}])
def test_rechaza_cantidades_y_campos_invalidos(sistema, cambios):
    response = ingresar(sistema).post("/calidad/scrap/nuevo", data=formulario_calidad(sistema, **cambios))
    assert response.status_code == 400
    with sistema.app_context():
        assert db.session.execute(db.select(db.func.count(Declaracion.id))).scalar_one() == 0


def test_no_crea_celula_si_esta_inactiva(sistema):
    form = formulario_calidad(sistema)
    with sistema.app_context():
        cell = db.session.execute(db.select(Celula).where(Celula.nombre == "Calidad")).scalar_one()
        cell.activo = False
        db.session.commit()
    response = ingresar(sistema).post("/calidad/scrap/nuevo", data=form)
    assert response.status_code == 400
    with sistema.app_context():
        assert db.session.execute(db.select(db.func.count(Declaracion.id))).scalar_one() == 0
        assert not db.session.execute(db.select(Celula).where(Celula.nombre == "Calidad")).scalar_one().activo


@pytest.mark.parametrize("controlado", [False, True])
def test_scrap_directo_validado_se_imprime_y_se_exporta(sistema, controlado):
    if controlado:
        with sistema.app_context():
            db.session.add(PiezaControlLogistica(codigo="CH-1110", activo=True))
            db.session.commit()
    client = ingresar(sistema)
    response = client.post("/calidad/scrap/nuevo", data=formulario_calidad(sistema))
    assert response.status_code == 302
    assert "/calidad?" in response.location and "imprimir=" in response.location
    with sistema.app_context():
        dnc = db.session.execute(db.select(Declaracion)).scalar_one()
        item = dnc.items[0]
        assert dnc.celula_detecta == "Calidad"
        assert dnc.turno_id == 1 and dnc.equipo == "301"
        assert dnc.legajo_calidad == "123" and dnc.fecha_validacion is not None
        assert dnc.estado == ("PENDIENTE_LOGISTICA" if controlado else "CERRADA")
        assert item.cantidad_detectada == item.cantidad_scrap_directo == 3
        assert item.cantidad_a_retrabajo == item.cantidad_liberada == 0
        assert not item.intervenciones
        assert item.observacion_calidad == "Corte de probeta de soldadura"
        assert item.requiere_validacion_logistica == controlado
        assert item.cantidad_scrap_validada_logistica is None
        numero, dnc_id, item_id = dnc.numero, dnc.id, item.id
    history = client.get("/calidad/declaraciones").get_data(as_text=True)
    assert numero in history
    html = client.get(f"/calidad/declaraciones/{dnc_id}?imprimir=1").get_data(as_text=True)
    assert numero in html and "Corte de probeta de soldadura" in html
    assert "AVISO INICIAL" not in html
    assert client.get("/reportes/scrap/excel").status_code == 403
    admin = ingresar(sistema, "admin")
    response = admin.get("/reportes/scrap/excel", query_string={"desde": date.today().isoformat(), "hasta": date.today().isoformat(), "dnc": numero})
    assert response.status_code == 200
    wb = load_workbook(BytesIO(response.data))
    row = list(wb["Resumen por componente"].values)[1]
    assert row[4:7] == (3, 0, 3)
    if controlado:
        logistic = ingresar(sistema, "logistica")
        assert numero in logistic.get("/logistica").get_data(as_text=True)
        assert logistic.post(f"/logistica/validaciones/{item_id}", data={"cantidad": "3", "legajo": "321"}).status_code == 302
        with sistema.app_context():
            assert db.session.get(Declaracion, dnc_id).estado == "CERRADA"


def test_varios_renglones_atomicos_y_destino_logistico_mixto(sistema):
    form = formulario_calidad(sistema)
    items = json.loads(form["items_json"])
    items.append({**items[0], "codigo": "CH-1120", "cantidad_detectada": 2, "cantidad_scrap_directo": 2})
    form["items_json"] = json.dumps(items)
    with sistema.app_context():
        db.session.add(PiezaControlLogistica(codigo="CH-1110", activo=True))
        db.session.commit()
    client = ingresar(sistema)
    assert client.post("/calidad/scrap/nuevo", data=form).status_code == 302
    with sistema.app_context():
        dnc = db.session.execute(db.select(Declaracion)).scalar_one()
        assert len(dnc.items) == 2
        assert dnc.cantidad_scrap == 5
        assert dnc.estado == "PENDIENTE_LOGISTICA"
        assert [i.requiere_validacion_logistica for i in dnc.items] == [True, False]
    items[1]["observacion"] = ""
    form["items_json"] = json.dumps(items)
    assert client.post("/calidad/scrap/nuevo", data=form).status_code == 400
    with sistema.app_context():
        assert db.session.execute(db.select(db.func.count(Declaracion.id))).scalar_one() == 1
        assert db.session.execute(db.select(db.func.count(DeclaracionItem.id))).scalar_one() == 2


def test_calidad_valida_operacion_hcp_y_dato_adicional_en_servidor(sistema):
    client = ingresar(sistema)
    # Pieza con operaciones: ninguna operación elegida debe rechazarse.
    assert client.post("/calidad/scrap/nuevo", data=formulario_calidad(sistema, codigo="CONJ-1000")).status_code == 400
    with sistema.app_context():
        motivo = db.session.execute(db.select(Motivo).where(Motivo.codigo == "D11")).scalar_one()
        motivo_id, grupo_id = motivo.id, motivo.grupo_id
    assert client.post("/calidad/scrap/nuevo", data=formulario_calidad(sistema, motivo_id=motivo_id, grupo_id=grupo_id)).status_code == 400
    with sistema.app_context():
        assert db.session.execute(db.select(db.func.count(Declaracion.id))).scalar_one() == 0


def test_origen_y_responsabilidad_se_fijan_en_servidor(sistema):
    form = formulario_calidad(sistema, tipo_origen="PROVEEDOR", proveedor_numero="999999",
        sector_origen="Otro", celula_origen="Célula 0001", operacion_origen="Otro proceso",
        legajo_origen="999", tipo_imputacion="NO_DETERMINADA", responsabilidad_estado="PENDIENTE")
    assert ingresar(sistema).post("/calidad/scrap/nuevo", data=form).status_code == 302
    with sistema.app_context():
        item = db.session.execute(db.select(DeclaracionItem)).scalar_one()
        assert item.tipo_origen == item.responsable_tipo == "INTERNO"
        assert item.celula_origen == item.responsable_celula == "Calidad"
        assert item.responsabilidad_estado == item.tipo_imputacion == "CONFIRMADA"
        assert item.responsable_legajo == item.legajo_origen == "123"
        assert item.responsable_operacion == "Ensayos de Calidad"
        assert item.proveedor_numero is None and item.proveedor is None
        assert item.declaracion.estado == "CERRADA"


def test_unidad_calidad_inactiva_impide_declarar(sistema):
    form = formulario_calidad(sistema)
    with sistema.app_context():
        cell = db.session.execute(db.select(Celula).where(Celula.nombre == "Calidad")).scalar_one()
        cell.unidad_gestion.activo = False
        db.session.commit()
    assert ingresar(sistema).post("/calidad/scrap/nuevo", data=form).status_code == 400


def test_limite_de_cantidad_entera_y_observacion(sistema):
    client = ingresar(sistema)
    for cambios in [{"cantidad_detectada": 1000000000, "cantidad_scrap_directo": 1000000000},
                    {"observacion": " "}, {"observacion": "x" * 256}]:
        assert client.post("/calidad/scrap/nuevo", data=formulario_calidad(sistema, **cambios)).status_code == 400
    assert client.post("/calidad/scrap/nuevo", data=formulario_calidad(sistema,
        cantidad_detectada=999999999, cantidad_scrap_directo=999999999)).status_code == 302
    with sistema.app_context():
        assert db.session.execute(db.select(DeclaracionItem)).scalar_one().cantidad_scrap_total == 999999999


def test_scrap_calidad_persiste_despues_de_reiniciar(tmp_path):
    from app import create_app
    config = {"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'calidad.db'}",
              "SECRET_KEY": "test-persistencia", "AUTH_DISABLED": False}
    app = create_app(config)
    assert ingresar(app).post("/calidad/scrap/nuevo", data=formulario_calidad(app)).status_code == 302
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    segunda = create_app(config)
    with segunda.app_context():
        dnc = db.session.execute(db.select(Declaracion)).scalar_one()
        assert dnc.numero == "DNC-000001" and dnc.estado == "CERRADA"
        assert dnc.fecha_validacion is not None and dnc.legajo_calidad == "123"
        assert dnc.items[0].cantidad_scrap_total == 3
        assert dnc.items[0].responsable_celula == "Calidad"
        assert dnc.items[0].observacion_calidad == "Corte de probeta de soldadura"
        db.session.remove()
        db.engine.dispose()


def test_no_admite_causa_de_un_grupo_inactivo(sistema):
    form = formulario_calidad(sistema)
    with sistema.app_context():
        motivo = db.session.execute(db.select(Motivo).where(Motivo.codigo == "D3-POR")).scalar_one()
        motivo.grupo.activo = False
        db.session.commit()
    assert ingresar(sistema).post("/calidad/scrap/nuevo", data=form).status_code == 400


def test_repite_validacion_externa_hcp_aunque_el_formato_sea_valido(sistema, monkeypatch):
    llamadas = []
    def hcp_inexistente(*args):
        llamadas.append(args)
        return False
    monkeypatch.setattr("app.validar_hcp", hcp_inexistente)
    response = ingresar(sistema).post("/calidad/scrap/nuevo", data=formulario_calidad(sistema))
    assert response.status_code == 400
    assert llamadas == [("CH-1110", "", "123456", False)]
