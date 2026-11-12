"""Analítica, permisos de consulta y fuente productiva de solo lectura."""
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError

from analisis import construir_analisis, filtros_analisis, porcentaje_scrap
from app import Declaracion, DeclaracionItem, Motivo, Usuario, create_app, db
from productivo import normalizar_operacion, produccion_por_operacion
from test_integridad import crear_dnc, mysql_server, sistema  # noqa: F401


def filtros(**cambios):
    return filtros_analisis({"desde": "2026-01-01", "hasta": "2026-01-31", **cambios})


def producidas():
    return [{"fecha": date(2026, 1, 5), "codigo": " CH-1110 ", "operacion": "10", "cantidad": Decimal("97"), "sin_cantidad": 0}]


def preparar(app):
    d, ids, _ = crear_dnc(app, intervencion=True)
    with app.app_context():
        item = db.session.get(DeclaracionItem, ids[0])
        item.operacion_codigo = "010"
        db.session.commit()
    return d, ids[0]


def calcular(app, produccion=None, **cambios):
    with app.app_context():
        return construir_analisis(db.session.execute(db.select(Declaracion)).scalars().all(),
            producidas() if produccion is None else produccion, filtros(**cambios))


@pytest.mark.parametrize("op", ["010", "10", "00010", " 010 "])
def test_operacion_textual_se_normaliza(op):
    assert normalizar_operacion(op) == "10"


@pytest.mark.parametrize("buenas,scrap,esperado", [(97,3,Decimal("3")),(0,3,Decimal("100")),(10,0,Decimal("0")),(0,0,None),(None,3,None)])
def test_formula_no_confunde_buenas_con_total(buenas, scrap, esperado):
    assert porcentaje_scrap(None if buenas is None else Decimal(buenas), Decimal(scrap)) == esperado


@pytest.mark.parametrize("args", [{"desde":"mal"}, {"hasta":"2026-00-01"}, {"desde":"2026-02-01","hasta":"2026-01-01"}, {"hasta":"9999-12-31"}, {"fecha":"otro"}, {"origen_scrap":"otro"}])
def test_filtros_invalidos(args):
    with pytest.raises(ValueError):
        filtros(**args)


def test_scrap_directo_mas_final_y_recuperacion_sin_doble_conteo(sistema):
    preparar(sistema)
    datos = calcular(sistema)
    row = datos["comparacion"][0]
    assert row["buenas"] == 97
    assert row["scrap"] == 3 and row["directo"] == 2 and row["retrabajo"] == 1
    assert row["porcentaje"] == 3
    assert datos["resumen"]["recuperadas"] == 3
    assert datos["resumen"]["recuperacion"] == 75
    assert datos["resumen"]["pendiente"] == 4
    assert len(datos["detalle"]) == 2 and sum(f["cantidad"] for f in datos["detalle"]) == 3
    assert datos["pareto"][-1]["acumulado"] == 100


def test_no_suma_operaciones_como_piezas_distintas(sistema):
    preparar(sistema)
    p = producidas() + [{"fecha":date(2026,1,5),"codigo":"CH-1110","operacion":"020","cantidad":100}]
    datos = calcular(sistema,p)
    rows = {(r["pieza"],r["operacion"]):r for r in datos["comparacion"]}
    assert rows[("CH-1110","10")]["porcentaje"] == 3
    assert rows[("CH-1110","20")]["porcentaje"] == 0
    assert "porcentaje_global" not in datos["resumen"]


def test_fecha_de_evento_no_carga_scrap_futuro_en_dnc_anterior(sistema):
    preparar(sistema)
    enero5 = calcular(sistema, hasta="2026-01-05")
    assert enero5["resumen"]["scrap"] == 2
    enero6 = calcular(sistema, desde="2026-01-06", hasta="2026-01-06")
    assert enero6["resumen"]["scrap"] == 1
    assert enero6["resumen"]["recuperadas"] == 3
    assert enero6["comparacion"][0]["porcentaje"] is None
    emision = calcular(sistema, hasta="2026-01-05", fecha="DNC")
    assert emision["resumen"]["scrap"] == 3
    assert all(r["porcentaje"] is None for r in emision["comparacion"])


@pytest.mark.parametrize("extra", [{"celula":"Célula"}, {"motivo":"D3"}, {"equipo":"101"}, {"origen_scrap":"DIRECTO"}])
def test_no_presenta_tasas_con_denominadores_incompatibles(sistema, extra):
    preparar(sistema)
    assert all(r["porcentaje"] is None for r in calcular(sistema, **extra)["comparacion"])


