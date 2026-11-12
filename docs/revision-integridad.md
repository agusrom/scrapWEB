# Revisión de integridad del sistema DNC

## Alcance y arquitectura comprobada

Base de la revisión: commit `3a4423032dda3fb16881aca8d5c87690b27bdaee`.
No había `AGENTS.md` ni instrucciones adicionales en los directorios padres.
Se revisaron README, instrucciones de instalación, modelos, flujo de rutas,
permisos, plantillas, recursos estáticos, conexiones externas, DDL, migrador y
pruebas. No se utilizaron supuestos de versiones anteriores.

- `app.py`: fábrica Flask, 12 modelos SQLAlchemy, permisos, rutas, estados,
  impresión y reporte/exportación. `Declaracion` conserva el número DNC;
  `DeclaracionItem` conserva cada disposición y su control de Logística;
  `RetrabajoIntervencion` registra los resultados asociados al renglón.
- `validaciones.py`: validaciones de cantidades reutilizadas por creación,
  Calidad y Administración. Las propiedades del modelo siguen calculando
  recuperadas, scrap posterior, scrap total y retrabajo pendiente.
- `productivo.py`: adaptador de consultas SELECT parametrizadas a fuentes
  externas. Los identificadores configurables se validan por separado.
- `templates/`: Jinja2 compartido para el detalle y su impresión, con bases
  separadas para Gestión y Producción/Logística. Los botones administrativos
  dependen del rol; el servidor vuelve a comprobar los permisos.
- `static/js/`: formularios, selectores y consultas periódicas; `app.css`
  conserva el diseño adaptable y las reglas de impresión.
- `estructura_mysql.sql`: estructura para ejecución explícita; el migrador
  verifica estructura y copia datos históricos, sin ejecutar DDL al arrancar.
- `tests/`: suite original y nuevas regresiones HTTP, de cantidades y de MySQL.

Se mantuvo esta organización para evitar una reorganización general que
complicase la revisión de las correcciones. Separar rutas en blueprints y
servicios de dominio es una mejora posterior razonable, sin cambiar tablas.

## Flujo y correcciones

Producción y Logística informan una alerta pendiente de Calidad. Calidad
asigna scrap directo, retrabajo y liberadas; Producción registra resultados del
retrabajo. La regla histórica del renglón determina si Logística debe validar
el scrap directo. Administración corrige y recalcula el estado. El número DNC
se conserva en todas las etapas.

| Corrección | Quién ve / modifica | Datos existentes y estados | Impresión / Excel | Migración |
| --- | --- | --- | --- | --- |
| Rechazo de negativos, valores no finitos, exceso de precisión/rango y fracciones en PZS | Roles que ya acceden a cada formulario; valida el servidor | No reescribe históricos; rechaza nuevas operaciones inconsistentes | Conserva valores válidos en ambas salidas | No |
| Alertas sin disposición anticipada y bloqueo del antiguo POST de Producción que omitía Calidad | Producción informa; Calidad decide; ADMIN mantiene su carga administrativa | Las nuevas alertas quedan pendientes de Calidad; no convierte registros antiguos | Mismo DNC | No |
| Disposición coherente con retrabajos ya procesados | Calidad y ADMIN | Impide reducir el retrabajo por debajo de recuperadas + scrap posterior; revierte toda la operación si falla un renglón | Mantiene totales sin doble contabilización | No |
| Revalidación logística al cambiar pieza, HCP, operación o scrap directo en Administración | ADMIN corrige; Logística vuelve a validar | Invalida la cantidad/fecha anterior del control y recalcula pendientes; sin scrap no genera tarea | Documento actualizado refleja el pendiente | No |
| Escrituras serializadas por DNC | Transparente para los roles autorizados | MySQL usa READ COMMITTED y bloqueo de la declaración antes de leer sus renglones para escribir; evita doble cierre simultáneo | Sin cambio visual | No |
| Sesión fija de cinco minutos y errores JSON | Todos los roles | El autorefresco no extiende la sesión; 401 JSON también sin cookie o con cuenta inactiva; 403 JSON para fetch sin permiso | No aplica | No |
| Reporte tolerante a mes inválido, textos Excel seguros y criterio de estructura explícito | Solo ADMIN | No modifica declaraciones ni estructura productiva | Excel conserva los textos como texto y documenta el criterio | No |
| Retiro de `run_demo.bat` obsoleto | Instalación | El arranque operativo sigue exigiendo MySQL; AUTH_DISABLED solo se admite en pruebas | No aplica | No |

Las validaciones frontend de cantidades usan límites, pasos y comprobación de
sumas/retrabajo procesado. El servidor repite esas reglas con Decimal y los
límites de NUMERIC(12,3); uso de estructura conserva NUMERIC(12,4). No se confía
en los campos ocultos, JavaScript ni en ocultar enlaces.

Decisiones confirmadas por el usuario:

1. Logística controla **solo scrap directo**, no el scrap generado por retrabajos.
2. La explosión de componentes usa la **estructura productiva vigente al
   consultar**. No existe una instantánea histórica de estructura por DNC;
   cambios posteriores del maestro pueden cambiar la explosión de una DNC vieja.

## Seguridad y compatibilidad de los datos

