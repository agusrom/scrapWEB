import json
import os
import re
import time
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO

from validaciones import decimal_no_negativo, entero_no_negativo, validar_disposicion

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, or_, text
from sqlalchemy.orm import selectinload
from werkzeug.security import check_password_hash, generate_password_hash

from productivo import (
    buscar_operaciones,
    buscar_piezas,
    buscar_proveedor,
    buscar_proveedores,
    init_productivo,
    listar_equipos,
    listar_operaciones_pieza,
    listar_turnos,
    obtener_componentes_finales,
    obtener_estructura,
    validar_fuentes_mysql,
    validar_hcp,
)

load_dotenv()
db = SQLAlchemy()


class Usuario(db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(40), unique=True, nullable=False, index=True)
    nombre = db.Column(db.String(120), nullable=False)
    rol = db.Column(db.String(20), nullable=False)
    clave_hash = db.Column(db.String(255), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.now)

    def verificar_clave(self, clave):
        return check_password_hash(self.clave_hash, str(clave or ""))

    def cambiar_clave(self, clave):
        self.clave_hash = generate_password_hash(str(clave))


class Declaracion(db.Model):
    __tablename__ = "declaraciones"

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=True, index=True)
    fecha = db.Column(db.Date, nullable=False)
    sector_declara = db.Column(db.String(40), nullable=False)
    unidad_gestion = db.Column(db.String(120), nullable=True)
    celula_detecta = db.Column(db.String(80), nullable=False)
    celula_codigo_equipos = db.Column(db.String(80), nullable=True)
    legajo_declara = db.Column(db.String(30), nullable=False)
    turno_id = db.Column(db.Integer, nullable=True)
    turno = db.Column(db.String(80), nullable=True)
    equipo = db.Column(db.String(80), nullable=False)
    equipo_descripcion = db.Column(db.String(160), nullable=True)
    cliente = db.Column(db.String(100), nullable=True)
    lugar_detectado = db.Column(db.String(120), nullable=False)
    observaciones = db.Column(db.Text, nullable=True)
    estado = db.Column(db.String(30), nullable=False, default="ABIERTA")
    legajo_calidad = db.Column(db.String(30), nullable=True)
    fecha_validacion = db.Column(db.DateTime, nullable=True)
    observaciones_calidad = db.Column(db.Text, nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.now)
    actualizado_en = db.Column(
        db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    items = db.relationship(
        "DeclaracionItem",
        back_populates="declaracion",
        cascade="all, delete-orphan",
        order_by="DeclaracionItem.id",
    )

    @property
    def cantidad_detectada(self):
        return sum((item.cantidad_detectada for item in self.items), Decimal("0"))

    @property
    def cantidad_scrap(self):
        return sum((item.cantidad_scrap_total for item in self.items), Decimal("0"))

    @property
    def cantidad_retrabajo_pendiente(self):
        return sum((item.cantidad_retrabajo_pendiente for item in self.items), Decimal("0"))


class GrupoMotivo(db.Model):
    __tablename__ = "grupos_motivo"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True, nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    orden = db.Column(db.Integer, nullable=False, default=0)
    motivos = db.relationship(
        "Motivo", back_populates="grupo", order_by="Motivo.codigo"
    )


class Motivo(db.Model):
    __tablename__ = "motivos"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    tipo_accion = db.Column(db.String(20), nullable=False, default="NINGUNA")
    grupo_id = db.Column(
        db.Integer, db.ForeignKey("grupos_motivo.id"), nullable=True, index=True
    )
    grupo = db.relationship("GrupoMotivo", back_populates="motivos")


class Catalogo(db.Model):
    __tablename__ = "catalogos"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(30), nullable=False, index=True)
    codigo = db.Column(db.String(30), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    orden = db.Column(db.Integer, nullable=False, default=0)
    __table_args__ = (
        db.UniqueConstraint("tipo", "codigo", name="uq_catalogo_tipo_codigo"),
    )


class UnidadGestion(db.Model):
    __tablename__ = "unidades_gestion"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False)
    nombre = db.Column(db.String(120), unique=True, nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    orden = db.Column(db.Integer, nullable=False, default=0)
    celulas = db.relationship(
        "Celula",
        back_populates="unidad_gestion",
        order_by="Celula.orden, Celula.nombre",
    )


class Celula(db.Model):
    __tablename__ = "celulas"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False)
    nombre = db.Column(db.String(120), unique=True, nullable=False)
    codigo_equipos = db.Column(db.String(80), unique=True, nullable=False)
    unidad_gestion_id = db.Column(
        db.Integer,
        db.ForeignKey("unidades_gestion.id"),
        nullable=False,
        index=True,
    )
    activo = db.Column(db.Boolean, nullable=False, default=True)
    orden = db.Column(db.Integer, nullable=False, default=0)
    unidad_gestion = db.relationship("UnidadGestion", back_populates="celulas")


class PiezaControlLogistica(db.Model):
    __tablename__ = "piezas_control_logistica"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False, index=True)
    descripcion = db.Column(db.String(255), nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.now)


class Configuracion(db.Model):
    __tablename__ = "configuraciones"

    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(60), unique=True, nullable=False)
    valor = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)


class VersionEsquema(db.Model):
    __tablename__ = "versiones_esquema"

    version = db.Column(db.Integer, primary_key=True)
    descripcion = db.Column(db.String(255), nullable=False)
    aplicado_en = db.Column(db.DateTime, nullable=False, default=datetime.now)


class DeclaracionItem(db.Model):
    __tablename__ = "declaracion_items"

    id = db.Column(db.Integer, primary_key=True)
    declaracion_id = db.Column(
        db.Integer, db.ForeignKey("declaraciones.id"), nullable=False, index=True
    )
    tipo_material = db.Column(db.String(30), nullable=False)
    codigo_padre = db.Column(db.String(50), nullable=True)
    codigo_pieza = db.Column(db.String(50), nullable=False)
    codigo_cliente = db.Column(db.String(50), nullable=True)
    material = db.Column(db.String(80), nullable=True)
    descripcion = db.Column(db.String(255), nullable=True)
    trazabilidad = db.Column(db.String(6), nullable=False)
    operacion_codigo = db.Column(db.String(30), nullable=True)
    operacion_descripcion = db.Column(db.String(160), nullable=True)
    unidad = db.Column(db.String(10), nullable=False, default="PZS")
    uso_estructura = db.Column(db.Numeric(12, 4), nullable=True)
    cantidad_detectada = db.Column(db.Numeric(12, 3), nullable=False)
    cantidad_scrap_directo = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    cantidad_a_retrabajo = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    cantidad_liberada = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    motivo_id = db.Column(db.Integer, db.ForeignKey("motivos.id"), nullable=False)
    sector_origen = db.Column(db.String(40), nullable=False)
    celula_origen = db.Column(db.String(80), nullable=False)
    operacion_origen = db.Column(db.String(120), nullable=False)
    legajo_origen = db.Column(db.String(30), nullable=True)
    tipo_imputacion = db.Column(db.String(20), nullable=False)
    tipo_origen = db.Column(db.String(20), nullable=False, default="INTERNO")
    proveedor_numero = db.Column(db.String(30), nullable=True)
    proveedor = db.Column(db.String(120), nullable=True)
    remito = db.Column(db.String(80), nullable=True)
    afectado_tipo = db.Column(db.String(20), nullable=True)
    afectado_codigo = db.Column(db.String(80), nullable=True)
    afectado_descripcion = db.Column(db.String(255), nullable=True)
    afectado_componente_codigo = db.Column(db.String(50), nullable=True)
    responsabilidad_estado = db.Column(
        db.String(24), nullable=False, default="CONFIRMADA"
    )
    responsable_tipo = db.Column(db.String(20), nullable=True)
    responsable_sector = db.Column(db.String(40), nullable=True)
    responsable_celula = db.Column(db.String(80), nullable=True)
    responsable_operacion = db.Column(db.String(120), nullable=True)
    responsable_legajo = db.Column(db.String(30), nullable=True)
    responsable_proveedor_numero = db.Column(db.String(30), nullable=True)
    responsable_proveedor = db.Column(db.String(120), nullable=True)
    observacion_calidad = db.Column(db.String(255), nullable=True)
    observacion = db.Column(db.String(255), nullable=True)
    requiere_validacion_logistica = db.Column(
        db.Boolean, nullable=False, default=False
    )
    cantidad_scrap_validada_logistica = db.Column(
        db.Numeric(12, 3), nullable=True
    )
    legajo_logistica = db.Column(db.String(30), nullable=True)
    fecha_validacion_logistica = db.Column(db.DateTime, nullable=True)
    observacion_logistica = db.Column(db.String(255), nullable=True)

    declaracion = db.relationship("Declaracion", back_populates="items")
    motivo = db.relationship("Motivo")
    intervenciones = db.relationship(
        "RetrabajoIntervencion",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="RetrabajoIntervencion.fecha, RetrabajoIntervencion.id",
    )

    @property
    def cantidad_recuperada(self):
        return sum((x.cantidad_ok for x in self.intervenciones), Decimal("0"))

    @property
    def cantidad_scrap_retrabajo(self):
        return sum((x.cantidad_scrap for x in self.intervenciones), Decimal("0"))

    @property
    def cantidad_scrap_total(self):
        return self.cantidad_scrap_directo + self.cantidad_scrap_retrabajo

    @property
    def cantidad_retrabajo_resuelta(self):
        return self.cantidad_recuperada + self.cantidad_scrap_retrabajo

    @property
    def cantidad_retrabajo_pendiente(self):
        pendiente = self.cantidad_a_retrabajo - self.cantidad_retrabajo_resuelta
        return max(pendiente, Decimal("0"))

    @property
    def estado(self):
        if self.declaracion.estado == "PENDIENTE_CALIDAD":
            return "PENDIENTE CALIDAD"
        if (
            self.requiere_validacion_logistica
            and self.fecha_validacion_logistica is None
        ):
            return "PENDIENTE LOGÍSTICA"
        if self.cantidad_retrabajo_pendiente > 0:
            return "PENDIENTE RETRABAJO"
        if self.cantidad_a_retrabajo > 0:
            return "RETRABAJO CERRADO"
        if self.cantidad_liberada > 0 and self.cantidad_scrap_directo <= 0:
            return "LIBERADO"
        return "SCRAP DIRECTO"


class RetrabajoIntervencion(db.Model):
    __tablename__ = "retrabajo_intervenciones"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(
        db.Integer, db.ForeignKey("declaracion_items.id"), nullable=False, index=True
    )
    fecha = db.Column(db.Date, nullable=False)
    operacion = db.Column(db.String(120), nullable=False)
    celula = db.Column(db.String(80), nullable=False)
    legajo = db.Column(db.String(30), nullable=False)
    minutos = db.Column(db.Integer, nullable=False)
    cantidad_personas = db.Column(db.Integer, nullable=False, default=1)
    cantidad_ok = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    cantidad_scrap = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    motivo_scrap_id = db.Column(db.Integer, db.ForeignKey("motivos.id"), nullable=True)
    observaciones = db.Column(db.String(255), nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.now)

    item = db.relationship("DeclaracionItem", back_populates="intervenciones")
    motivo_scrap = db.relationship("Motivo")

    @property
    def horas_hombre(self):
        return (self.minutos * self.cantidad_personas) / 60


MOTIVOS_INICIALES = [
    ("D1", "SET UP - PUESTA A PUNTO", "NINGUNA"),
    ("D2", "DEFECTOS DE MP", "MATERIA_PRIMA"),
    ("D3", "DEFECTOS SOLDADURA", "NINGUNA"),
    ("D4", "GEOMETRÍA NO OK", "NINGUNA"),
    ("D5", "ENSAYO MACROGRÁFICO", "NINGUNA"),
    ("D6", "AUSENCIA/DEFECTO AGUJERO", "NINGUNA"),
    ("D7", "CONFORMADO CAÑO NO OK", "NINGUNA"),
    ("D8", "MECANIZADO NO OK", "NINGUNA"),
    ("D9", "PROCESO 3° NO OK", "NINGUNA"),
    ("D10", "REBABAS NO OK", "NINGUNA"),
    ("D11", "COMPONENTE DEFECTUOSO", "COMPONENTE"),
    ("D12", "GRABADO/IDENTIFICACIÓN NO OK", "NINGUNA"),
    ("D13", "RECUBRIMIENTO SUPERFICIAL NO OK", "NINGUNA"),
    ("D14", "OBSOLETAS/FIN DE SERIE", "NINGUNA"),
]

TIPOS_ACCION_MOTIVO = [
    ("NINGUNA", "Sin dato adicional"),
    ("COMPONENTE", "Pedir componente afectado"),
    ("MATERIA_PRIMA", "Pedir materia prima afectada"),
    ("PROCESO", "Pedir proceso relacionado"),
]

SECTORES = ["Producción", "Calidad", "Logística", "Recepción"]
TIPOS_MATERIAL = [
    ("PIEZA_TERMINADA", "Pieza terminada"),
    ("SUBCONJUNTO", "Subconjunto"),
    ("COMPONENTE", "Componente"),
    ("MATERIA_PRIMA", "Materia prima"),
    ("CONSIGNADO", "Componente consignado"),
    ("OTRO", "Otro material"),
]
TIPOS_IMPUTACION = [
    ("CONFIRMADA", "Confirmada"),
    ("PRESUNTA", "Presunta"),
    ("NO_DETERMINADA", "No determinada"),
]

CATALOGOS_INICIALES = {
    "CELULA": [
        ("0001", "Célula 0001"),
        ("RETRABAJO", "Retrabajo"),
        ("CALIDAD", "Calidad"),
        ("RECEPCION", "Recepción"),
    ],
    "EQUIPO": [("A", "Turno A"), ("B", "Turno B"), ("C", "Turno C")],
    "PROVEEDOR": [
        ("PROV-DEMO", "Proveedor de prueba"),
    ],
    "LUGAR": [
        ("LINEA", "Línea / proceso"),
        ("CONTROL", "Control de calidad"),
        ("RECEPCION", "Recepción"),
        ("LOGISTICA", "Logística / dársena"),
    ],
}

CONFIGURACIONES_INICIALES = {
    "NOMBRE_EMPRESA": ("C.G.R. S.A.", "Nombre mostrado en el sistema"),
    "PREFIJO_DECLARACION": ("DNC", "Prefijo del número correlativo"),
    "DIGITOS_DECLARACION": ("6", "Cantidad de dígitos del número correlativo"),
    "TRAZABILIDAD_DIGITOS": ("6", "Cantidad de números del HCP"),
    "MOSTRAR_CLIENTE": ("SI", "Mostrar cliente en la carga de Producción"),
    "PERMITIR_SIN_CODIGO": ("SI", "Permitir materiales sin código productivo"),
    "REQUERIR_LEGAJO_ORIGEN": ("NO", "Hacer obligatorio el legajo de origen"),
    "IMPRESION_AUTOMATICA": ("NO", "Abrir impresión al guardar"),
}

USUARIOS_INICIALES = [
    ("produccion", "Producción", "PRODUCCION", "PRODUCCION_PASSWORD", "produccion"),
    ("calidad", "Calidad", "CALIDAD", "CALIDAD_PASSWORD", "calidad"),
    ("logistica", "Logística", "LOGISTICA", "LOGISTICA_PASSWORD", "logistica"),
    ("admin", "Administrador", "ADMIN", "ADMIN_PASSWORD", "admin"),
]

NOMBRES_ROL = {
    "PRODUCCION": "Producción",
    "CALIDAD": "Calidad",
    "LOGISTICA": "Logística",
    "ADMIN": "Administración",
    "CONSULTA": "Consulta y análisis",
}