@pytest.mark.parametrize("p", [[], [{"codigo":"CH-1110","operacion":"010","cantidad":None}], [{"codigo":"CH-1110","operacion":"010","cantidad":-1}], [{"codigo":"CH-1110","operacion":"010","cantidad":10,"sin_cantidad":1}]])
def test_datos_ausentes_o_invalidos_no_se_convierten_en_cero(sistema,p):
    preparar(sistema)
    row = calcular(sistema,p)["comparacion"][0]
    assert row["porcentaje"] is None and row["buenas"] is None


def test_operacion_ausente_no_se_asigna_a_la_produccion_de_otra_etapa(sistema):
    crear_dnc(sistema)
    datos=calcular(sistema)
    sin_op=next(r for r in datos["comparacion"] if not r["operacion"])
    assert sin_op["scrap"] == 2 and sin_op["porcentaje"] is None


def test_unidades_distintas_no_se_mezclan(sistema):
    d, ids, _=crear_dnc(sistema,filas=2)
    with sistema.app_context():
        db.session.get(DeclaracionItem,ids[1]).unidad="KG"
        db.session.commit()
    assert calcular(sistema)["resumen"]["scrap"] == 2
    kg=calcular(sistema,unidad="KG")
    assert kg["resumen"]["scrap"] == 2 and kg["comparacion"][0]["buenas"] is None


def test_consulta_usuario_y_servidor_bloquean_escrituras(sistema,monkeypatch):
    d, item=preparar(sistema)
    sistema.config["AUTH_DISABLED"]=False
    client=sistema.test_client()
    client.post('/login',data={"usuario":"admin","clave":"admin"})
    result=client.post('/gestion/usuarios/consulta',data={"usuario":"visor","nombre":"Consulta","clave":"clave-prueba","confirmacion":"clave-prueba"})
    assert result.status_code == 302
    client.post('/logout')
    ingreso=client.post('/login',data={"usuario":"visor","clave":"clave-prueba"})
    assert ingreso.location.endswith('/analisis')
    monkeypatch.setattr('analisis.produccion_por_operacion',lambda *args:producidas())
    assert client.get('/analisis?desde=2026-01-01&hasta=2026-01-31').status_code==200
    history=client.get('/declaraciones').get_data(as_text=True)
    assert 'Nueva declaración' not in history and '>Editar</a>' not in history
    detail=client.get(f'/declaraciones/{d}?imprimir=1')
    assert detail.status_code==200
    assert 'Registrar retrabajo' not in detail.get_data(as_text=True)
    assert client.get('/reportes/scrap?mes=2026-01').status_code==200
    for path in ['/gestion','/calidad','/produccion','/logistica','/api/piezas','/declaraciones/nueva',f'/declaraciones/{d}/editar']:
        assert client.get(path).status_code==403
    for path in [f'/declaraciones/{d}/eliminar',f'/calidad/{d}/validar',f'/retrabajos/{item}/registrar','/gestion/usuarios/consulta','/analisis']:
        response=client.post(path,headers={'X-Requested-With':'fetch'})
        assert response.status_code==403 and response.is_json
    with sistema.app_context():
        cuenta=db.session.execute(db.select(Usuario).where(Usuario.usuario=='visor')).scalar_one()
        assert cuenta.rol=='CONSULTA' and cuenta.verificar_clave('clave-prueba')
        assert cuenta.clave_hash!='clave-prueba'
        assert db.session.get(Declaracion,d) is not None


@pytest.mark.parametrize('usuario',['produccion','calidad','logistica'])
def test_otros_roles_no_pueden_ver_analisis_ni_crear_consulta(sistema,usuario):
    sistema.config['AUTH_DISABLED']=False
    client=sistema.test_client()
    client.post('/login',data={'usuario':usuario,'clave':usuario})
    assert client.get('/analisis').status_code==403
    assert client.get('/analisis/excel').status_code==403
    assert client.post('/gestion/usuarios/consulta',data={}).status_code==403


@pytest.mark.parametrize('datos',[{}, {'usuario':'admin','nombre':'Consulta','clave':'clave-prueba','confirmacion':'clave-prueba'}, {'usuario':'../mal','nombre':'Consulta','clave':'clave-prueba','confirmacion':'clave-prueba'}, {'usuario':'visor','nombre':'Consulta','clave':'corta','confirmacion':'corta'}])
def test_alta_invalida_no_modifica_cuentas_existentes(sistema,datos):
    sistema.config['AUTH_DISABLED']=False
    client=sistema.test_client()
    client.post('/login',data={'usuario':'admin','clave':'admin'})
    assert client.post('/gestion/usuarios/consulta',data=datos).status_code==302
    with sistema.app_context():
        assert db.session.execute(db.select(db.func.count(Usuario.id))).scalar_one()==4
        assert db.session.execute(db.select(Usuario).where(Usuario.usuario=='admin')).scalar_one().verificar_clave('admin')