No hay migración ni cambios de nombre/tipo de tablas o columnas. No se ejecutó
ninguna operación contra bases de la instalación. Las pruebas MySQL crean y
eliminan exclusivamente bases temporales `dnc_test_*` y `erp_test_*` y un
usuario temporal de lectura. El DDL existente se aplica explícitamente en una
prueba; dos arranques operativos posteriores solo emiten consultas. Las fuentes
externas de esa prueba tienen permiso SELECT y rechazan un UPDATE de prueba.
En producción deben usarse también cuentas externas con permisos SELECT.

La ejecución normal no crea SQLite, tablas, columnas ni semillas. La rama de
`TESTING` sí prepara bases aisladas para las pruebas. No usarla como despliegue.
Los registros antiguos no se corrigen masivamente: una inconsistencia debe ser
revisada antes de guardar nuevas cantidades. Los estados de flujos antiguos sin
fecha de Calidad se conservan durante una edición administrativa.

## Validación reproducible

Python 3.12, dependencias de `requirements.txt` y pytest 9.0.2:

```sh
python -m venv .venv
# Linux/macOS:
.venv/bin/python -m pip install -r requirements.txt pytest==9.0.2
.venv/bin/python -m pytest -q
# PowerShell: usar .\.venv\Scripts\python.exe en lugar de .venv/bin/python
```

Sin servidor MySQL las pruebas que lo requieren quedan explícitamente omitidas.
Para ejecutarlas, usar un servidor **desechable** dedicado a pruebas, con un
usuario autorizado a crear/eliminar bases y usuarios temporales. La URL de
`SCRAPWEB_MYSQL_TEST_SERVER` no debe incluir nombre de base. No usar una conexión
operativa. Ejemplo local sin credenciales reales:

```sh
docker run -d --name scrapweb-mysql-test -e MYSQL_ALLOW_EMPTY_PASSWORD=yes -e MYSQL_ROOT_HOST=% -p 127.0.0.1:3307:3306 mysql:8.4
# Esperar a que mysqladmin ping indique que está listo:
docker exec scrapweb-mysql-test mysqladmin ping --silent
SCRAPWEB_MYSQL_TEST_SERVER='mysql+pymysql://root@127.0.0.1:3307' .venv/bin/python -m pytest -q
# Al terminar, eliminar exclusivamente el contenedor de pruebas:
docker rm -f scrapweb-mysql-test
```

En PowerShell, establecer `$env:SCRAPWEB_MYSQL_TEST_SERVER` antes de pytest.
La suite comprueba permisos por rol y acceso por URL, alertas inválidas,
atomicidad con varios renglones, edición administrativa, resultados históricos,
impresión, Excel, reinicio operativo y cierre concurrente en MySQL.

El fallo previo quedó demostrado antes de editar: **24 aprobadas, 1 fallida**,
porque una prueba exigía la ausencia del lanzador `run_demo.bat` que estaba
versionado. Se eliminó el lanzador incompatible; no se debilitó la prueba.

## Límites y próximos trabajos recomendados

Esta revisión y sus pruebas no garantizan ausencia de todo defecto ni sustituyen
una validación con copias anonimizadas del volumen y versiones MySQL reales.

- No hay historial inmutable de cambios administrativos: para auditoría futura
  conviene una tabla de eventos con actor, fecha y valores anteriores/nuevos.
  Requiere acordar retención y preparar una migración explícita.
- La eliminación administrativa ya existente elimina el documento y sus hijos.
  No se cambió esa función en esta entrega. Para análisis longitudinal conviene
  acordar anulación con motivo y trazabilidad en lugar de borrado definitivo.
- Los motivos/descripciones y las estructuras externas pueden cambiar con el
  tiempo. Una analítica histórica reproducible requiere definir qué datos se
  congelan y a partir de qué momento; no se inventaron datos históricos.
- Se conserva la suma visible de cantidades de componentes; al analizar unidades
  distintas debe agruparse por unidad, como hace el resumen por componente.
- La aplicación conserva formularios sin protección CSRF explícita y claves
  iniciales conocidas. Antes de exponerla a Internet se recomienda incorporar
  CSRF, exigir secreto de sesión propio, cambiar claves iniciales y definir
  despliegue WSGI/TLS, copias y recuperación. Es un trabajo separado de seguridad.
- El reporte materializa los registros del período y consulta las estructuras.
  Conviene medir con volumen real antes de agregar paginación, índices de fecha
  o agregaciones persistidas mediante una migración.
- El adaptador corta ciclos/profundidad de estructura. Un reporte de errores de
  maestro ayudaría a evitar interpretar esas ramas como hojas reales.

## Resultado de esta entrega

- Suite completa con MySQL 8.4.13: **90 aprobadas, 0 fallidas, 0 omitidas**.
- Compilación de los 9 archivos Python del proyecto: correcta.
- Sintaxis de los 15 archivos JavaScript: correcta.
- Carga de las 38 plantillas Jinja2: correcta.
- Chromium: comprobados los controles de cantidades en Administración y Calidad,
  apertura del renglón inválido y reporte con viewport móvil; sin errores JS.
- Diff revisado sin bases, credenciales, archivos temporales ni cachés añadidos.