def create_app(test_config=None):
    app = Flask(__name__)
    database_url = os.getenv("DATABASE_URL", "").strip()
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "desarrollo-solamente"),
        SQLALCHEMY_DATABASE_URI=database_url or "mysql+pymysql://configuracion-faltante",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={
            "pool_pre_ping": True,
            "pool_recycle": 1800,
        },
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=5),
        SESSION_REFRESH_EACH_REQUEST=False,
        SESSION_MAX_AGE_SECONDS=5 * 60,
        AUTH_DISABLED=os.getenv("AUTH_DISABLED", "false").lower() == "true",
        PRODUCTIVE_DEMO_MODE=os.getenv("PRODUCTIVE_DEMO_MODE", "false").lower() == "true",
        PRODUCTION_DATABASE_URL=os.getenv("PRODUCTION_DATABASE_URL", ""),
        AUXILIARY_DEMO_MODE=os.getenv("AUXILIARY_DEMO_MODE", "false").lower()
        == "true",
        AUXILIARY_DATABASE_URL=os.getenv("AUXILIARY_DATABASE_URL", ""),
    )
    if test_config:
        app.config.update(test_config)
        if app.config.get("TESTING"):
            app.config["PRODUCTIVE_DEMO_MODE"] = test_config.get(
                "PRODUCTIVE_DEMO_MODE", True
            )
            app.config["AUXILIARY_DEMO_MODE"] = test_config.get(
                "AUXILIARY_DEMO_MODE", True
            )

    if str(app.config["SQLALCHEMY_DATABASE_URI"]).startswith("mysql"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"]["isolation_level"] = "READ COMMITTED"
    if not app.config.get("TESTING") and app.config.get("AUTH_DISABLED"):
        raise RuntimeError("No se puede deshabilitar la autenticación en la instalación operativa.")

    db.init_app(app)
    with app.app_context():
        if app.config.get("TESTING"):
            # Base aislada utilizada únicamente por las pruebas automáticas.
            init_productivo(app)
            db.create_all()
            sembrar_datos_iniciales()
        else:
            validar_base_sistema_mysql(database_url)
            validar_esquema_sistema()
            init_productivo(app)
            validar_fuentes_mysql(app)

    registrar_rutas(app)
    from analisis import crear_blueprint
    app.register_blueprint(crear_blueprint(db, Declaracion, DeclaracionItem, Motivo, RetrabajoIntervencion))
    return app


def sembrar_datos_iniciales():
    """Carga inicial controlada; sólo la invocan pruebas y el migrador."""
    sembrar_motivos()
    sembrar_catalogos_y_configuracion()
    sembrar_unidades_y_celulas()
    sembrar_usuarios()


def validar_base_sistema_mysql(database_url):
    if not database_url:
        raise RuntimeError(
            "Falta DATABASE_URL. Configurá la conexión MySQL en el archivo .env "
            "y ejecutá primero migrar_a_mysql.bat."
        )
    if db.engine.dialect.name != "mysql":
        raise RuntimeError(
            "DATABASE_URL debe apuntar a MySQL. La aplicación operativa ya no "
            "crea ni utiliza bases SQLite locales."
        )
    try:
        with db.engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError(
            "No se pudo conectar con la base MySQL del sistema. Revisá "
            "DATABASE_URL, el servidor, el usuario y sus permisos."
        ) from exc


def validar_esquema_sistema():
    """Verifica tablas y columnas del sistema sin crear ni modificar nada."""
    inspector = inspect(db.engine)
    tablas_existentes = set(inspector.get_table_names())
    requeridas = {tabla.name: tabla for tabla in db.metadata.sorted_tables}
    faltantes = sorted(set(requeridas) - tablas_existentes)
    if faltantes:
        raise RuntimeError(
            "La base MySQL del sistema no está migrada. Faltan las tablas: "
            f"{', '.join(faltantes)}. Ejecutá migrar_a_mysql.bat."
        )

    columnas_faltantes = []
    for nombre, tabla in requeridas.items():
        existentes = {columna["name"] for columna in inspector.get_columns(nombre)}
        for columna in tabla.columns:
            if columna.name not in existentes:
                columnas_faltantes.append(f"{nombre}.{columna.name}")
    if columnas_faltantes:
        raise RuntimeError(
            "La estructura MySQL está desactualizada. Faltan columnas: "
            f"{', '.join(columnas_faltantes)}. Ejecutá migrar_a_mysql.bat."
        )


def sembrar_usuarios():
    existentes = {
        usuario.usuario
        for usuario in db.session.execute(db.select(Usuario)).scalars()
    }
    for usuario, nombre, rol, variable_entorno, clave_predeterminada in USUARIOS_INICIALES:
        if usuario in existentes:
            continue
        cuenta = Usuario(
            usuario=usuario,
            nombre=nombre,
            rol=rol,
            activo=True,
            clave_hash="",
        )
        cuenta.cambiar_clave(
            os.getenv(variable_entorno, clave_predeterminada)
        )
        db.session.add(cuenta)
    db.session.commit()


def sembrar_motivos():
    grupos = {
        x.codigo: x
        for x in db.session.execute(db.select(GrupoMotivo)).scalars()
    }
    for orden, (codigo, nombre, _tipo_accion) in enumerate(MOTIVOS_INICIALES):
        if codigo not in grupos:
            grupos[codigo] = GrupoMotivo(
                codigo=codigo, nombre=nombre, orden=orden
            )
            db.session.add(grupos[codigo])
    db.session.flush()
    existentes = {
        m.codigo: m for m in db.session.execute(db.select(Motivo)).scalars()
    }
    for codigo, nombre, tipo_accion in MOTIVOS_INICIALES:
        if codigo not in existentes:
            existentes[codigo] = Motivo(
                codigo=codigo,
                nombre="No identificado / requiere validación",
                tipo_accion=tipo_accion,
                grupo=grupos[codigo],
            )
            db.session.add(existentes[codigo])
        elif existentes[codigo].grupo_id is None:
            existentes[codigo].grupo = grupos[codigo]
        if existentes[codigo].nombre == "Sin especificar":
            existentes[codigo].nombre = "No identificado / requiere validación"
    detalles = [
        ("D2-ESP", "Material fuera de especificación", "D2", "MATERIA_PRIMA"),
        ("D2-OXI", "Oxidación / corrosión", "D2", "MATERIA_PRIMA"),
        ("D2-DIM", "Espesor o dimensión incorrecta", "D2", "MATERIA_PRIMA"),
        ("D3-POR", "Poros", "D3", "NINGUNA"),
        ("D3-SPA", "Exceso de spatter", "D3", "NINGUNA"),
        ("D3-FUS", "Falta de fusión", "D3", "NINGUNA"),
        ("D3-SOC", "Socavado", "D3", "NINGUNA"),
    ]
    for codigo, nombre, grupo_codigo, tipo_accion in detalles:
        if codigo not in existentes:
            db.session.add(
                Motivo(
                    codigo=codigo,
                    nombre=nombre,
                    tipo_accion=tipo_accion,
                    grupo=grupos[grupo_codigo],
                )
            )
    db.session.commit()



def sembrar_catalogos_y_configuracion():
    existentes = {
        (x.tipo, x.codigo)
        for x in db.session.execute(db.select(Catalogo)).scalars()
    }
    for tipo, opciones in CATALOGOS_INICIALES.items():
        for orden, (codigo, nombre) in enumerate(opciones):
            if (tipo, codigo) not in existentes:
                db.session.add(
                    Catalogo(tipo=tipo, codigo=codigo, nombre=nombre, orden=orden)
                )
    configs = {
        x.clave for x in db.session.execute(db.select(Configuracion)).scalars()
    }
    for clave, (valor, descripcion) in CONFIGURACIONES_INICIALES.items():
        if clave not in configs:
            db.session.add(
                Configuracion(clave=clave, valor=valor, descripcion=descripcion)
            )
    prefijo_anterior = db.session.execute(
        db.select(Configuracion).where(
            Configuracion.clave == "PREFIJO_DECLARACION"
        )
    ).scalar_one_or_none()
    if prefijo_anterior and prefijo_anterior.valor.strip().upper() == "DEC":
        prefijo_anterior.valor = "DNC"
    db.session.commit()


def sembrar_unidades_y_celulas():
    unidades = {
        unidad.codigo: unidad
        for unidad in db.session.execute(db.select(UnidadGestion)).scalars()
    }
    iniciales = [
        ("UG-PROD", "Producción"),
        ("UG-CAL", "Calidad"),
        ("UG-LOG", "Logística y Recepción"),
        ("UG-SIN", "Sin asignar"),
    ]
    for orden, (codigo, nombre) in enumerate(iniciales):
        if codigo not in unidades:
            unidades[codigo] = UnidadGestion(
                codigo=codigo,
                nombre=nombre,
                orden=orden,
                activo=codigo != "UG-SIN",
            )
            db.session.add(unidades[codigo])
    db.session.flush()

    existentes = {
        celula.nombre.casefold(): celula
        for celula in db.session.execute(db.select(Celula)).scalars()
    }
    catalogo_celulas = db.session.execute(
        db.select(Catalogo)
        .where(Catalogo.tipo == "CELULA")
        .order_by(Catalogo.orden, Catalogo.nombre)
    ).scalars().all()
    for orden, catalogo in enumerate(catalogo_celulas):
        if catalogo.nombre.casefold() in existentes:
            continue
        nombre_normalizado = catalogo.nombre.casefold()
        if "calidad" in nombre_normalizado:
            unidad = unidades["UG-CAL"]
        elif "recep" in nombre_normalizado or "log" in nombre_normalizado:
            unidad = unidades["UG-LOG"]
        elif "célula" in nombre_normalizado or "celula" in nombre_normalizado or "retrab" in nombre_normalizado:
            unidad = unidades["UG-PROD"]
        else:
            unidad = unidades["UG-SIN"]
        celula = Celula(
            codigo=catalogo.codigo,
            nombre=catalogo.nombre,
            codigo_equipos=catalogo.nombre,
            unidad_gestion=unidad,
            activo=catalogo.activo,
            orden=orden,
        )
        db.session.add(celula)
        existentes[catalogo.nombre.casefold()] = celula
    for celula in existentes.values():
        if not celula.codigo_equipos:
            celula.codigo_equipos = celula.nombre
    db.session.commit()


def config_valor(clave, predeterminado=""):
    fila = db.session.execute(
        db.select(Configuracion).where(Configuracion.clave == clave)
    ).scalar_one_or_none()
    return fila.valor if fila else predeterminado


def catalogo_activo(tipo):
    return db.session.execute(
        db.select(Catalogo)
        .where(Catalogo.tipo == tipo, Catalogo.activo.is_(True))
        .order_by(Catalogo.orden, Catalogo.nombre)
    ).scalars().all()


def celulas_activas():
    return db.session.execute(
        db.select(Celula)
        .join(Celula.unidad_gestion)
        .where(
            Celula.activo.is_(True),
            UnidadGestion.activo.is_(True),
        )
        .order_by(UnidadGestion.orden, Celula.orden, Celula.nombre)
    ).scalars().all()


def numero_declaracion(declaracion):
    prefijo = config_valor("PREFIJO_DECLARACION", "DNC").strip().upper()
    try:
        digitos = int(config_valor("DIGITOS_DECLARACION", "6"))
    except (TypeError, ValueError):
        digitos = 6
    digitos = min(max(digitos, 3), 12)
    return f"{prefijo}-{declaracion.id:0{digitos}d}"


def requerido(value, campo):
    valor = str(value or "").strip()
    if not valor:
        raise ValueError(f"Completá {campo}")
    return valor


def validar_legajo(value, campo="el legajo", obligatorio=True):
    valor = str(value or "").strip()
    if not valor:
        if obligatorio:
            raise ValueError(f"Completá {campo}")
        return None
    if not re.fullmatch(r"\d{1,5}", valor):
        raise ValueError(f"{campo} debe contener solamente números y hasta 5 dígitos")
    return valor


def actualizar_estado(declaracion):
    if any(
        item.requiere_validacion_logistica
        and item.fecha_validacion_logistica is None
        for item in declaracion.items
    ):
        declaracion.estado = "PENDIENTE_LOGISTICA"
    elif any(item.cantidad_retrabajo_pendiente > 0 for item in declaracion.items):
        resuelto = any(item.cantidad_retrabajo_resuelta > 0 for item in declaracion.items)
        declaracion.estado = "RESUELTA_PARCIAL" if resuelto else "PENDIENTE_RETRABAJO"
    elif declaracion.fecha_validacion and any(
        item.responsabilidad_estado == "PENDIENTE" for item in declaracion.items
    ):
        declaracion.estado = "PENDIENTE_INVESTIGACION"
    else:
        declaracion.estado = "CERRADA"


def pieza_requiere_control_logistica(codigo):
    codigo_normalizado = str(codigo or "").strip().upper()
    if not codigo_normalizado:
        return False
    return db.session.execute(
        db.select(PiezaControlLogistica.id).where(
            PiezaControlLogistica.codigo == codigo_normalizado,
            PiezaControlLogistica.activo.is_(True),
        )
    ).scalar_one_or_none() is not None


def actualizar_control_logistica(item, scrap_anterior=None):
    requiere = (
        item.cantidad_scrap_directo > 0
        and pieza_requiere_control_logistica(item.codigo_pieza)
    )
    cambio_cantidad = (
        scrap_anterior is not None
        and Decimal(scrap_anterior) != item.cantidad_scrap_directo
    )
    if not requiere:
        item.requiere_validacion_logistica = False
        item.cantidad_scrap_validada_logistica = None
        item.legajo_logistica = None
        item.fecha_validacion_logistica = None
        item.observacion_logistica = None
    elif not item.requiere_validacion_logistica or cambio_cantidad:
        item.requiere_validacion_logistica = True
        item.cantidad_scrap_validada_logistica = None
        item.legajo_logistica = None
        item.fecha_validacion_logistica = None
        item.observacion_logistica = None


def etapa_documento(declaracion):
    if not declaracion.fecha_validacion:
        return "AVISO INICIAL · PRODUCCIÓN"
    controles = [
        item
        for item in declaracion.items
        if item.requiere_validacion_logistica
    ]
    if controles:
        confirmados = sum(
            item.fecha_validacion_logistica is not None for item in controles
        )
        if confirmados == len(controles):
            return "VALIDACIÓN DE LOGÍSTICA COMPLETA"
        if confirmados:
            return "VALIDACIÓN DE LOGÍSTICA PARCIAL"
        return "VALIDADO POR CALIDAD · PENDIENTE DE LOGÍSTICA"
    return "VALIDADO POR CALIDAD"


def _fecha_reporte(valor, predeterminada):
    try:
        return date.fromisoformat(str(valor or ""))
    except ValueError:
        return predeterminada


def filtros_reporte_scrap(args):
    hoy = date.today()
    mes = str(args.get("mes", "")).strip()
    desde_texto = str(args.get("desde", "")).strip()
    hasta_texto = str(args.get("hasta", "")).strip()
    if mes and not re.fullmatch(r"[0-9]{4}-[0-9]{2}", mes):
        mes = ""
    if mes:
        anio, numero_mes = map(int, mes.split("-"))
        if 1 <= anio <= 9999 and 1 <= numero_mes <= 12:
            desde = date(anio, numero_mes, 1)
            hasta = date(anio, numero_mes, monthrange(anio, numero_mes)[1])
        else:
            mes = ""
    if not mes:
        desde_predeterminada = hoy.replace(day=1)
        desde = _fecha_reporte(desde_texto, desde_predeterminada)
        hasta = _fecha_reporte(hasta_texto, hoy)
    if not mes and desde_texto:
        desde = _fecha_reporte(desde_texto, desde)
    if not mes and hasta_texto:
        hasta = _fecha_reporte(hasta_texto, hasta)
    if desde > hasta:
        desde, hasta = hasta, desde
    return {
        "mes": mes,
        "desde": desde,
        "hasta": hasta,
        "cliente": str(args.get("cliente", "")).strip(),
        "pieza": str(args.get("pieza", "")).strip(),
        "componente": str(args.get("componente", "")).strip(),
        "celula": str(args.get("celula", "")).strip(),
        "equipo": str(args.get("equipo", "")).strip(),
        "motivo": str(args.get("motivo", "")).strip(),
        "estado": str(args.get("estado", "")).strip(),
        "proveedor": str(args.get("proveedor", "")).strip(),
        "dnc": str(args.get("dnc", "")).strip(),
        "origen_scrap": str(args.get("origen_scrap", "TODOS")).strip().upper(),
    }


def _contiene(valor, filtro):
    return not filtro or filtro.casefold() in str(valor or "").casefold()


def datos_reporte_scrap(filtros):
    consulta = (
        db.select(Declaracion)
        .options(
            selectinload(Declaracion.items).selectinload(DeclaracionItem.motivo),
            selectinload(Declaracion.items).selectinload(
                DeclaracionItem.intervenciones
            ),
        )
        .where(
            Declaracion.fecha >= filtros["desde"],
            Declaracion.fecha <= filtros["hasta"],
        )
        .order_by(Declaracion.fecha.desc(), Declaracion.id.desc())
    )
    declaraciones = db.session.execute(consulta).scalars().all()
    estructura_cache = {}
    detalle = []

    for declaracion in declaraciones:
        if not _contiene(declaracion.numero, filtros["dnc"]):
            continue
        if filtros["estado"] and declaracion.estado != filtros["estado"]:
            continue
        if not _contiene(declaracion.celula_detecta, filtros["celula"]):
            continue
        if not _contiene(declaracion.equipo, filtros["equipo"]):
            continue
        for item in declaracion.items:
            directo = Decimal(item.cantidad_scrap_directo or 0)
            retrabajo = Decimal(item.cantidad_scrap_retrabajo or 0)
            if filtros["origen_scrap"] == "DIRECTO":
                retrabajo = Decimal("0")
            elif filtros["origen_scrap"] == "RETRABAJO":
                directo = Decimal("0")
            if directo + retrabajo <= 0:
                continue
            cliente_visible = declaracion.cliente or item.codigo_cliente or ""
            if filtros["cliente"] and not (
                _contiene(declaracion.cliente, filtros["cliente"])
                or _contiene(item.codigo_cliente, filtros["cliente"])
            ):
                continue
            if filtros["pieza"] and not (
                _contiene(item.codigo_pieza, filtros["pieza"])
                or _contiene(item.descripcion, filtros["pieza"])
            ):
                continue
            motivo_visible = (
                f"{item.motivo.codigo} · {item.motivo.nombre}"
                if item.motivo else ""
            )
            if not _contiene(motivo_visible, filtros["motivo"]):
                continue
            proveedor_visible = " · ".join(
                x for x in [item.proveedor_numero, item.proveedor] if x
            )
            if not _contiene(proveedor_visible, filtros["proveedor"]):
                continue

            if item.codigo_pieza not in estructura_cache:
                estructura_cache[item.codigo_pieza] = obtener_componentes_finales(
                    item.codigo_pieza
                )
            componentes = estructura_cache[item.codigo_pieza]
            for componente in componentes:
                descripcion_componente = componente["descripcion"]
                if componente["codigo"] == item.codigo_pieza and not descripcion_componente:
                    descripcion_componente = item.descripcion or ""
                texto_componente = " ".join([
                    componente["codigo"],
                    descripcion_componente,
                    componente["material"],
                ])
                if not _contiene(texto_componente, filtros["componente"]):
                    continue
                factor = Decimal(componente["factor"])
                detalle.append({
                    "fecha": declaracion.fecha,
                    "dnc": declaracion.numero,
                    "declaracion_id": declaracion.id,
                    "cliente": cliente_visible,
                    "cliente_declarado": declaracion.cliente or "",
                    "codigo_cliente": item.codigo_cliente or "",
                    "celula": declaracion.celula_detecta,
                    "equipo": declaracion.equipo,
                    "estado": declaracion.estado,
                    "pieza": item.codigo_pieza,
                    "pieza_descripcion": item.descripcion or "",
                    "operacion": item.operacion_codigo or item.operacion_descripcion or "",
                    "hcp": item.trazabilidad,
                    "motivo": motivo_visible,
                    "proveedor": proveedor_visible,
                    "componente": componente["codigo"],
                    "componente_descripcion": descripcion_componente,
                    "material": componente["material"],
                    "nivel": componente["nivel"],
                    "factor": factor,
                    "scrap_directo": directo * factor,
                    "scrap_retrabajo": retrabajo * factor,
                    "scrap_total": (directo + retrabajo) * factor,
                    "unidad": item.unidad,
                })

    grupos = {}
    for fila in detalle:
        clave = (fila["componente"], fila["componente_descripcion"], fila["material"], fila["unidad"])
        if clave not in grupos:
            grupos[clave] = {
                "componente": fila["componente"],
                "descripcion": fila["componente_descripcion"],
                "material": fila["material"],
                "unidad": fila["unidad"],
                "scrap_directo": Decimal("0"),
                "scrap_retrabajo": Decimal("0"),
                "scrap_total": Decimal("0"),
                "dnc": set(),
                "piezas": set(),
            }
        grupo = grupos[clave]
        grupo["scrap_directo"] += fila["scrap_directo"]
        grupo["scrap_retrabajo"] += fila["scrap_retrabajo"]
        grupo["scrap_total"] += fila["scrap_total"]
        grupo["dnc"].add(fila["dnc"])
        grupo["piezas"].add(fila["pieza"])
    resumen = sorted(grupos.values(), key=lambda x: (-x["scrap_total"], x["componente"]))
    for fila in resumen:
        fila["cantidad_dnc"] = len(fila.pop("dnc"))
        fila["cantidad_piezas"] = len(fila.pop("piezas"))
    return resumen, detalle


def opciones_reporte_scrap():
    def distintos(columna):
        return {
            valor for valor in db.session.execute(
                db.select(columna).where(columna.is_not(None)).distinct()
            ).scalars() if valor
        }

    clientes = distintos(Declaracion.cliente) | distintos(DeclaracionItem.codigo_cliente)
    piezas = distintos(DeclaracionItem.codigo_pieza)
    celulas = distintos(Declaracion.celula_detecta)
    equipos = distintos(Declaracion.equipo)
    proveedores = distintos(DeclaracionItem.proveedor)
    return {
        "clientes": sorted(clientes),
        "piezas": sorted(piezas),
        "celulas": sorted(celulas),
        "equipos": sorted(equipos),
        "proveedores": sorted(proveedores),
        "motivos": db.session.execute(
            db.select(Motivo).order_by(Motivo.codigo)
        ).scalars().all(),
        "estados": [
            "PENDIENTE_CALIDAD", "PENDIENTE_LOGISTICA",
            "PENDIENTE_RETRABAJO", "RESUELTA_PARCIAL",
            "PENDIENTE_INVESTIGACION", "CERRADA",
        ],
    }


def opciones_formulario(incluir_turnos=False):
    motivos = db.session.execute(
        db.select(Motivo).where(Motivo.activo.is_(True)).order_by(Motivo.id)
    ).scalars().all()
    grupos_motivo = db.session.execute(
        db.select(GrupoMotivo)
        .where(GrupoMotivo.activo.is_(True))
        .order_by(GrupoMotivo.orden, GrupoMotivo.nombre)
    ).scalars().all()
    return {
        "motivos": motivos,
        "grupos_motivo": grupos_motivo,
        "sectores": SECTORES,
        "tipos_material": TIPOS_MATERIAL,
        "tipos_imputacion": TIPOS_IMPUTACION,
        "celulas": celulas_activas(),
        "turnos": listar_turnos() if incluir_turnos else [],
        "equipos": catalogo_activo("EQUIPO"),
        "proveedores": catalogo_activo("PROVEEDOR"),
        "lugares": catalogo_activo("LUGAR"),
        "modo_demostracion_productivo": current_app.config["PRODUCTIVE_DEMO_MODE"],
        "modo_demostracion_auxiliar": current_app.config["AUXILIARY_DEMO_MODE"],
        "config": {
            clave: config_valor(clave, valor[0])
            for clave, valor in CONFIGURACIONES_INICIALES.items()
        },
    }


def es_carga_operativa():
    return (request.path.startswith(("/produccion/", "/logistica/"))
            or request.endpoint == "calidad_scrap_nuevo")


def celulas_scrap_calidad():
    return [celula for celula in celulas_activas()
            if celula.nombre.strip().casefold() == "calidad"]


def cargar_item(data, motivos_validos, scrap_calidad=False):
    es_alerta = request.path in {"/produccion/alerta", "/logistica/informe"}
    cantidad = (
        entero_no_negativo(data.get("cantidad_detectada"), "la cantidad detectada")
        if es_alerta or scrap_calidad
        else decimal_no_negativo(
            data.get("cantidad_detectada"), "la cantidad detectada"
        )
    )
    scrap = decimal_no_negativo(data.get("cantidad_scrap_directo"), "el scrap directo")
    retrabajo = decimal_no_negativo(data.get("cantidad_a_retrabajo"), "la cantidad a retrabajo")
    if cantidad <= 0:
        raise ValueError("La cantidad detectada debe ser mayor a cero")
    liberada = decimal_no_negativo(data.get("cantidad_liberada"), "la cantidad liberada")
    if es_alerta and (scrap or retrabajo or liberada or data.get("retrabajo_estado", "PENDIENTE") != "PENDIENTE"):
        raise ValueError("La disposición del material debe ser definida por Calidad")
    if not es_alerta and scrap + retrabajo + liberada != cantidad:
        raise ValueError(
            f"En {data.get('codigo', 'un ítem')}, scrap + retrabajo debe ser igual "
            "a la cantidad detectada (incluyendo las liberadas)"
        )

    if scrap_calidad and (scrap != cantidad or retrabajo or liberada
                          or data.get("retrabajo_estado", "PENDIENTE") != "PENDIENTE"):
        raise ValueError("La declaración directa de Calidad debe destinar toda la cantidad a scrap")

    trazabilidad = requerido(data.get("trazabilidad"), "el HCP")
    digitos = int(config_valor("TRAZABILIDAD_DIGITOS", "6"))
    if not re.fullmatch(rf"\d{{{digitos}}}", trazabilidad):
        raise ValueError(f"El HCP debe tener exactamente {digitos} números")

    motivo_id = int(data.get("motivo_id", 0))
    if motivo_id not in motivos_validos:
        raise ValueError("Uno de los motivos seleccionados no es válido")
    motivo = db.session.get(Motivo, motivo_id)
    if scrap_calidad and (not motivo.grupo or not motivo.grupo.activo):
        raise ValueError("El grupo de la causa seleccionada no está habilitado")
    grupo_id = int(data.get("grupo_id") or motivo.grupo_id or 0)
    if not motivo.grupo_id or motivo.grupo_id != grupo_id:
        raise ValueError(
            f"La causa seleccionada no pertenece al grupo de {data.get('codigo', 'el renglón')}"
        )
    afectado_tipo = str(data.get("afectado_tipo", "")).strip() or None
    afectado_codigo = str(data.get("afectado_codigo", "")).strip() or None
    afectado_descripcion = (
        str(data.get("afectado_descripcion", "")).strip() or None
    )
    afectado_componente_codigo = (
        str(data.get("afectado_componente_codigo", "")).strip() or None
    )
    if es_carga_operativa():
        if motivo.tipo_accion == "COMPONENTE":
            if afectado_tipo != "COMPONENTE" or not afectado_codigo:
                raise ValueError(
                    f"Elegí el componente afectado para {data.get('codigo', 'el renglón')}"
                )
        elif motivo.tipo_accion == "MATERIA_PRIMA":
            if (
                afectado_tipo != "MATERIA_PRIMA"
                or not afectado_codigo
                or not afectado_componente_codigo
            ):
                raise ValueError(
                    f"Elegí la materia prima afectada para {data.get('codigo', 'el renglón')}"
                )
        elif motivo.tipo_accion == "PROCESO":
            if afectado_tipo != "PROCESO" or not afectado_codigo:
                raise ValueError(
                    f"Elegí el proceso relacionado para {data.get('codigo', 'el renglón')}"
                )

    tipo_material = requerido(data.get("tipo_material"), "el tipo de material")
    if tipo_material not in {x[0] for x in TIPOS_MATERIAL}:
        raise ValueError("Uno de los tipos de material no es válido")
    codigo_pieza = requerido(data.get("codigo"), "el código de pieza/material")
    operacion_codigo = str(data.get("operacion_codigo", "")).strip()
    operacion_descripcion = None
    if es_carga_operativa():
        operaciones_disponibles = listar_operaciones_pieza(codigo_pieza)
        if operaciones_disponibles:
            operacion = next(
                (
                    x for x in operaciones_disponibles
                    if str(x["codigo"]).strip() == operacion_codigo
                ),
                None,
            )
            if not operacion:
                raise ValueError(
                    f"Elegí una operación válida para {codigo_pieza}"
                )
            operacion_descripcion = str(operacion.get("titulo", "")).strip() or None
        else:
            operacion_codigo = ""
        if not validar_hcp(
            codigo_pieza,
            operacion_codigo,
            trazabilidad,
            tipo_material == "MATERIA_PRIMA",
        ):
            identificador_hcp = "lote" if tipo_material == "MATERIA_PRIMA" else "HCP"
            raise ValueError(
                f"El {identificador_hcp} {trazabilidad} no es válido para "
                f"{codigo_pieza}"
                + (f" en la operación {operacion_codigo}" if operacion_codigo else "")
            )

    tipo_imputacion = requerido(data.get("tipo_imputacion"), "el tipo de imputación")
    if tipo_imputacion not in {x[0] for x in TIPOS_IMPUTACION}:
        raise ValueError("Uno de los tipos de imputación no es válido")
    tipo_origen = str(data.get("tipo_origen", "INTERNO")).strip() or "INTERNO"
    proveedor_numero = str(data.get("proveedor_numero", "")).strip() or None
    proveedor = None
    remito = str(data.get("remito", "")).strip() or None
    if tipo_origen == "PROVEEDOR":
        if not proveedor_numero:
            raise ValueError("Ingresá el número del proveedor")
        proveedor_validado = buscar_proveedor(proveedor_numero)
        if not proveedor_validado:
            raise ValueError(
                f"No se encontró el proveedor N.º {proveedor_numero}"
            )
        proveedor = proveedor_validado["descripcion"]

    return DeclaracionItem(
        tipo_material=tipo_material,
        codigo_padre=str(data.get("codigo_padre", "")).strip() or None,
        codigo_pieza=codigo_pieza,
        codigo_cliente=str(data.get("codigo_cliente", "")).strip() or None,
        material=str(data.get("material", "")).strip() or None,
        descripcion=str(data.get("descripcion", "")).strip() or None,
        trazabilidad=trazabilidad,
        operacion_codigo=operacion_codigo or None,
        operacion_descripcion=operacion_descripcion,
        unidad=requerido(data.get("unidad", "PZS"), "la unidad").upper(),
        uso_estructura=decimal_no_negativo(data.get("uso", 1), "el uso de estructura", escala=4),
        cantidad_detectada=cantidad,
        cantidad_scrap_directo=scrap,
        cantidad_a_retrabajo=retrabajo,
        cantidad_liberada=liberada,
        motivo_id=motivo_id,
        sector_origen=requerido(data.get("sector_origen"), "el sector de origen"),
        celula_origen=requerido(data.get("celula_origen"), "la célula de origen"),
        operacion_origen=requerido(data.get("operacion_origen"), "la operación de origen"),
        legajo_origen=validar_legajo(
            data.get("legajo_origen"), "el legajo de origen", obligatorio=False
        ),
        tipo_imputacion=tipo_imputacion,
        tipo_origen=tipo_origen,
        proveedor_numero=proveedor_numero,
        proveedor=proveedor,
        remito=remito,
        afectado_tipo=afectado_tipo,
        afectado_codigo=afectado_codigo,
        afectado_descripcion=afectado_descripcion,
        afectado_componente_codigo=afectado_componente_codigo,
        observacion=str(data.get("observacion", "")).strip() or None,
    )


def cargar_retrabajo_inicial(item, data, motivos_validos):
    if item.cantidad_a_retrabajo <= 0:
        return
    estado = str(data.get("retrabajo_estado", "PENDIENTE")).strip().upper()
    if estado == "PENDIENTE":
        return
    if estado != "REALIZADO":
        raise ValueError("El estado inicial del retrabajo no es válido")

    cantidad_ok = decimal_no_negativo(
        data.get("cantidad_ok"), "la cantidad recuperada"
    )
    cantidad_scrap = decimal_no_negativo(
        data.get("cantidad_scrap_retrabajo"), "el scrap final"
    )
    if cantidad_ok + cantidad_scrap <= 0:
        raise ValueError(
            f"Informá el resultado del retrabajo de {item.codigo_pieza}"
        )
    if cantidad_ok + cantidad_scrap > item.cantidad_a_retrabajo:
        raise ValueError(
            f"El resultado del retrabajo de {item.codigo_pieza} supera "
            "la cantidad enviada"
        )

    motivo_scrap_id = None
    if cantidad_scrap > 0:
        motivo_scrap_id = int(data.get("motivo_scrap_retrabajo_id", 0))
        if motivo_scrap_id not in motivos_validos:
            raise ValueError(
                f"Seleccioná el motivo del scrap final de {item.codigo_pieza}"
            )

    try:
        minutos = int(data.get("minutos_retrabajo", 0))
        personas = int(data.get("personas_retrabajo", 0))
    except (TypeError, ValueError):
        raise ValueError("El tiempo y la cantidad de personas no son válidos")
    if minutos <= 0 or personas <= 0:
        raise ValueError("El tiempo y la cantidad de personas deben ser mayores a cero")

    item.intervenciones.append(
        RetrabajoIntervencion(
            fecha=date.fromisoformat(
                requerido(data.get("fecha_retrabajo"), "la fecha del retrabajo")
            ),
            operacion=requerido(
                data.get("operacion_retrabajo"), "la operación de retrabajo"
            ),
            celula=requerido(
                data.get("celula_retrabajo"), "la célula que retrabajó"
            ),
            legajo=validar_legajo(
                data.get("legajo_retrabajo"), "el legajo de retrabajo"
            ),
            minutos=minutos,
            cantidad_personas=personas,
            cantidad_ok=cantidad_ok,
            cantidad_scrap=cantidad_scrap,
            motivo_scrap_id=motivo_scrap_id,
            observaciones=str(data.get("observacion_retrabajo", "")).strip() or None,
        )
    )


def crear_declaracion_desde_formulario(es_alerta=False, scrap_calidad=False):
    items_json = json.loads(request.form.get("items_json", "[]"))
    if not isinstance(items_json, list) or not all(isinstance(x, dict) for x in items_json):
        raise ValueError("La lista de piezas o materiales no es válida")
    if not items_json:
        raise ValueError("Agregá al menos una pieza o material")

    es_carga_produccion = es_carga_operativa()
    celula_nombre = requerido(request.form.get("celula_detecta"), "la célula")
    if scrap_calidad:
        habilitadas = celulas_scrap_calidad()
        if len(habilitadas) != 1:
            raise ValueError("Debe haber una única célula Calidad activa dentro de una unidad habilitada")
        if celula_nombre.casefold() != habilitadas[0].nombre.strip().casefold():
            raise ValueError("Calidad solo puede declarar scrap desde la célula Calidad")
        celula_nombre = habilitadas[0].nombre
    unidad_gestion = None
    celula_codigo_equipos = None
    turno_id = None
    turno_nombre = None
    equipo_descripcion = None
    if es_carga_produccion:
        celula = db.session.execute(
            db.select(Celula)
            .options(selectinload(Celula.unidad_gestion))
            .where(
                Celula.nombre == celula_nombre,
                Celula.activo.is_(True),
            )
        ).scalar_one_or_none()
        if not celula or not celula.unidad_gestion.activo:
            raise ValueError("La célula seleccionada no está habilitada")
        unidad_gestion = celula.unidad_gestion.nombre
        celula_codigo_equipos = celula.codigo_equipos
        try:
            turno_id = int(request.form.get("turno_id", ""))
        except (TypeError, ValueError):
            raise ValueError("Seleccioná el turno")
        turno = next(
            (x for x in listar_turnos() if int(x["id"]) == turno_id),
            None,
        )
        if not turno:
            raise ValueError("El turno seleccionado no es válido")
        turno_nombre = turno["turno"]
        equipo_numero = requerido(request.form.get("equipo"), "el número de equipo")
        equipo = next(
            (
                x
                for x in listar_equipos(celula.codigo_equipos)
                if str(x["equipo"]).strip() == equipo_numero
            ),
            None,
        )
        if not equipo:
            raise ValueError(
                f"El equipo {equipo_numero} no pertenece a {celula_nombre}"
            )
        equipo_descripcion = str(equipo.get("descripcion") or "").strip() or None

    declaracion = Declaracion(
        fecha=date.fromisoformat(request.form["fecha"]),
        sector_declara=(
            unidad_gestion
            if es_carga_produccion
            else requerido(request.form.get("sector_declara"), "el sector")
        ),
        unidad_gestion=unidad_gestion,
        celula_detecta=celula_nombre,
        celula_codigo_equipos=(
            celula_codigo_equipos if es_carga_produccion else None
        ),
        legajo_declara=validar_legajo(
            request.form.get("legajo_declara"), "el legajo declarante"
        ),
        turno_id=turno_id,
        turno=turno_nombre,
        equipo=requerido(request.form.get("equipo"), "el equipo o turno"),
        equipo_descripcion=equipo_descripcion,
        cliente=str(request.form.get("cliente", "")).strip() or None,
        lugar_detectado=(
            celula_nombre
            if es_carga_produccion
            else requerido(
                request.form.get("lugar_detectado"),
                "dónde fue detectado",
            )
        ),
        observaciones=str(request.form.get("observaciones", "")).strip() or None,
    )
    motivos_validos = {
        m.id
        for m in db.session.execute(
            db.select(Motivo).where(Motivo.activo.is_(True))
        ).scalars()
    }
    for data in items_json:
        if scrap_calidad:
            data = {**data, "tipo_origen": "INTERNO", "tipo_imputacion": "CONFIRMADA",
                    "sector_origen": unidad_gestion, "celula_origen": celula_nombre,
                    "operacion_origen": "Ensayos de Calidad", "legajo_origen": declaracion.legajo_declara,
                    "proveedor_numero": "", "remito": ""}
        item = cargar_item(data, motivos_validos, scrap_calidad=scrap_calidad)
        if scrap_calidad:
            item.responsabilidad_estado = "CONFIRMADA"
            item.responsable_tipo = "INTERNO"
            item.responsable_sector = unidad_gestion
            item.responsable_celula = celula_nombre
            item.responsable_operacion = "Ensayos de Calidad"
            item.responsable_legajo = declaracion.legajo_declara
            item.observacion_calidad = requerido(data.get("observacion"), "el ensayo o motivo del scrap")
            if len(item.observacion_calidad) > 255:
                raise ValueError("La indicación de Calidad no puede superar los 255 caracteres")
        cargar_retrabajo_inicial(item, data, motivos_validos)
        if not es_alerta:
            validar_disposicion(item, item.cantidad_detectada, item.cantidad_scrap_directo,
                                item.cantidad_a_retrabajo, item.cantidad_liberada)
        declaracion.items.append(item)

    db.session.add(declaracion)
    db.session.flush()
    declaracion.numero = numero_declaracion(declaracion)
    if scrap_calidad:
        declaracion.legajo_calidad = declaracion.legajo_declara
        declaracion.fecha_validacion = datetime.now()
        declaracion.observaciones_calidad = "Scrap declarado directamente por Calidad."
        for item in declaracion.items:
            actualizar_control_logistica(item)
    if es_alerta:
        declaracion.estado = "PENDIENTE_CALIDAD"
        for item in declaracion.items:
            item.responsabilidad_estado = "PENDIENTE"
    else:
        actualizar_estado(declaracion)
    db.session.commit()
    return declaracion


def registrar_rutas(app):
    def sesion_vencida():
        inicio = session.get("sesion_iniciada_en")

        if not inicio:
            return True

        try:
            ahora = time.time()

            if ahora - float(inicio) >= app.config["SESSION_MAX_AGE_SECONDS"]:
                return True

            return False

        except (TypeError, ValueError):
            return True

    def inicio_para_rol(rol):
        return {
            "PRODUCCION": "produccion_inicio",
            "CALIDAD": "calidad_bandeja",
            "LOGISTICA": "logistica_inicio",
            "ADMIN": "inicio",
            "CONSULTA": "analisis.panel",
        }.get(rol, "login")

    def espera_json():
        return (request.path.startswith("/api/")
                or request.headers.get("X-Requested-With", "").lower() in {"fetch", "xmlhttprequest"}
                or request.accept_mimetypes.best == "application/json")

    def pedir_login():
        if espera_json():
            return jsonify(error="sesion_vencida", mensaje="La sesión venció. Ingresá nuevamente."), 401
        return redirect(url_for("login"))

    @app.before_request
    def controlar_acceso():
        if app.config.get("AUTH_DISABLED"):
            return None
        if request.endpoint == "static":
            return None
        if session.get("usuario_id") and sesion_vencida():
            session.clear()

            return pedir_login()
        if request.endpoint in {"login", "logout"}:
            return None

        usuario_id = session.get("usuario_id")
        usuario = db.session.get(Usuario, usuario_id) if usuario_id else None
        if not usuario or not usuario.activo:
            session.clear()
            return pedir_login()

        g.usuario = usuario
        if usuario.rol not in NOMBRES_ROL:
            abort(403)
        if usuario.rol == "ADMIN" or request.path == "/":
            return None
        if usuario.rol == "CONSULTA":
            lectura = {"analisis.panel", "analisis.excel", "declaraciones", "declaracion_detalle",
                       "reporte_scrap", "reporte_scrap_excel"}
            if request.method in {"GET", "HEAD"} and request.endpoint in lectura:
                return None
            abort(403)
        if request.endpoint == "produccion_nueva" and usuario.rol == "PRODUCCION":
            if request.method == "GET":
                return redirect(url_for("produccion_alerta"))
            abort(403)
        if request.path.startswith("/api/"):
            return None
        permisos = {
            "PRODUCCION": ("/produccion",),
            "CALIDAD": ("/calidad",),
            "LOGISTICA": ("/logistica",),
        }
        if any(request.path == prefijo or request.path.startswith(prefijo + "/")
               for prefijo in permisos.get(usuario.rol, ())):
            return None
        abort(403)

    @app.context_processor
    def contexto_usuario():
        if app.config.get("AUTH_DISABLED"):
            rol_demo = (
                "CALIDAD"
                if request.path.startswith("/calidad")
                else "LOGISTICA"
                if request.path.startswith("/logistica")
                else "PRODUCCION"
                if request.path.startswith("/produccion")
                else "ADMIN"
            )
            return {
                "usuario_actual": None,
                "rol_actual": rol_demo,
                "nombre_rol_actual": NOMBRES_ROL[rol_demo],
            }
        usuario = getattr(g, "usuario", None)
        return {
            "usuario_actual": usuario,
            "rol_actual": usuario.rol if usuario else None,
            "nombre_rol_actual": NOMBRES_ROL.get(usuario.rol, "") if usuario else "",
        }

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("usuario_id"):
            if not sesion_vencida():
                usuario = db.session.get(Usuario, session["usuario_id"])
                if usuario and usuario.activo:
                    return redirect(url_for(inicio_para_rol(usuario.rol)))
            session.clear()
        if request.method == "POST":
            nombre_usuario = str(request.form.get("usuario", "")).strip().lower()
            clave = str(request.form.get("clave", ""))
            usuario = db.session.execute(
                db.select(Usuario).where(Usuario.usuario == nombre_usuario)
            ).scalar_one_or_none()
            if not usuario or not usuario.activo or not usuario.verificar_clave(clave):
                flash("Usuario o contraseña incorrectos.", "error")
                return render_template("login.html", usuario=nombre_usuario), 401
            session.clear()
            session["usuario_id"] = usuario.id
            session["rol"] = usuario.rol
            session["sesion_iniciada_en"] = time.time()
            session.permanent = True
            return redirect(url_for(inicio_para_rol(usuario.rol)))
        return render_template("login.html", usuario="")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.errorhandler(403)
    def acceso_denegado(_error):
        if espera_json():
            return jsonify(error="acceso_denegado", mensaje="No tenés permiso para realizar esta acción."), 403
        return render_template("403.html"), 403

    @app.get("/")
    def raiz():
        if app.config.get("AUTH_DISABLED"):
            return redirect(url_for("produccion_inicio"))
        return redirect(url_for(inicio_para_rol(g.usuario.rol)))

    @app.get("/produccion")
    def produccion_inicio():
        return render_template(
            "produccion_inicio.html",
            **contexto_produccion_inicio(),
        )

    def contexto_produccion_inicio():
        pendientes = db.session.execute(
            db.select(DeclaracionItem)
            .options(selectinload(DeclaracionItem.declaracion))
            .where(DeclaracionItem.cantidad_a_retrabajo > 0)
            .order_by(DeclaracionItem.id.desc())
        ).scalars().all()
        pendientes = [
            item for item in pendientes if item.cantidad_retrabajo_pendiente > 0
        ][:5]
        return {
            "pendientes": pendientes,
            "empresa": config_valor("NOMBRE_EMPRESA", "C.G.R. S.A."),
        }

    @app.get("/produccion/inicio/contenido")
    def produccion_inicio_contenido():
        respuesta = make_response(
            render_template(
                "_produccion_inicio_contenido.html",
                **contexto_produccion_inicio(),
            )
        )
        respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    def contexto_logistica():
        piezas_configuradas = db.session.execute(
            db.select(PiezaControlLogistica)
            .where(PiezaControlLogistica.activo.is_(True))
            .order_by(PiezaControlLogistica.codigo)
        ).scalars().all()
        items = db.session.execute(
            db.select(DeclaracionItem)
            .options(
                selectinload(DeclaracionItem.declaracion),
                selectinload(DeclaracionItem.motivo).selectinload(Motivo.grupo),
            )
            .where(DeclaracionItem.requiere_validacion_logistica.is_(True))
            .order_by(DeclaracionItem.id.desc())
        ).scalars().all()
        pendientes = [
            item for item in items if item.fecha_validacion_logistica is None
        ]
        validados = [
            item for item in items if item.fecha_validacion_logistica is not None
        ][:10]
        return {
            "pendientes": pendientes,
            "validados": validados,
            "piezas_configuradas": piezas_configuradas,
        }

    def contexto_impresion_automatica(endpoint_detalle):
        declaracion_id = request.args.get("imprimir", type=int)
        if not declaracion_id:
            return {}
        return {
            "auto_print_url": url_for(
                endpoint_detalle,
                declaracion_id=declaracion_id,
                imprimir=1,
            ),
            "auto_print_revision": request.args.get("revision", "actual"),
        }

    @app.get("/logistica")
    def logistica_inicio():
        return render_template(
            "logistica_inicio.html",
            empresa=config_valor("NOMBRE_EMPRESA", "C.G.R. S.A."),
            **contexto_logistica(),
            **contexto_impresion_automatica("logistica_declaracion_detalle"),
        )

    @app.get("/logistica/validaciones/contenido")
    def logistica_validaciones_contenido():
        respuesta = make_response(
            render_template(
                "_logistica_validaciones.html",
                **contexto_logistica(),
            )
        )
        respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    @app.get("/logistica/piezas-control")
    def logistica_piezas_control():
        piezas = db.session.execute(
            db.select(PiezaControlLogistica)
            .where(PiezaControlLogistica.activo.is_(True))
            .order_by(PiezaControlLogistica.codigo)
        ).scalars().all()
        respuesta = make_response(render_template(
            "logistica_piezas_control.html", piezas=piezas
        ))
        respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    def escritura(consulta):
        return consulta.with_for_update() if request.method == "POST" else consulta

    def bloquear_por_item(item_id):
        if request.method == "POST":
            declaracion_id = db.session.execute(
                db.select(DeclaracionItem.declaracion_id).where(DeclaracionItem.id == item_id)
            ).scalar_one_or_none()
            if declaracion_id is not None:
                db.session.execute(db.select(Declaracion).where(
                    Declaracion.id == declaracion_id
                ).with_for_update()).scalar_one()

    @app.post("/logistica/validaciones/<int:item_id>")
    def logistica_validar_scrap(item_id):
        bloquear_por_item(item_id)
        item = db.session.execute(
            db.select(DeclaracionItem)
            .options(selectinload(DeclaracionItem.declaracion))
            .where(DeclaracionItem.id == item_id)
        ).scalar_one_or_none()
        if not item:
            abort(404)
        if not item.requiere_validacion_logistica:
            flash("Esta pieza no requiere control de Logística", "error")
            return redirect(url_for("logistica_inicio"))
        if item.fecha_validacion_logistica is not None:
            flash("La cantidad de esta pieza ya fue validada", "error")
            return redirect(url_for("logistica_inicio"))
        try:
            cantidad = entero_no_negativo(
                request.form.get("cantidad"),
                "la cantidad recibida para scrap",
            )
            legajo = validar_legajo(
                request.form.get("legajo"), "el legajo de Logística"
            )
            observacion = (
                str(request.form.get("observacion", "")).strip() or None
            )
            cantidad_calidad = Decimal(item.cantidad_scrap_directo)
            if Decimal(cantidad) != cantidad_calidad and not observacion:
                raise ValueError(
                    "Explicá la diferencia entre la cantidad de Calidad y la recibida"
                )
            item.cantidad_scrap_validada_logistica = cantidad
            item.legajo_logistica = legajo
            item.fecha_validacion_logistica = datetime.now()
            item.observacion_logistica = observacion
            actualizar_estado(item.declaracion)
            db.session.commit()
            flash(
                f"Cantidad de {item.codigo_pieza} validada por Logística",
                "ok",
            )
            revision = int(item.fecha_validacion_logistica.timestamp() * 1000)
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for("logistica_inicio")), 400
        return redirect(url_for(
            "logistica_inicio",
            imprimir=item.declaracion_id,
            revision=revision,
        ))

    def formulario_alerta():
        contexto = opciones_formulario(incluir_turnos=True)
        if request.method == "POST":
            try:
                declaracion = crear_declaracion_desde_formulario(es_alerta=True)
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                db.session.rollback()
                flash(str(exc), "error")
                return render_template(
                    "produccion_nueva.html",
                    hoy=date.today(),
                    modo="ALERTA",
                    **contexto,
                ), 400
            except Exception:
                db.session.rollback()
                app.logger.exception("No se pudo generar la alerta")
                flash("No se pudo generar la alerta. Revisá los datos.", "error")
                return render_template(
                    "produccion_nueva.html",
                    hoy=date.today(),
                    modo="ALERTA",
                    **contexto,
                ), 500
            return redirect(
                url_for(
                    "logistica_exito"
                    if request.path.startswith("/logistica")
                    else "produccion_exito",
                    declaracion_id=declaracion.id,
                )
            )
        return render_template(
            "produccion_nueva.html",
            hoy=date.today(),
            modo="ALERTA",
            **contexto,
        )

    @app.route("/produccion/alerta", methods=["GET", "POST"])
    def produccion_alerta():
        return formulario_alerta()

    @app.route("/logistica/informe", methods=["GET", "POST"])
    def logistica_informe():
        return formulario_alerta()

    @app.route("/calidad/scrap/nuevo", methods=["GET", "POST"])
    def calidad_scrap_nuevo():
        contexto = opciones_formulario(incluir_turnos=True)
        contexto["celulas"] = celulas_scrap_calidad()
        contexto.update(scrap_calidad=True, base_formulario="base.html")
        if len(contexto["celulas"]) != 1:
            flash("Debe haber una única célula Calidad activa dentro de una unidad habilitada.", "error")
        if request.method == "POST":
            try:
                declaracion = crear_declaracion_desde_formulario(scrap_calidad=True)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                db.session.rollback()
                # Los detalles de validación se muestran en español sin excepciones técnicas.
                flash("No se pudo declarar el scrap. Revisá la célula, el equipo, las piezas, cantidades, causas y HCP.", "error")
                return render_template("produccion_nueva.html", hoy=date.today(), modo="SCRAP", **contexto), 400
            except Exception:
                db.session.rollback()
                app.logger.exception("No se pudo declarar scrap desde Calidad")
                flash("No se pudo guardar el scrap. Intentá nuevamente.", "error")
                return render_template("produccion_nueva.html", hoy=date.today(), modo="SCRAP", **contexto), 500
            flash(f"{declaracion.numero} registrada y validada por Calidad", "ok")
            return redirect(url_for("calidad_bandeja", imprimir=declaracion.id,
                                    revision=int(declaracion.fecha_validacion.timestamp() * 1000)))
        return render_template("produccion_nueva.html", hoy=date.today(), modo="SCRAP", **contexto)

    @app.route("/produccion/nueva/<modo>", methods=["GET", "POST"])
    def produccion_nueva(modo):
        modo = modo.upper()
        if modo not in {"SCRAP", "RETRABAJO"}:
            abort(404)
        contexto = opciones_formulario(incluir_turnos=True)
        if request.method == "POST":
            try:
                declaracion = crear_declaracion_desde_formulario()
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                db.session.rollback()
                flash(str(exc), "error")
                return render_template(
                    "produccion_nueva.html",
                    hoy=date.today(),
                    modo=modo,
                    **contexto,
                ), 400
            except Exception:
                db.session.rollback()
                app.logger.exception("No se pudo guardar desde Producción")
                flash("No se pudo guardar. Revisá los datos cargados.", "error")
                return render_template(
                    "produccion_nueva.html",
                    hoy=date.today(),
                    modo=modo,
                    **contexto,
                ), 500
            return redirect(
                url_for("produccion_exito", declaracion_id=declaracion.id)
            )
        return render_template(
            "produccion_nueva.html", hoy=date.today(), modo=modo, **contexto
        )

    @app.get("/produccion/listo/<int:declaracion_id>")
    def produccion_exito(declaracion_id):
        return mostrar_exito(
            declaracion_id,
            "produccion_inicio",
            "produccion_alerta",
            "produccion_declaracion_detalle",
        )

    @app.get("/logistica/listo/<int:declaracion_id>")
    def logistica_exito(declaracion_id):
        return mostrar_exito(
            declaracion_id,
            "logistica_inicio",
            "logistica_informe",
            "logistica_declaracion_detalle",
        )

    def mostrar_exito(
        declaracion_id,
        endpoint_inicio,
        endpoint_nuevo,
        endpoint_impresion=None,
    ):
        declaracion = db.get_or_404(Declaracion, declaracion_id)
        return render_template(
            "produccion_exito.html",
            declaracion=declaracion,
            endpoint_inicio=endpoint_inicio,
            endpoint_nuevo=endpoint_nuevo,
            endpoint_impresion=endpoint_impresion,
            impresion_automatica=bool(endpoint_impresion),
        )

    @app.get("/gestion")
    def inicio():
        ultimas = db.session.execute(
            db.select(Declaracion).order_by(Declaracion.id.desc()).limit(5)
        ).scalars().all()
        pendientes = db.session.execute(
            db.select(DeclaracionItem)
            .options(selectinload(DeclaracionItem.declaracion))
            .where(DeclaracionItem.cantidad_a_retrabajo > 0)
            .order_by(DeclaracionItem.id.desc())
        ).scalars().all()
        pendientes = [item for item in pendientes if item.cantidad_retrabajo_pendiente > 0][:5]
        return render_template("inicio.html", ultimos=ultimas, pendientes=pendientes)

    def contexto_calidad_bandeja():
        alertas = db.session.execute(
            db.select(Declaracion)
            .options(selectinload(Declaracion.items))
            .where(Declaracion.estado == "PENDIENTE_CALIDAD")
            .order_by(Declaracion.creado_en)
        ).scalars().all()
        investigaciones = db.session.execute(
            db.select(Declaracion)
            .options(selectinload(Declaracion.items))
            .where(Declaracion.estado == "PENDIENTE_INVESTIGACION")
            .order_by(Declaracion.fecha_validacion)
        ).scalars().all()
        validadas = db.session.execute(
            db.select(Declaracion)
            .options(selectinload(Declaracion.items))
            .where(
                Declaracion.fecha_validacion.is_not(None),
                Declaracion.estado != "PENDIENTE_INVESTIGACION",
            )
            .order_by(Declaracion.fecha_validacion.desc())
            .limit(10)
        ).scalars().all()
        return {
            "alertas": alertas,
            "investigaciones": investigaciones,
            "validadas": validadas,
        }

    @app.get("/calidad")
    def calidad_bandeja():
        return render_template(
            "calidad_bandeja.html",
            **contexto_calidad_bandeja(),
            **contexto_impresion_automatica("calidad_declaracion_detalle"),
        )

    @app.get("/calidad/bandeja/contenido")
    def calidad_bandeja_contenido():
        respuesta = make_response(
            render_template(
                "_calidad_bandeja_contenido.html",
                **contexto_calidad_bandeja(),
            )
        )
        respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    @app.route("/calidad/<int:declaracion_id>/validar", methods=["GET", "POST"])
    def calidad_validar(declaracion_id):
        declaracion = db.session.execute(escritura(
            db.select(Declaracion)
            .options(
                selectinload(Declaracion.items).selectinload(DeclaracionItem.motivo)
            )
            .where(Declaracion.id == declaracion_id)
        )).scalar_one_or_none()
        if not declaracion:
            abort(404)
        grupos = db.session.execute(
            db.select(GrupoMotivo)
            .options(selectinload(GrupoMotivo.motivos))
            .where(GrupoMotivo.activo.is_(True))
            .order_by(GrupoMotivo.orden, GrupoMotivo.nombre)
        ).scalars().all()
        operaciones_por_item = {
            item.id: listar_operaciones_pieza(item.codigo_pieza)
            for item in declaracion.items
        }
        hcp_validado_por_item = {
            item.id: bool(
                (
                    not operaciones_por_item[item.id]
                    or any(
                        str(x["codigo"]).strip() == str(item.operacion_codigo or "")
                        for x in operaciones_por_item[item.id]
                    )
                )
                and validar_hcp(
                    item.codigo_pieza,
                    item.operacion_codigo or "",
                    item.trazabilidad,
                    item.tipo_material == "MATERIA_PRIMA",
                )
            )
            for item in declaracion.items
        }
        if request.method == "POST":
            try:
                legajo = validar_legajo(
                    request.form.get("legajo_calidad"), "el legajo de Calidad"
                )
                motivos_validos = {
                    m.id
                    for grupo in grupos
                    for m in grupo.motivos
                    if m.activo
                }
                for item in declaracion.items:
                    scrap_anterior = item.cantidad_scrap_directo
                    operacion_codigo = str(item.operacion_codigo or "").strip()
                    operaciones_disponibles = operaciones_por_item[item.id]
                    operacion_seleccionada = next(
                        (
                            x for x in operaciones_disponibles
                            if str(x["codigo"]).strip() == operacion_codigo
                        ),
                        None,
                    )
                    if operaciones_disponibles and not operacion_seleccionada:
                        raise ValueError(
                            f"La operación registrada para {item.codigo_pieza} "
                            "ya no está disponible"
                        )
                    if not operaciones_disponibles:
                        operacion_codigo = ""
                    hcp = str(item.trazabilidad).strip()
                    hcp_digitos = int(config_valor("TRAZABILIDAD_DIGITOS", "6"))
                    if not re.fullmatch(rf"\d{{{hcp_digitos}}}", hcp):
                        raise ValueError(
                            f"El HCP de {item.codigo_pieza} debe tener exactamente "
                            f"{hcp_digitos} números"
                        )
                    if not validar_hcp(
                        item.codigo_pieza,
                        operacion_codigo,
                        hcp,
                        item.tipo_material == "MATERIA_PRIMA",
                    ):
                        identificador_hcp = (
                            "lote" if item.tipo_material == "MATERIA_PRIMA" else "HCP"
                        )
                        raise ValueError(
                            f"El {identificador_hcp} {hcp} no es válido para "
                            f"{item.codigo_pieza}"
                            + (
                                f" en la operación {operacion_codigo}"
                                if operacion_codigo
                                else ""
                            )
                        )
                    scrap = decimal_no_negativo(
                        requerido(request.form.get(f"scrap_{item.id}"), "las cantidades de destino"), "la cantidad scrap"
                    )
                    retrabajo = decimal_no_negativo(
                        requerido(request.form.get(f"retrabajo_{item.id}"), "las cantidades de destino"), "la cantidad a retrabajo"
                    )
                    liberada = decimal_no_negativo(
                        requerido(request.form.get(f"liberada_{item.id}"), "las cantidades de destino"), "la cantidad liberada"
                    )
                    validar_disposicion(item, item.cantidad_detectada, scrap, retrabajo, liberada)
                    observacion_item = (
                        str(request.form.get(f"obs_item_{item.id}", "")).strip()
                        or None
                    )
                    if not observacion_item:
                        raise ValueError(
                            f"Escribí la indicación de Calidad para "
                            f"{item.codigo_pieza}"
                        )
                    motivo_id = int(request.form.get(f"motivo_{item.id}", 0))
                    if motivo_id not in motivos_validos:
                        raise ValueError(
                            f"Seleccioná la causa validada de {item.codigo_pieza}"
                        )
                    motivo = db.session.get(Motivo, motivo_id)
                    grupo_id = int(
                        request.form.get(f"grupo_{item.id}")
                        or motivo.grupo_id
                        or 0
                    )
                    if motivo.grupo_id != grupo_id:
                        raise ValueError(
                            f"La causa validada de {item.codigo_pieza} no pertenece "
                            "al grupo seleccionado"
                        )
                    responsabilidad_estado = str(
                        request.form.get(
                            f"resp_estado_{item.id}",
                            item.responsabilidad_estado or "PENDIENTE",
                        )
                    ).strip().upper()
                    if responsabilidad_estado not in {
                        "CONFIRMADA",
                        "PROBABLE",
                        "PENDIENTE",
                        "NO_ATRIBUIBLE",
                    }:
                        raise ValueError(
                            f"El estado de responsabilidad de {item.codigo_pieza} no es válido"
                        )
                    responsable_tipo = (
                        str(request.form.get(f"resp_tipo_{item.id}", "")).strip().upper()
                        or None
                    )
                    responsable_sector = (
                        str(request.form.get(f"resp_sector_{item.id}", "")).strip()
                        or None
                    )
                    responsable_celula = (
                        str(request.form.get(f"resp_celula_{item.id}", "")).strip()
                        or None
                    )
                    responsable_operacion = (
                        str(request.form.get(f"resp_operacion_{item.id}", "")).strip()
                        or None
                    )
                    responsable_legajo = validar_legajo(
                        request.form.get(f"resp_legajo_{item.id}"),
                        "el legajo relacionado",
                        obligatorio=False,
                    )
                    responsable_proveedor_numero = (
                        str(
                            request.form.get(
                                f"resp_proveedor_numero_{item.id}",
                                "",
                            )
                        ).strip()
                        or None
                    )
                    responsable_proveedor = None
                    if (
                        responsabilidad_estado in {"CONFIRMADA", "PROBABLE"}
                        and responsable_tipo == "PROVEEDOR"
                    ):
                        if not responsable_proveedor_numero:
                            raise ValueError(
                                f"Ingresá el número del proveedor responsable de "
                                f"{item.codigo_pieza}"
                            )
                        proveedor_validado = buscar_proveedor(
                            responsable_proveedor_numero
                        )
                        if not proveedor_validado:
                            raise ValueError(
                                f"No se encontró el proveedor N.º "
                                f"{responsable_proveedor_numero}"
                            )
                        responsable_proveedor = proveedor_validado["descripcion"]
                    if responsabilidad_estado == "CONFIRMADA":
                        if responsable_tipo == "INTERNO" and not (
                            responsable_celula and responsable_operacion
                        ):
                            raise ValueError(
                                f"Completá célula y proceso responsable de {item.codigo_pieza}"
                            )
                        if responsable_tipo not in {"INTERNO", "PROVEEDOR"}:
                            raise ValueError(
                                f"Elegí el tipo de responsable de {item.codigo_pieza}"
                            )
                    if responsabilidad_estado in {"PENDIENTE", "NO_ATRIBUIBLE"}:
                        responsable_tipo = None
                        responsable_sector = None
                        responsable_celula = None
                        responsable_operacion = None
                        responsable_legajo = None
                        responsable_proveedor_numero = None
                        responsable_proveedor = None
                    item.cantidad_scrap_directo = scrap
                    item.cantidad_a_retrabajo = retrabajo
                    item.cantidad_liberada = liberada
                    item.motivo_id = motivo_id
                    item.responsabilidad_estado = responsabilidad_estado
                    item.responsable_tipo = responsable_tipo
                    item.responsable_sector = responsable_sector
                    item.responsable_celula = responsable_celula
                    item.responsable_operacion = responsable_operacion
                    item.responsable_legajo = responsable_legajo
                    item.responsable_proveedor_numero = responsable_proveedor_numero
                    item.responsable_proveedor = responsable_proveedor
                    item.observacion_calidad = observacion_item
                    actualizar_control_logistica(item, scrap_anterior)
                declaracion.legajo_calidad = legajo
                declaracion.fecha_validacion = datetime.now()
                declaracion.observaciones_calidad = (
                    str(request.form.get("observaciones_calidad", "")).strip() or None
                )
                actualizar_estado(declaracion)
                db.session.commit()
                pendientes_logistica = sum(
                    1
                    for item in declaracion.items
                    if item.requiere_validacion_logistica
                    and item.fecha_validacion_logistica is None
                )
                mensaje = f"{declaracion.numero} validada por Calidad"
                if pendientes_logistica:
                    mensaje += (
                        f" · {pendientes_logistica} renglón"
                        f"{'es' if pendientes_logistica != 1 else ''} enviado"
                        f"{'s' if pendientes_logistica != 1 else ''} a Logística"
                    )
                flash(mensaje, "ok")
                revision = int(declaracion.fecha_validacion.timestamp() * 1000)
                return redirect(url_for(
                    "calidad_bandeja",
                    imprimir=declaracion.id,
                    revision=revision,
                ))
            except (ValueError, TypeError) as exc:
                db.session.rollback()
                flash(str(exc), "error")
        return render_template(
            "calidad_validar.html",
            declaracion=declaracion,
            grupos=grupos,
            hcp_digitos=int(config_valor("TRAZABILIDAD_DIGITOS", "6")),
            operaciones_por_item=operaciones_por_item,
            hcp_validado_por_item=hcp_validado_por_item,
        )

    @app.get("/declaraciones")
    @app.get("/vales")
    def declaraciones():
        lista = db.session.execute(
            db.select(Declaracion).order_by(Declaracion.id.desc())
        ).scalars().all()
        return render_template("declaraciones.html", declaraciones=lista)

    @app.get("/reportes/scrap")
    def reporte_scrap():
        filtros = filtros_reporte_scrap(request.args)
        resumen, detalle = datos_reporte_scrap(filtros)
        metricas = {
            "componentes": len(resumen),
            "dnc": len({fila["dnc"] for fila in detalle}),
            "piezas": len({fila["pieza"] for fila in detalle}),
            "scrap_total": sum(
                (fila["scrap_total"] for fila in resumen), Decimal("0")
            ),
        }
        return render_template(
            "reporte_scrap.html",
            filtros=filtros,
            resumen=resumen,
            detalle=detalle,
            metricas=metricas,
            opciones=opciones_reporte_scrap(),
        )

    @app.get("/reportes/scrap/excel")
    def reporte_scrap_excel():
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        filtros = filtros_reporte_scrap(request.args)
        resumen, detalle = datos_reporte_scrap(filtros)
        libro = Workbook()
        hoja = libro.active
        hoja.title = "Resumen por componente"
        encabezado = [
            "Componente final", "Descripción", "Material", "Unidad",
            "Scrap directo", "Scrap de retrabajo", "Scrap total",
            "Cantidad DNC", "Piezas origen distintas",
        ]
        hoja.append(encabezado)
        for fila in resumen:
            hoja.append([
                fila["componente"], fila["descripcion"], fila["material"],
                fila["unidad"], float(fila["scrap_directo"]),
                float(fila["scrap_retrabajo"]), float(fila["scrap_total"]),
                fila["cantidad_dnc"], fila["cantidad_piezas"],
            ])

        detalle_hoja = libro.create_sheet("Detalle trazable")
        detalle_hoja.append([
            "Fecha", "DNC", "Cliente", "Código cliente", "Célula", "Equipo",
            "Estado", "Pieza origen", "Descripción pieza", "Operación", "HCP/Lote",
            "Motivo", "Proveedor", "Componente final", "Descripción componente",
            "Material", "Nivel", "Factor estructura", "Scrap directo",
            "Scrap de retrabajo", "Scrap total", "Unidad",
        ])
        for fila in detalle:
            detalle_hoja.append([
                fila["fecha"], fila["dnc"], fila["cliente"], fila["codigo_cliente"],
                fila["celula"], fila["equipo"], fila["estado"], fila["pieza"],
                fila["pieza_descripcion"], fila["operacion"], fila["hcp"],
                fila["motivo"], fila["proveedor"], fila["componente"],
                fila["componente_descripcion"], fila["material"], fila["nivel"],
                float(fila["factor"]), float(fila["scrap_directo"]),
                float(fila["scrap_retrabajo"]), float(fila["scrap_total"]),
                fila["unidad"],
            ])

        filtros_hoja = libro.create_sheet("Filtros aplicados")
        filtros_hoja.append(["Filtro", "Valor"])
        for clave, valor in filtros.items():
            filtros_hoja.append([
                clave.replace("_", " ").title(),
                valor.isoformat() if isinstance(valor, date) else valor or "Todos",
            ])
        filtros_hoja.append(["Generado", datetime.now().strftime("%d/%m/%Y %H:%M")])

        filtros_hoja.append(["Criterio de estructura", "Estructura productiva vigente al consultar; no es una estructura histórica de la DNC."])
        for planilla in libro.worksheets:
            for fila in planilla.iter_rows():
                for celda in fila:
                    if isinstance(celda.value, str):
                        celda.data_type = "s"
            planilla.freeze_panes = "A2"
            planilla.auto_filter.ref = planilla.dimensions
            for celda in planilla[1]:
                celda.font = Font(bold=True, color="FFFFFF")
                celda.fill = PatternFill("solid", fgColor="1769E0")
                celda.alignment = Alignment(vertical="center")
            planilla.row_dimensions[1].height = 25
            for columna in planilla.columns:
                letra = get_column_letter(columna[0].column)
                ancho = min(max(len(str(celda.value or "")) for celda in columna) + 2, 42)
                planilla.column_dimensions[letra].width = max(ancho, 11)
        for fila in hoja.iter_rows(min_row=2, min_col=5, max_col=7):
            for celda in fila:
                celda.number_format = "0.000"
        for fila in detalle_hoja.iter_rows(min_row=2, min_col=18, max_col=21):
            for celda in fila:
                celda.number_format = "0.0000" if celda.column == 18 else "0.000"

        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        nombre = f"scrap_componentes_{filtros['desde']}_{filtros['hasta']}.xlsx"
        return send_file(
            salida,
            as_attachment=True,
            download_name=nombre,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.get("/produccion/declaraciones")
    def produccion_declaraciones():
        return render_historial_sector(
            base_historial="base_produccion.html",
            titulo_historial="Declaraciones informadas",
            descripcion_historial=(
                "Consultá el material declarado y volvé a imprimir cualquier informe."
            ),
            endpoint_detalle="produccion_declaracion_detalle",
            endpoint_nuevo="produccion_alerta",
            texto_nuevo="＋ Nuevo informe",
        )

    @app.get("/calidad/declaraciones")
    def calidad_declaraciones():
        return render_historial_sector(
            base_historial="base.html",
            titulo_historial="Historial de declaraciones",
            descripcion_historial=(
                "Revisá las decisiones de Calidad y reimprimí el documento actualizado."
            ),
            endpoint_detalle="calidad_declaracion_detalle",
        )

    @app.get("/logistica/declaraciones")
    def logistica_declaraciones():
        return render_historial_sector(
            base_historial="base_produccion.html",
            titulo_historial="Historial de declaraciones",
            descripcion_historial=(
                "Consultá y reimprimí los DNC recibidos o validados por Logística."
            ),
            endpoint_detalle="logistica_declaracion_detalle",
            endpoint_nuevo="logistica_informe",
            texto_nuevo="＋ Nuevo informe",
        )

    def render_historial_sector(
        base_historial,
        titulo_historial,
        descripcion_historial,
        endpoint_detalle,
        endpoint_nuevo=None,
        texto_nuevo=None,
    ):
        lista = db.session.execute(
            db.select(Declaracion)
            .options(selectinload(Declaracion.items))
            .order_by(Declaracion.id.desc())
            .limit(500)
        ).scalars().all()
        return render_template(
            "produccion_declaraciones.html",
            declaraciones=lista,
            base_historial=base_historial,
            titulo_historial=titulo_historial,
            descripcion_historial=descripcion_historial,
            endpoint_detalle=endpoint_detalle,
            endpoint_nuevo=endpoint_nuevo,
            texto_nuevo=texto_nuevo,
        )

    @app.route("/declaraciones/nueva", methods=["GET", "POST"])
    @app.route("/vales/nuevo", methods=["GET", "POST"])
    def declaracion_nueva():
        contexto = opciones_formulario()
        if request.method == "GET":
            return render_template(
                "declaracion_nueva.html", hoy=date.today(), **contexto
            )

        try:
            declaracion = crear_declaracion_desde_formulario()
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return render_template(
                "declaracion_nueva.html", hoy=date.today(), **contexto
            ), 400
        except Exception:
            db.session.rollback()
            app.logger.exception("No se pudo guardar la declaración")
            flash("No se pudo guardar la declaración. Revisá los datos.", "error")
            return render_template(
                "declaracion_nueva.html", hoy=date.today(), **contexto
            ), 500

        flash(f"Declaración {declaracion.numero} guardada correctamente", "ok")
        return redirect(url_for("declaracion_detalle", declaracion_id=declaracion.id))

    def cargar_declaracion_detallada(declaracion_id):
        return db.session.execute(escritura(
            db.select(Declaracion)
            .options(
                selectinload(Declaracion.items).selectinload(DeclaracionItem.motivo),
                selectinload(Declaracion.items)
                .selectinload(DeclaracionItem.intervenciones)
                .selectinload(RetrabajoIntervencion.motivo_scrap),
            )
            .where(Declaracion.id == declaracion_id)
        )).scalar_one_or_none()

    @app.get("/declaraciones/<int:declaracion_id>")
    @app.get("/vales/<int:declaracion_id>")
    def declaracion_detalle(declaracion_id):
        return render_detalle_sector(declaracion_id)

    @app.route("/declaraciones/<int:declaracion_id>/editar", methods=["GET", "POST"])
    def declaracion_editar(declaracion_id):
        declaracion = cargar_declaracion_detallada(declaracion_id)
        if not declaracion:
            abort(404)
        motivos = db.session.execute(
            db.select(Motivo)
            .options(selectinload(Motivo.grupo))
            .order_by(Motivo.grupo_id, Motivo.codigo)
        ).scalars().all()
        if request.method == "POST":
            try:
                actualizar_declaracion_admin(declaracion, {m.id for m in motivos})
                db.session.commit()
                flash(f"{declaracion.numero} actualizada correctamente", "ok")
                return redirect(url_for(
                    "declaracion_detalle", declaracion_id=declaracion.id
                ))
            except (ValueError, TypeError, InvalidOperation) as exc:
                db.session.rollback()
                flash(str(exc), "error")
        return render_template(
            "declaracion_editar.html",
            declaracion=declaracion,
            motivos=motivos,
            tipos_material=TIPOS_MATERIAL,
            tipos_imputacion=TIPOS_IMPUTACION,
        )

    @app.post("/declaraciones/<int:declaracion_id>/eliminar")
    def declaracion_eliminar(declaracion_id):
        declaracion = cargar_declaracion_detallada(declaracion_id)
        if not declaracion:
            abort(404)
        numero = declaracion.numero
        if str(request.form.get("confirmacion", "")).strip() != numero:
            flash(f"Escribí {numero} para confirmar la eliminación", "error")
            return redirect(url_for(
                "declaracion_detalle", declaracion_id=declaracion.id
            )), 400
        db.session.delete(declaracion)
        db.session.commit()
        flash(f"La declaración {numero} fue eliminada", "ok")
        return redirect(url_for("declaraciones"))

    def actualizar_declaracion_admin(declaracion, motivos_validos):
        era_alerta = declaracion.estado == "PENDIENTE_CALIDAD"
        declaracion.fecha = date.fromisoformat(
            requerido(request.form.get("fecha"), "la fecha")
        )
        declaracion.sector_declara = requerido(
            request.form.get("sector_declara"), "el sector declarante"
        )
        declaracion.unidad_gestion = (
            str(request.form.get("unidad_gestion", "")).strip() or None
        )
        declaracion.celula_detecta = requerido(
            request.form.get("celula_detecta"), "la célula"
        )
        declaracion.legajo_declara = validar_legajo(
            request.form.get("legajo_declara"), "el legajo declarante"
        )
        declaracion.turno = str(request.form.get("turno", "")).strip() or None
        declaracion.equipo = requerido(request.form.get("equipo"), "el equipo")
        declaracion.equipo_descripcion = (
            str(request.form.get("equipo_descripcion", "")).strip() or None
        )
        declaracion.cliente = str(request.form.get("cliente", "")).strip() or None
        declaracion.lugar_detectado = declaracion.celula_detecta
        declaracion.observaciones = (
            str(request.form.get("observaciones", "")).strip() or None
        )
        declaracion.legajo_calidad = validar_legajo(
            request.form.get("legajo_calidad"),
            "el legajo de Calidad",
            obligatorio=False,
        )
        declaracion.observaciones_calidad = (
            str(request.form.get("observaciones_calidad", "")).strip() or None
        )

        digitos_hcp = int(config_valor("TRAZABILIDAD_DIGITOS", "6"))
        tipos_material_validos = {valor for valor, _ in TIPOS_MATERIAL}
        imputaciones_validas = {valor for valor, _ in TIPOS_IMPUTACION}
        responsabilidades_validas = {
            "PENDIENTE", "PROBABLE", "CONFIRMADA", "NO_ATRIBUIBLE"
        }
        tipos_origen_validos = {"INTERNO", "PROVEEDOR", "DESCONOCIDO"}

        for item in declaracion.items:
            identidad_anterior = (item.codigo_pieza, item.trazabilidad, item.operacion_codigo)
            scrap_anterior = item.cantidad_scrap_directo
            prefijo = f"item_{item.id}_"
            tipo_material = requerido(
                request.form.get(prefijo + "tipo_material"), "el tipo de material"
            )
            if tipo_material not in tipos_material_validos:
                raise ValueError("Uno de los tipos de material no es válido")
            item.tipo_material = tipo_material
            item.codigo_pieza = requerido(
                request.form.get(prefijo + "codigo_pieza"), "el código de pieza"
            ).upper()
            item.descripcion = (
                str(request.form.get(prefijo + "descripcion", "")).strip() or None
            )
            item.operacion_codigo = (
                str(request.form.get(prefijo + "operacion_codigo", "")).strip()
                or None
            )
            item.operacion_descripcion = (
                str(request.form.get(prefijo + "operacion_descripcion", "")).strip()
                or None
            )
            trazabilidad = requerido(
                request.form.get(prefijo + "trazabilidad"), "el HCP o lote"
            )
            if not re.fullmatch(rf"\d{{{digitos_hcp}}}", trazabilidad):
                raise ValueError(
                    f"El HCP/lote de {item.codigo_pieza} debe tener exactamente "
                    f"{digitos_hcp} números"
                )
            item.trazabilidad = trazabilidad
            item.unidad = requerido(
                request.form.get(prefijo + "unidad"), "la unidad"
            ).upper()
            cantidad = decimal_no_negativo(
                requerido(request.form.get(prefijo + "cantidad_detectada"), "la cantidad informada"),
                f"la cantidad de {item.codigo_pieza}",
            )
            if cantidad <= 0:
                raise ValueError(
                    f"La cantidad de {item.codigo_pieza} debe ser mayor a cero"
                )
            if item.unidad == "PZS":
                entero_no_negativo(cantidad, "La cantidad de piezas")
            item.cantidad_detectada = cantidad

            motivo_id = int(request.form.get(prefijo + "motivo_id", 0))
            if motivo_id not in motivos_validos:
                raise ValueError(f"Elegí un motivo válido para {item.codigo_pieza}")
            item.motivo_id = motivo_id
            item.afectado_tipo = (
                str(request.form.get(prefijo + "afectado_tipo", "")).strip() or None
            )
            item.afectado_codigo = (
                str(request.form.get(prefijo + "afectado_codigo", "")).strip() or None
            )
            item.afectado_descripcion = (
                str(request.form.get(prefijo + "afectado_descripcion", "")).strip()
                or None
            )
            item.afectado_componente_codigo = (
                str(request.form.get(
                    prefijo + "afectado_componente_codigo", ""
                )).strip() or None
            )
            item.observacion = (
                str(request.form.get(prefijo + "observacion", "")).strip() or None
            )
            item.observacion_calidad = (
                str(request.form.get(prefijo + "observacion_calidad", "")).strip()
                or None
            )

            if declaracion.fecha_validacion or declaracion.estado != "PENDIENTE_CALIDAD":
                scrap = decimal_no_negativo(
                    requerido(request.form.get(prefijo + "cantidad_scrap_directo"), "las cantidades de destino"),
                    f"el scrap de {item.codigo_pieza}",
                )
                retrabajo = decimal_no_negativo(
                    requerido(request.form.get(prefijo + "cantidad_a_retrabajo"), "las cantidades de destino"),
                    f"el retrabajo de {item.codigo_pieza}",
                )
                liberada = decimal_no_negativo(
                    requerido(request.form.get(prefijo + "cantidad_liberada"), "las cantidades de destino"),
                    f"la cantidad liberada de {item.codigo_pieza}",
                )
                validar_disposicion(item, cantidad, scrap, retrabajo, liberada)
                item.cantidad_scrap_directo = scrap
                item.cantidad_a_retrabajo = retrabajo
                item.cantidad_liberada = liberada

            tipo_imputacion = requerido(
                request.form.get(prefijo + "tipo_imputacion"),
                "el tipo de imputación",
            )
            if tipo_imputacion not in imputaciones_validas:
                raise ValueError("Uno de los tipos de imputación no es válido")
            item.tipo_imputacion = tipo_imputacion
            tipo_origen = requerido(
                request.form.get(prefijo + "tipo_origen"), "el tipo de origen"
            )
            if tipo_origen not in tipos_origen_validos:
                raise ValueError("Uno de los tipos de origen no es válido")
            item.tipo_origen = tipo_origen
            item.sector_origen = requerido(
                request.form.get(prefijo + "sector_origen"), "el sector de origen"
            )
            item.celula_origen = requerido(
                request.form.get(prefijo + "celula_origen"), "la célula de origen"
            )
            item.operacion_origen = requerido(
                request.form.get(prefijo + "operacion_origen"),
                "la operación de origen",
            )
            item.legajo_origen = validar_legajo(
                request.form.get(prefijo + "legajo_origen"),
                "el legajo de origen",
                obligatorio=False,
            )
            item.proveedor_numero = (
                str(request.form.get(prefijo + "proveedor_numero", "")).strip()
                or None
            )
            item.proveedor = (
                str(request.form.get(prefijo + "proveedor", "")).strip() or None
            )
            item.remito = (
                str(request.form.get(prefijo + "remito", "")).strip() or None
            )

            responsabilidad = requerido(
                request.form.get(prefijo + "responsabilidad_estado"),
                "el estado de responsabilidad",
            )
            if responsabilidad not in responsabilidades_validas:
                raise ValueError("Uno de los estados de responsabilidad no es válido")
            item.responsabilidad_estado = responsabilidad
            item.responsable_tipo = (
                str(request.form.get(prefijo + "responsable_tipo", "")).strip()
                or None
            )
            item.responsable_sector = (
                str(request.form.get(prefijo + "responsable_sector", "")).strip()
                or None
            )
            item.responsable_celula = (
                str(request.form.get(prefijo + "responsable_celula", "")).strip()
                or None
            )
            item.responsable_operacion = (
                str(request.form.get(prefijo + "responsable_operacion", "")).strip()
                or None
            )
            item.responsable_legajo = validar_legajo(
                request.form.get(prefijo + "responsable_legajo"),
                "el legajo responsable",
                obligatorio=False,
            )
            item.responsable_proveedor_numero = (
                str(request.form.get(
                    prefijo + "responsable_proveedor_numero", ""
                )).strip() or None
            )
            item.responsable_proveedor = (
                str(request.form.get(prefijo + "responsable_proveedor", "")).strip()
                or None
            )

            requiere_logistica = request.form.get(
                prefijo + "requiere_validacion_logistica"
            ) == "1"
            requiere_logistica = requiere_logistica and item.cantidad_scrap_directo > 0
            cambio_control = (scrap_anterior != item.cantidad_scrap_directo or
                              identidad_anterior != (item.codigo_pieza, item.trazabilidad, item.operacion_codigo))
            item.requiere_validacion_logistica = requiere_logistica
            if requiere_logistica:
                cantidad_logistica_texto = str(request.form.get(
                    prefijo + "cantidad_scrap_validada_logistica", ""
                )).strip()
                if cambio_control:
                    cantidad_logistica_texto = ""
                if cantidad_logistica_texto:
                    item.cantidad_scrap_validada_logistica = entero_no_negativo(
                        cantidad_logistica_texto,
                        f"la cantidad validada por Logística de {item.codigo_pieza}",
                    )
                    item.legajo_logistica = validar_legajo(
                        request.form.get(prefijo + "legajo_logistica"),
                        "el legajo de Logística",
                    )
                    if not item.fecha_validacion_logistica:
                        item.fecha_validacion_logistica = datetime.now()
                else:
                    item.cantidad_scrap_validada_logistica = None
                    item.legajo_logistica = None
                    item.fecha_validacion_logistica = None
                item.observacion_logistica = (
                    str(request.form.get(prefijo + "observacion_logistica", "")).strip()
                    or None
                )
                if cambio_control:
                    item.observacion_logistica = None
                if (item.cantidad_scrap_validada_logistica is not None
                    and item.cantidad_scrap_validada_logistica != item.cantidad_scrap_directo
                    and not item.observacion_logistica):
                    raise ValueError("Explicá la diferencia entre la cantidad de Calidad y la recibida")
            else:
                item.cantidad_scrap_validada_logistica = None
                item.legajo_logistica = None
                item.fecha_validacion_logistica = None
                item.observacion_logistica = None

        if declaracion.fecha_validacion or not era_alerta:
            actualizar_estado(declaracion)
        else:
            declaracion.estado = "PENDIENTE_CALIDAD"

    @app.get("/produccion/declaraciones/<int:declaracion_id>")
    def produccion_declaracion_detalle(declaracion_id):
        return render_detalle_sector(
            declaracion_id,
            base_detalle="base_produccion.html",
            endpoint_volver="produccion_declaraciones",
            endpoint_retrabajo="produccion_retrabajos",
        )

    @app.get("/calidad/declaraciones/<int:declaracion_id>")
    def calidad_declaracion_detalle(declaracion_id):
        return render_detalle_sector(
            declaracion_id,
            base_detalle="base.html",
            endpoint_volver="calidad_declaraciones",
            mostrar_retrabajo=False,
        )

    @app.get("/logistica/declaraciones/<int:declaracion_id>")
    def logistica_declaracion_detalle(declaracion_id):
        return render_detalle_sector(
            declaracion_id,
            base_detalle="base_produccion.html",
            endpoint_volver="logistica_declaraciones",
            mostrar_retrabajo=False,
        )

    def render_detalle_sector(declaracion_id, **contexto):
        declaracion = cargar_declaracion_detallada(declaracion_id)
        if not declaracion:
            abort(404)
        return render_template(
            "declaracion_detalle.html",
            declaracion=declaracion,
            impreso_en=datetime.now(),
            etapa_impresion=etapa_documento(declaracion),
            imprimir_automaticamente=request.args.get("imprimir") == "1",
            **contexto,
        )

    @app.get("/retrabajos")
    def retrabajos():
        items = db.session.execute(
            db.select(DeclaracionItem)
            .options(
                selectinload(DeclaracionItem.declaracion),
                selectinload(DeclaracionItem.motivo),
                selectinload(DeclaracionItem.intervenciones),
            )
            .where(DeclaracionItem.cantidad_a_retrabajo > 0)
            .order_by(DeclaracionItem.id.desc())
        ).scalars().all()
        pendientes = [item for item in items if item.cantidad_retrabajo_pendiente > 0]
        cerrados = [item for item in items if item.cantidad_retrabajo_pendiente == 0]
        return render_template(
            "retrabajos.html", pendientes=pendientes, cerrados=cerrados
        )

    @app.get("/produccion/retrabajos")
    def produccion_retrabajos():
        items = db.session.execute(
            db.select(DeclaracionItem)
            .options(
                selectinload(DeclaracionItem.declaracion),
                selectinload(DeclaracionItem.motivo),
                selectinload(DeclaracionItem.intervenciones),
            )
            .where(DeclaracionItem.cantidad_a_retrabajo > 0)
            .order_by(DeclaracionItem.id.desc())
        ).scalars().all()
        pendientes = [item for item in items if item.cantidad_retrabajo_pendiente > 0]
        return render_template(
            "produccion_retrabajos.html", pendientes=pendientes
        )

    @app.get("/produccion/retrabajos/historial")
    def produccion_retrabajos_historial():
        intervenciones = db.session.execute(
            db.select(RetrabajoIntervencion)
            .options(
                selectinload(RetrabajoIntervencion.item)
                .selectinload(DeclaracionItem.declaracion),
                selectinload(RetrabajoIntervencion.item)
                .selectinload(DeclaracionItem.motivo)
                .selectinload(Motivo.grupo),
            )
            .order_by(
                RetrabajoIntervencion.fecha.desc(),
                RetrabajoIntervencion.id.desc(),
            )
            .limit(500)
        ).scalars().all()
        return render_template(
            "produccion_retrabajos_historial.html",
            intervenciones=intervenciones,
            total_recuperadas=sum(
                (x.cantidad_ok for x in intervenciones), Decimal("0")
            ),
            total_scrap=sum(
                (x.cantidad_scrap for x in intervenciones), Decimal("0")
            ),
            total_horas=sum((x.horas_hombre for x in intervenciones), 0),
        )

    @app.route("/retrabajos/<int:item_id>/registrar", methods=["GET", "POST"])
    @app.route(
        "/produccion/retrabajos/<int:item_id>/registrar", methods=["GET", "POST"]
    )
    def registrar_retrabajo(item_id):
        bloquear_por_item(item_id)
        vista_produccion = request.path.startswith("/produccion/")
        plantilla = (
            "produccion_retrabajo_registrar.html"
            if vista_produccion
            else "retrabajo_registrar.html"
        )
        item = db.session.execute(
            db.select(DeclaracionItem)
            .options(
                selectinload(DeclaracionItem.declaracion),
                selectinload(DeclaracionItem.intervenciones),
            )
            .where(DeclaracionItem.id == item_id)
        ).scalar_one_or_none()
        if not item or item.cantidad_a_retrabajo <= 0:
            abort(404)
        opciones = opciones_formulario()
        celulas = opciones["celulas"]

        if request.method == "POST":
            try:
                if item.declaracion.estado == "PENDIENTE_CALIDAD":
                    raise ValueError("Calidad debe definir el destino antes de registrar un retrabajo")
                if item.cantidad_retrabajo_pendiente <= 0:
                    raise ValueError("Este retrabajo ya está cerrado")
                cantidad_ok = entero_no_negativo(
                    request.form.get("cantidad_ok"), "la cantidad recuperada"
                )
                cantidad_scrap = entero_no_negativo(
                    request.form.get("cantidad_scrap"), "la cantidad scrap"
                )
                if Decimal(cantidad_ok + cantidad_scrap) != item.cantidad_retrabajo_pendiente:
                    raise ValueError(
                        "Piezas recuperadas + piezas a scrap debe ser igual "
                        f"a la cantidad pendiente ({item.cantidad_retrabajo_pendiente:g})"
                    )

                motivo_scrap_id = item.motivo_id if cantidad_scrap > 0 else None

                celula = requerido(request.form.get("celula"), "la célula")
                if celula not in {x.nombre for x in celulas}:
                    raise ValueError("Seleccioná una célula válida de la lista")
                minutos = entero_no_negativo(
                    requerido(request.form.get("minutos"), "los minutos"),
                    "el tiempo en minutos",
                )
                personas = entero_no_negativo(
                    requerido(request.form.get("cantidad_personas"), "las personas"),
                    "la cantidad de personas",
                )
                if minutos <= 0 or personas <= 0:
                    raise ValueError(
                        "El tiempo y la cantidad de personas deben ser mayores a cero"
                    )
                try:
                    fecha_retrabajo = date.fromisoformat(
                        requerido(request.form.get("fecha"), "la fecha")
                    )
                except ValueError as exc:
                    if str(exc).startswith("Completá"):
                        raise
                    raise ValueError("La fecha del retrabajo no es válida")
                if fecha_retrabajo > date.today():
                    raise ValueError("La fecha del retrabajo no puede ser futura")
                trabajo_realizado = requerido(
                    request.form.get("operacion"),
                    "el trabajo efectuado y su resultado",
                )
                if len(trabajo_realizado) > 120:
                    raise ValueError(
                        "El trabajo efectuado no puede superar los 120 caracteres"
                    )

                intervencion = RetrabajoIntervencion(
                    fecha=fecha_retrabajo,
                    operacion=trabajo_realizado,
                    celula=celula,
                    legajo=validar_legajo(
                        request.form.get("legajo"), "el legajo del retrabajo"
                    ),
                    minutos=minutos,
                    cantidad_personas=personas,
                    cantidad_ok=cantidad_ok,
                    cantidad_scrap=cantidad_scrap,
                    motivo_scrap_id=motivo_scrap_id,
                    observaciones=None,
                )
                item.intervenciones.append(intervencion)
                db.session.flush()
                actualizar_estado(item.declaracion)
                db.session.commit()
            except (ValueError, KeyError) as exc:
                db.session.rollback()
                flash(str(exc), "error")
                return render_template(
                    plantilla,
                    item=item,
                    celulas=celulas,
                    hoy=date.today(),
                ), 400
            except Exception:
                db.session.rollback()
                app.logger.exception("No se pudo registrar el retrabajo")
                flash("No se pudo registrar el resultado del retrabajo.", "error")
                return render_template(
                    plantilla,
                    item=item,
                    celulas=celulas,
                    hoy=date.today(),
                ), 500

            flash("Resultado de retrabajo guardado", "ok")
            if vista_produccion:
                return redirect(url_for("produccion_retrabajos"))
            if item.cantidad_retrabajo_pendiente > 0:
                return redirect(url_for("registrar_retrabajo", item_id=item.id))
            return redirect(
                url_for("declaracion_detalle", declaracion_id=item.declaracion_id)
            )

        return render_template(
            plantilla,
            item=item,
            celulas=celulas,
            hoy=date.today(),
        )

    @app.get("/gestion/configuracion")
    def gestion_configuracion():
        return render_template("gestion_configuracion.html")

    @app.get("/gestion/usuarios")
    def gestion_usuarios():
        usuarios = db.session.execute(
            db.select(Usuario).order_by(Usuario.id)
        ).scalars().all()
        return render_template("gestion_usuarios.html", usuarios=usuarios)

    @app.post("/gestion/usuarios/consulta")
    def gestion_usuario_consulta():
        from sqlalchemy.exc import IntegrityError
        nombre_usuario = str(request.form.get("usuario", "")).strip().lower()
        nombre = str(request.form.get("nombre", "")).strip()
        clave = str(request.form.get("clave", ""))
        if not re.fullmatch(r"[a-z0-9_.-]{1,40}", nombre_usuario):
            flash("El usuario debe tener hasta 40 letras sin acentos, números, puntos, guiones o guiones bajos.", "error")
        elif not nombre or len(nombre) > 120:
            flash("Completá un nombre de hasta 120 caracteres.", "error")
        elif not 8 <= len(clave) <= 72 or clave != request.form.get("confirmacion"):
            flash("Ingresá y repetí una contraseña de entre 8 y 72 caracteres.", "error")
        elif db.session.execute(db.select(Usuario.id).where(Usuario.usuario == nombre_usuario)).scalar_one_or_none():
            flash("Ese nombre de usuario ya existe.", "error")
        else:
            cuenta = Usuario(usuario=nombre_usuario, nombre=nombre, rol="CONSULTA", activo=True, clave_hash="")
            cuenta.cambiar_clave(clave)
            db.session.add(cuenta)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Ese nombre de usuario ya existe.", "error")
            else:
                flash("Usuario de consulta creado. Solo puede visualizar, imprimir y exportar.", "ok")
        return redirect(url_for("gestion_usuarios"))

    @app.post("/gestion/usuarios/<int:usuario_id>/clave")
    def gestion_usuario_clave(usuario_id):
        usuario = db.get_or_404(Usuario, usuario_id)
        clave = str(request.form.get("clave", ""))
        confirmacion = str(request.form.get("confirmacion", ""))
        if len(clave) < 4:
            flash("La contraseña debe tener al menos 4 caracteres.", "error")
        elif len(clave) > 72:
            flash("La contraseña no puede superar los 72 caracteres.", "error")
        elif clave != confirmacion:
            flash("Las contraseñas no coinciden.", "error")
        else:
            usuario.cambiar_clave(clave)
            db.session.commit()
            flash(f"Contraseña de {usuario.nombre} actualizada.", "ok")
        return redirect(url_for("gestion_usuarios"))

    @app.route("/gestion/unidades-gestion", methods=["GET", "POST"])
    def gestion_unidades():
        if request.method == "POST":
            codigo = requerido(request.form.get("codigo"), "el código")
            nombre = requerido(request.form.get("nombre"), "el nombre")
            existe = db.session.execute(
                db.select(UnidadGestion).where(
                    or_(
                        UnidadGestion.codigo == codigo,
                        UnidadGestion.nombre == nombre,
                    )
                )
            ).scalar_one_or_none()
            if existe:
                flash("Ya existe una unidad con ese código o nombre", "error")
            else:
                orden = db.session.execute(
                    db.select(db.func.max(UnidadGestion.orden))
                ).scalar() or 0
                db.session.add(
                    UnidadGestion(codigo=codigo, nombre=nombre, orden=orden + 1)
                )
                db.session.commit()
                flash("Unidad de gestión agregada", "ok")
            return redirect(url_for("gestion_unidades"))
        unidades = db.session.execute(
            db.select(UnidadGestion)
            .options(selectinload(UnidadGestion.celulas))
            .order_by(UnidadGestion.orden, UnidadGestion.nombre)
        ).scalars().all()
        return render_template("gestion_unidades.html", unidades=unidades)

    @app.post("/gestion/unidades-gestion/<int:unidad_id>/editar")
    def gestion_unidad_editar(unidad_id):
        unidad = db.get_or_404(UnidadGestion, unidad_id)
        codigo = requerido(request.form.get("codigo"), "el código")
        nombre = requerido(request.form.get("nombre"), "el nombre")
        existe = db.session.execute(
            db.select(UnidadGestion).where(
                UnidadGestion.id != unidad.id,
                or_(
                    UnidadGestion.codigo == codigo,
                    UnidadGestion.nombre == nombre,
                ),
            )
        ).scalar_one_or_none()
        if existe:
            flash("Otra unidad ya usa ese código o nombre", "error")
        else:
            unidad.codigo = codigo
            unidad.nombre = nombre
            db.session.commit()
            flash("Unidad actualizada", "ok")
        return redirect(url_for("gestion_unidades"))

    @app.post("/gestion/unidades-gestion/<int:unidad_id>/alternar")
    def gestion_unidad_alternar(unidad_id):
        unidad = db.get_or_404(UnidadGestion, unidad_id)
        unidad.activo = not unidad.activo
        db.session.commit()
        return redirect(url_for("gestion_unidades"))

    @app.post("/gestion/unidades-gestion/<int:unidad_id>/eliminar")
    def gestion_unidad_eliminar(unidad_id):
        unidad = db.get_or_404(UnidadGestion, unidad_id)
        if unidad.celulas:
            flash(
                "No se puede eliminar una unidad que todavía tiene células. "
                "Movelas o eliminalas primero.",
                "error",
            )
        else:
            nombre = unidad.nombre
            db.session.delete(unidad)
            db.session.commit()
            flash(f"Unidad {nombre} eliminada", "ok")
        return redirect(url_for("gestion_unidades"))

    @app.post("/gestion/unidades-gestion/<int:unidad_id>/celulas")
    def gestion_celula_agregar(unidad_id):
        unidad = db.get_or_404(UnidadGestion, unidad_id)
        codigo = requerido(request.form.get("codigo"), "el código")
        nombre = requerido(request.form.get("nombre"), "el nombre de la célula")
        codigo_equipos = requerido(
            request.form.get("codigo_equipos"),
            "el código de búsqueda de equipos",
        )
        existe = db.session.execute(
            db.select(Celula).where(
                or_(
                    Celula.codigo == codigo,
                    Celula.nombre == nombre,
                    Celula.codigo_equipos == codigo_equipos,
                )
            )
        ).scalar_one_or_none()
        if existe:
            flash(
                f"El código, nombre o código de búsqueda de equipos ya está usado por "
                f"{existe.nombre} dentro de {existe.unidad_gestion.nombre}",
                "error",
            )
        else:
            orden = db.session.execute(
                db.select(db.func.max(Celula.orden)).where(
                    Celula.unidad_gestion_id == unidad.id
                )
            ).scalar() or 0
            db.session.add(
                Celula(
                    codigo=codigo,
                    nombre=nombre,
                    codigo_equipos=codigo_equipos,
                    unidad_gestion=unidad,
                    orden=orden + 1,
                )
            )
            db.session.commit()
            flash("Célula agregada", "ok")
        return redirect(url_for("gestion_unidades"))

    @app.post("/gestion/celulas/<int:celula_id>/editar")
    def gestion_celula_editar(celula_id):
        celula = db.get_or_404(Celula, celula_id)
        codigo = requerido(request.form.get("codigo"), "el código")
        nombre = requerido(request.form.get("nombre"), "el nombre")
        codigo_equipos = requerido(
            request.form.get("codigo_equipos"),
            "el código de búsqueda de equipos",
        )
        unidad_id = int(requerido(request.form.get("unidad_id"), "la unidad"))
        unidad = db.get_or_404(UnidadGestion, unidad_id)
        existe = db.session.execute(
            db.select(Celula).where(
                Celula.id != celula.id,
                or_(
                    Celula.codigo == codigo,
                    Celula.nombre == nombre,
                    Celula.codigo_equipos == codigo_equipos,
                ),
            )
        ).scalar_one_or_none()
        if existe:
            flash(
                f"Otra célula con ese código, nombre o código de búsqueda de equipos "
                f"ya pertenece a "
                f"{existe.unidad_gestion.nombre}",
                "error",
            )
        else:
            celula.codigo = codigo
            celula.nombre = nombre
            celula.codigo_equipos = codigo_equipos
            celula.unidad_gestion = unidad
            db.session.commit()
            flash("Célula actualizada", "ok")
        return redirect(url_for("gestion_unidades"))

    @app.post("/gestion/celulas/<int:celula_id>/alternar")
    def gestion_celula_alternar(celula_id):
        celula = db.get_or_404(Celula, celula_id)
        celula.activo = not celula.activo
        db.session.commit()
        return redirect(url_for("gestion_unidades"))

    @app.post("/gestion/celulas/<int:celula_id>/eliminar")
    def gestion_celula_eliminar(celula_id):
        celula = db.get_or_404(Celula, celula_id)
        nombre = celula.nombre
        db.session.delete(celula)
        db.session.commit()
        flash(f"Célula {nombre} eliminada", "ok")
        return redirect(url_for("gestion_unidades"))

    @app.route("/gestion/configuracion/parametros", methods=["GET", "POST"])
    def gestion_parametros():
        if request.method == "POST":
            prefijo = str(
                request.form.get("PREFIJO_DECLARACION", "")
            ).strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{1,10}", prefijo):
                flash(
                    "El prefijo debe tener entre 1 y 10 letras o números",
                    "error",
                )
                return redirect(url_for("gestion_parametros"))
            try:
                digitos = int(request.form.get("DIGITOS_DECLARACION", ""))
            except (TypeError, ValueError):
                digitos = 0
            if not 3 <= digitos <= 12:
                flash(
                    "La numeración debe tener entre 3 y 12 dígitos",
                    "error",
                )
                return redirect(url_for("gestion_parametros"))
            for clave in CONFIGURACIONES_INICIALES:
                fila = db.session.execute(
                    db.select(Configuracion).where(Configuracion.clave == clave)
                ).scalar_one()
                valor = str(request.form.get(clave, "")).strip()
                fila.valor = valor.upper() if clave == "PREFIJO_DECLARACION" else valor
            db.session.commit()
            flash("Configuración actualizada", "ok")
            return redirect(url_for("gestion_parametros"))
        filas_configuracion = {
            fila.clave: fila
            for fila in db.session.execute(db.select(Configuracion)).scalars()
        }
        configuraciones = [
            filas_configuracion[clave]
            for clave in CONFIGURACIONES_INICIALES
            if clave in filas_configuracion
        ]
        return render_template(
            "gestion_parametros.html",
            configuraciones=configuraciones,
            config_por_clave=filas_configuracion,
        )

    @app.route("/gestion/piezas-control-logistica", methods=["GET", "POST"])
    def gestion_piezas_control_logistica():
        if request.method == "POST":
            codigo = requerido(request.form.get("codigo"), "el código de pieza")
            codigo = codigo.upper()
            try:
                coincidencias = buscar_piezas(codigo)
            except Exception:
                app.logger.exception("No se pudo validar la pieza para Logística")
                flash("No se pudo validar el código. Intentá nuevamente.", "error")
                return redirect(url_for("gestion_piezas_control_logistica"))
            pieza = next(
                (
                    x for x in coincidencias
                    if str(x.get("codigo", "")).strip().upper() == codigo
                ),
                None,
            )
            if not pieza:
                flash("No se encontró el código de pieza", "error")
            else:
                existente = db.session.execute(
                db.select(PiezaControlLogistica).where(
                    PiezaControlLogistica.codigo == codigo
                )
                ).scalar_one_or_none()
                descripcion = str(pieza.get("descripcion") or "").strip() or None
                if existente:
                    existente.descripcion = descripcion or existente.descripcion
                    if existente.activo:
                        flash("Esa pieza ya estaba activa en el control", "warning")
                    else:
                        existente.activo = True
                        flash("Pieza reactivada para el control de Logística", "ok")
                else:
                    db.session.add(PiezaControlLogistica(
                        codigo=codigo,
                        descripcion=descripcion,
                    ))
                    flash("Pieza agregada al control de Logística", "ok")
                db.session.commit()
            return redirect(url_for("gestion_piezas_control_logistica"))
        piezas = db.session.execute(
            db.select(PiezaControlLogistica)
            .order_by(PiezaControlLogistica.codigo)
        ).scalars().all()
        respuesta = make_response(render_template(
            "gestion_piezas_logistica.html",
            piezas=piezas,
            activas=sum(1 for pieza in piezas if pieza.activo),
            inactivas=sum(1 for pieza in piezas if not pieza.activo),
            base_demostracion=(
                "demo_material_no_conforme" in str(app.config["SQLALCHEMY_DATABASE_URI"])
            ),
        ))
        respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    @app.post("/gestion/piezas-control-logistica/<int:pieza_id>/alternar")
    def gestion_pieza_control_logistica_alternar(pieza_id):
        pieza = db.get_or_404(PiezaControlLogistica, pieza_id)
        pieza.activo = not pieza.activo
        db.session.commit()
        return redirect(url_for("gestion_piezas_control_logistica"))

    @app.post("/gestion/piezas-control-logistica/<int:pieza_id>/eliminar")
    def gestion_pieza_control_logistica_eliminar(pieza_id):
        pieza = db.get_or_404(PiezaControlLogistica, pieza_id)
        db.session.delete(pieza)
        db.session.commit()
        flash("Pieza eliminada de la configuración", "ok")
        return redirect(url_for("gestion_piezas_control_logistica"))

    @app.route("/gestion/motivos", methods=["GET", "POST"])
    def gestion_motivos():
        if request.method == "POST":
            codigo = requerido(request.form.get("codigo"), "el código")
            nombre = requerido(request.form.get("nombre"), "el nombre")
            if db.session.execute(
                db.select(GrupoMotivo).where(GrupoMotivo.codigo == codigo)
            ).scalar_one_or_none():
                flash("Ya existe un grupo con ese código", "error")
            else:
                orden = db.session.execute(
                    db.select(db.func.max(GrupoMotivo.orden))
                ).scalar() or 0
                grupo = GrupoMotivo(codigo=codigo, nombre=nombre, orden=orden + 1)
                db.session.add(grupo)
                db.session.flush()
                db.session.add(
                    Motivo(
                        codigo=codigo,
                        nombre="Sin especificar",
                        tipo_accion="NINGUNA",
                        grupo=grupo,
                    )
                )
                db.session.commit()
                flash("Grupo agregado", "ok")
            return redirect(url_for("gestion_motivos"))
        grupos = db.session.execute(
            db.select(GrupoMotivo)
            .options(selectinload(GrupoMotivo.motivos))
            .order_by(GrupoMotivo.orden, GrupoMotivo.nombre)
        ).scalars().all()
        return render_template(
            "gestion_motivos.html",
            grupos=grupos,
            tipos_accion=TIPOS_ACCION_MOTIVO,
        )

    @app.post("/gestion/motivos/grupos/<int:grupo_id>/editar")
    def gestion_grupo_motivo_editar(grupo_id):
        grupo = db.get_or_404(GrupoMotivo, grupo_id)
        grupo.codigo = requerido(request.form.get("codigo"), "el código")
        grupo.nombre = requerido(request.form.get("nombre"), "el nombre")
        db.session.commit()
        flash("Grupo actualizado", "ok")
        return redirect(url_for("gestion_motivos"))

    @app.post("/gestion/motivos/grupos/<int:grupo_id>/detalle")
    def gestion_motivo_detalle_agregar(grupo_id):
        grupo = db.get_or_404(GrupoMotivo, grupo_id)
        codigo = requerido(request.form.get("codigo"), "el código")
        nombre = requerido(request.form.get("nombre"), "el motivo detallado")
        if db.session.execute(
            db.select(Motivo).where(Motivo.codigo == codigo)
        ).scalar_one_or_none():
            flash("Ya existe un motivo con ese código", "error")
        else:
            db.session.add(
                Motivo(
                    codigo=codigo,
                    nombre=nombre,
                    tipo_accion=str(request.form.get("tipo_accion", "NINGUNA")),
                    grupo=grupo,
                )
            )
            db.session.commit()
            flash("Motivo detallado agregado", "ok")
        return redirect(url_for("gestion_motivos"))

    @app.post("/gestion/motivos/<int:motivo_id>/editar")
    def gestion_motivo_editar(motivo_id):
        motivo = db.get_or_404(Motivo, motivo_id)
        motivo.codigo = requerido(request.form.get("codigo"), "el código")
        motivo.nombre = requerido(request.form.get("nombre"), "el nombre")
        motivo.tipo_accion = str(request.form.get("tipo_accion", "NINGUNA"))
        db.session.commit()
        flash("Motivo actualizado", "ok")
        return redirect(url_for("gestion_motivos"))

    @app.post("/gestion/motivos/<int:motivo_id>/accion")
    def gestion_motivo_accion(motivo_id):
        motivo = db.get_or_404(Motivo, motivo_id)
        tipo_accion = str(request.form.get("tipo_accion", "NINGUNA")).strip()
        if tipo_accion not in {x[0] for x in TIPOS_ACCION_MOTIVO}:
            abort(400)
        motivo.tipo_accion = tipo_accion
        db.session.commit()
        flash("Acción del motivo actualizada", "ok")
        return redirect(url_for("gestion_motivos"))

    @app.post("/gestion/motivos/<int:motivo_id>/alternar")
    def gestion_motivo_alternar(motivo_id):
        motivo = db.get_or_404(Motivo, motivo_id)
        motivo.activo = not motivo.activo
        db.session.commit()
        return redirect(url_for("gestion_motivos"))

    @app.route("/gestion/catalogos/<tipo>", methods=["GET", "POST"])
    def gestion_catalogo(tipo):
        tipo = tipo.upper()
        if tipo == "CELULA":
            return redirect(url_for("gestion_unidades"))
        if tipo == "EQUIPO":
            flash("Los turnos y equipos se obtienen del sistema productivo", "ok")
            return redirect(url_for("gestion_configuracion"))
        if tipo == "PROVEEDOR":
            flash("Los proveedores se validan con el padrón de proveedores", "ok")
            return redirect(url_for("gestion_configuracion"))
        titulos = {
            "LUGAR": "Lugares de detección",
        }
        if tipo not in titulos:
            abort(404)
        if request.method == "POST":
            codigo = requerido(request.form.get("codigo"), "el código")
            nombre = requerido(request.form.get("nombre"), "el nombre")
            existe = db.session.execute(
                db.select(Catalogo).where(
                    Catalogo.tipo == tipo, Catalogo.codigo == codigo
                )
            ).scalar_one_or_none()
            if existe:
                flash("Ya existe una opción con ese código", "error")
            else:
                max_orden = db.session.execute(
                    db.select(db.func.max(Catalogo.orden)).where(Catalogo.tipo == tipo)
                ).scalar() or 0
                db.session.add(
                    Catalogo(
                        tipo=tipo, codigo=codigo, nombre=nombre, orden=max_orden + 1
                    )
                )
                db.session.commit()
                flash("Opción agregada", "ok")
            return redirect(url_for("gestion_catalogo", tipo=tipo))
        opciones = db.session.execute(
            db.select(Catalogo)
            .where(Catalogo.tipo == tipo)
            .order_by(Catalogo.orden, Catalogo.nombre)
        ).scalars().all()
        return render_template(
            "gestion_catalogo.html",
            tipo=tipo,
            titulo=titulos[tipo],
            opciones=opciones,
        )

    @app.post("/gestion/catalogos/<int:catalogo_id>/alternar")
    def gestion_catalogo_alternar(catalogo_id):
        opcion = db.get_or_404(Catalogo, catalogo_id)
        opcion.activo = not opcion.activo
        db.session.commit()
        return redirect(url_for("gestion_catalogo", tipo=opcion.tipo))

    @app.get("/api/piezas")
    def api_piezas():
        q = request.args.get("q", "").strip()
        if len(q) < 2:
            return jsonify([])
        try:
            return jsonify(buscar_piezas(q))
        except Exception:
            app.logger.exception("Error buscando piezas")
            return jsonify(
                {"error": "No se pudieron buscar los códigos. Intentá nuevamente."}
            ), 500

    @app.get("/api/estructura/<path:codigo>")
    def api_estructura(codigo):
        try:
            coincidencias = buscar_piezas(codigo)
            pieza = next((p for p in coincidencias if p["codigo"] == codigo), None)
            return jsonify(
                {"pieza": pieza, "componentes": obtener_estructura(codigo)}
            )
        except Exception:
            app.logger.exception("Error consultando estructura")
            return jsonify(
                {"error": "No se pudo cargar la estructura de la pieza."}
            ), 500

    @app.get("/api/operaciones")
    def api_operaciones():
        q = request.args.get("q", "").strip()
        if len(q) < 1:
            return jsonify([])
        try:
            return jsonify(buscar_operaciones(q))
        except Exception:
            app.logger.exception("Error buscando operaciones")
            return jsonify(
                {"error": "No se pudieron buscar las operaciones."}
            ), 500

    @app.get("/api/piezas/<path:codigo>/operaciones")
    def api_operaciones_pieza(codigo):
        try:
            return jsonify(listar_operaciones_pieza(codigo))
        except Exception:
            app.logger.exception("Error consultando operaciones de %s", codigo)
            return jsonify({"error": "No se pudieron consultar las operaciones"}), 500

    @app.get("/api/hcp/validar")
    def api_validar_hcp():
        codigo = request.args.get("codigo", "").strip()
        operacion = request.args.get("operacion", "").strip()
        hcp = request.args.get("hcp", "").strip()
        tipo_material = request.args.get("tipo_material", "").strip().upper()
        if not codigo or not hcp:
            return jsonify({"valido": False, "mensaje": "Faltan código o HCP"})
        try:
            operaciones = listar_operaciones_pieza(codigo)
            if operaciones and not any(
                str(x["codigo"]).strip() == operacion for x in operaciones
            ):
                return jsonify({
                    "valido": False,
                    "mensaje": "Elegí una operación válida para esta pieza",
                })
            resultado = validar_hcp(
                codigo,
                operacion,
                hcp,
                tipo_material == "MATERIA_PRIMA",
            )
            if resultado:
                return jsonify({
                    "valido": True,
                    "mensaje": (
                        "Lote validado"
                        if tipo_material == "MATERIA_PRIMA"
                        else "HCP validado"
                    ),
                })
            return jsonify({
                "valido": False,
                "mensaje": (
                    "El lote no coincide con los datos registrados"
                    if tipo_material == "MATERIA_PRIMA"
                    else "El HCP no coincide con los datos registrados"
                ),
            })
        except Exception:
            app.logger.exception("Error validando HCP")
            return jsonify(
                {"error": "No se pudo validar el HCP o lote. Intentá nuevamente."}
            ), 500

    @app.get("/api/turnos")
    def api_turnos():
        try:
            return jsonify(listar_turnos())
        except Exception:
            app.logger.exception("Error consultando turnos")
            return jsonify({"error": "No se pudieron cargar los turnos"}), 500

    @app.get("/api/equipos")
    def api_equipos():
        codigo_celula = request.args.get("codigo_celula", "").strip()
        if not codigo_celula:
            return jsonify([])
        try:
            return jsonify(listar_equipos(codigo_celula))
        except Exception:
            app.logger.exception("Error consultando tablaequipos")
            return jsonify(
                {"error": "No se pudieron consultar los equipos de la célula"}
            ), 500

    @app.get("/api/proveedores/<path:numero>")
    def api_proveedor(numero):
        try:
            proveedor = buscar_proveedor(numero)
            if not proveedor:
                return jsonify(
                    {"valido": False, "error": "Proveedor inexistente"}
                ), 404
            return jsonify({"valido": True, **proveedor})
        except Exception:
            app.logger.exception("Error consultando controlt")
            return jsonify(
                {
                    "valido": False,
                    "error": "No se pudo validar el proveedor. Intentá nuevamente.",
                }
            ), 500

    @app.get("/api/proveedores")
    def api_proveedores():
        q = request.args.get("q", "").strip()
        if not q:
            return jsonify([])
        try:
            return jsonify(buscar_proveedores(q))
        except Exception:
            app.logger.exception("Error buscando proveedores en controlt")
            return jsonify(
                {"error": "No se pudieron buscar proveedores. Intentá nuevamente."}
            ), 500

    @app.get("/api/estado-productivo")
    def api_estado_productivo():
        modo_demo = app.config["PRODUCTIVE_DEMO_MODE"]
        return jsonify(
            {
                "modo": "demostración" if modo_demo else "sistema productivo",
                "configurado": modo_demo or bool(app.config["PRODUCTION_DATABASE_URL"]),
                "auxiliar": (
                    "demostración"
                    if app.config["AUXILIARY_DEMO_MODE"]
                    else "sistema auxiliar"
                ),
            }
        )


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