def test_pantalla_excel_y_filtros_comparten_calculos(sistema,monkeypatch):
    d, item=preparar(sistema)
    with sistema.app_context():
        db.session.get(DeclaracionItem,item).descripcion='=HYPERLINK("https://example.com")'
        db.session.commit()
    monkeypatch.setattr('analisis.produccion_por_operacion',lambda *args:producidas())
    client=sistema.test_client()
    args={'desde':'2026-01-01','hasta':'2026-01-31','operacion':'010'}
    html=client.get('/analisis',query_string=args)
    assert html.status_code==200 and '3.00%' in html.get_data(as_text=True)
    excel=client.get('/analisis/excel',query_string=args)
    wb=load_workbook(BytesIO(excel.data),data_only=False)
    assert wb['Comparación']['D2'].value==97
    assert wb['Comparación']['G2'].value==3 and wb['Comparación']['H2'].value==3
    assert wb['Comparación']['C2'].data_type=='s'
    assert len(list(wb['Detalle DNC'].values))==3
    assert client.get('/analisis?desde=invalida').status_code==400


def test_produccion_indisponible_conserva_scrap_y_avisa(sistema,monkeypatch):
    preparar(sistema)
    def fallo(*args): raise RuntimeError('detalle técnico privado')
    monkeypatch.setattr('analisis.produccion_por_operacion',fallo)
    client=sistema.test_client()
    response=client.get('/analisis?desde=2026-01-01&hasta=2026-01-31')
    html=response.get_data(as_text=True)
    assert response.status_code==200 and 'No se pudo consultar la producción' in html
    assert 'detalle técnico privado' not in html and '3.000' in html and 'Sin datos' in html
    wb=load_workbook(BytesIO(client.get('/analisis/excel?desde=2026-01-01&hasta=2026-01-31').data))
    assert wb['Comparación']['H2'].value is None


@pytest.mark.parametrize('tipo_fecha',['DATE','DATETIME'])
def test_produccion_mysql_incluye_ultimo_dia_y_solo_lee(mysql_server,monkeypatch,tipo_fecha):
    engine,url=mysql_server
    nombre='erp_test_'+uuid4().hex
    usuario='lectura_'+uuid4().hex[:12]
    with engine.begin() as c:
        c.execute(text(f'CREATE DATABASE `{nombre}`'))
        c.execute(text(f'CREATE TABLE `{nombre}`.produc04 (FPRO_ {tipo_fecha}, CANT_ DECIMAL(12,3), NPRO_ VARCHAR(30), GCOD_ VARCHAR(50))'))
        c.execute(text(f"INSERT INTO `{nombre}`.produc04 VALUES (:fecha,:cantidad,:op,:codigo)"),[
            {'fecha':'2026-01-04 00:00:00','cantidad':900,'op':'010','codigo':'CH-1110'},
            {'fecha':'2026-01-05 00:00:00','cantidad':40,'op':'010','codigo':'CH-1110'},
            {'fecha':'2026-01-06 23:59:59','cantidad':57,'op':' 10 ','codigo':' CH-1110 '},
            {'fecha':'2026-01-07 00:00:00','cantidad':900,'op':'010','codigo':'CH-1110'}])
        c.execute(text(f"CREATE USER '{usuario}'@'%' IDENTIFIED BY ''"))
        c.execute(text(f"GRANT SELECT ON `{nombre}`.* TO '{usuario}'@'%'"))
    lectura=create_engine(url.set(database=nombre,username=usuario,password=None))
    app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///:memory:','SECRET_KEY':'test'})
    app.config['PRODUCTIVE_DEMO_MODE']=False
    app.extensions['productivo_engine']=lectura
    monkeypatch.setenv('ERP_SCHEMA',nombre)
    sentencias=[]
    def registrar(conn,cursor,sql,params,context,many): sentencias.append(sql.strip().upper())
    event.listen(lectura,'before_cursor_execute',registrar)
    try:
        with app.app_context():
            filas=produccion_por_operacion(date(2026,1,5),date(2026,1,6))
            assert sum(f['cantidad'] for f in filas)==97
            assert {normalizar_operacion(f['operacion']) for f in filas}=={'10'}
            assert all(date(2026,1,5)<=f['fecha']<=date(2026,1,6) for f in filas)
        assert sentencias and all(s.startswith('SELECT') for s in sentencias)
        event.remove(lectura,'before_cursor_execute',registrar)
        with lectura.begin() as c:
            with pytest.raises(DBAPIError): c.execute(text('UPDATE produc04 SET CANT_=0'))
    finally:
        if event.contains(lectura,'before_cursor_execute',registrar): event.remove(lectura,'before_cursor_execute',registrar)
        lectura.dispose()
        with app.app_context():
            db.session.remove(); db.engine.dispose()
        with engine.begin() as c:
            c.execute(text(f'DROP DATABASE `{nombre}`'))
            c.execute(text(f"DROP USER '{usuario}'@'%'"))


def test_deteccion_y_responsabilidad_no_se_confunden(sistema):
    d, item=preparar(sistema)
    with sistema.app_context():
        i=db.session.get(DeclaracionItem,item)
        i.responsable_celula='Otra célula'
        i.responsabilidad_estado='PROBABLE'
        db.session.commit()
    datos=calcular(sistema)
    assert datos['deteccion'][0]['celula']=='Célula 0001'
    assert datos['responsabilidad'][0]['responsable']=='Otra célula'
    assert datos['responsabilidad'][0]['conclusion']=='PROBABLE'
    assert datos['responsabilidad'][0]['scrap']==3


def test_alertas_no_validadas_no_incrementan_scrap(sistema):
    d, ids, _=crear_dnc(sistema,validada=False)
    datos=calcular(sistema,[])
    assert datos['resumen']['scrap']==0 and datos['detalle']==[]


def test_consulta_vencida_devuelve_json_y_no_hay_alta_automatica(sistema):
    import time
    sistema.config['AUTH_DISABLED']=False
    client=sistema.test_client()
    with sistema.app_context():
        assert db.session.execute(db.select(db.func.count(Usuario.id)).where(Usuario.rol=='CONSULTA')).scalar_one()==0
        u=Usuario(usuario='visor',nombre='Consulta',rol='CONSULTA',activo=True,clave_hash='')
        u.cambiar_clave('clave-prueba');db.session.add(u);db.session.commit()
    client.post('/login',data={'usuario':'visor','clave':'clave-prueba'})
    with client.session_transaction() as session: session['sesion_iniciada_en']=time.time()-301
    r=client.get('/analisis',headers={'X-Requested-With':'fetch'})
    assert r.status_code==401 and r.is_json


def test_cuenta_consulta_persiste_despues_de_reiniciar(tmp_path):
    config={'TESTING':True,'SQLALCHEMY_DATABASE_URI':f"sqlite:///{tmp_path / 'consulta.db'}",'SECRET_KEY':'test','AUTH_DISABLED':False}
    app=create_app(config)
    client=app.test_client();client.post('/login',data={'usuario':'admin','clave':'admin'})
    client.post('/gestion/usuarios/consulta',data={'usuario':'consulta','nombre':'Solo lectura','clave':'clave-prueba','confirmacion':'clave-prueba','rol':'ADMIN'})
    with app.app_context(): db.session.remove();db.engine.dispose()
    segunda=create_app(config)
    client=segunda.test_client()
    assert client.post('/login',data={'usuario':'consulta','clave':'clave-prueba'}).location.endswith('/analisis')
    assert client.get('/gestion').status_code==403
    with segunda.app_context():
        u=db.session.execute(db.select(Usuario).where(Usuario.usuario=='consulta')).scalar_one()
        assert u.rol=='CONSULTA' and u.verificar_clave('clave-prueba')
        db.session.remove();db.engine.dispose()


def test_pagina_fuera_de_rango_se_limita_y_filtros_no_se_pierden(sistema,monkeypatch):
    preparar(sistema)
    monkeypatch.setattr('analisis.produccion_por_operacion',lambda *args:producidas())
    response=sistema.test_client().get('/analisis?desde=2026-01-01&hasta=2026-01-31&pagina=999999')
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert 'Página 1' in html and '3.00%' in html


def test_exportacion_incluye_resultados_de_todas_las_paginas(sistema,monkeypatch):
    preparar(sistema)
    produccion=producidas()+[{'fecha':date(2026,1,5),'codigo':f'CH-P{i:03d}','operacion':'010','cantidad':1} for i in range(205)]
    monkeypatch.setattr('analisis.produccion_por_operacion',lambda *args:produccion)
    client=sistema.test_client()
    query={'desde':'2026-01-01','hasta':'2026-01-31','pieza':'CH-','pagina':'2'}
    html=client.get('/analisis',query_string=query).get_data(as_text=True)
    assert 'Página 2' in html and 'pagina=3' in html
    wb=load_workbook(BytesIO(client.get('/analisis/excel',query_string=query).data))
    assert len(list(wb['Comparación'].values))==207
    assert sum(row[6] for row in list(wb['Comparación'].values)[1:])==3
