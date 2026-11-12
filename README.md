# Material no conforme · V48 MySQL

Aplicación Flask + Jinja2 para informar material no conforme, validar la causa
en Calidad y gestionar scrap, retrabajos y resultados parciales.

## Arquitectura MySQL

La aplicación usa tres conexiones MySQL separadas:

- `DATABASE_URL`: base propia del sistema, con declaraciones, usuarios,
  configuración, motivos, retrabajos y validaciones de Logística.
- `PRODUCTION_DATABASE_URL`: MySQL productivo, usado solamente para consultas.
- `AUXILIARY_DATABASE_URL`: base que contiene turnos y equipos; puede reutilizar
  la conexión productiva.

La aplicación operativa no crea bases, tablas ni columnas al arrancar. Solamente
verifica la conexión, las tablas y las columnas requeridas. La estructura se
entrega por separado en `estructura_mysql.sql` para que la aplique un
administrador con permisos. `migrar_a_mysql.bat` tampoco crea estructura: sólo
la verifica y copia registros. Las tablas productivas y auxiliares siguen
siendo de sólo lectura.

## Funciones incluidas

- Administración dispone de un reporte de scrap explotado hasta el último
  componente de la estructura. Permite filtrar por período, cliente, pieza,
  componente, célula, equipo, motivo, estado, proveedor, DNC y origen del
  scrap, y exporta un Excel con resumen consolidado y detalle trazable.
- Producción genera una alerta sin decidir el destino del material.
- Calidad valida cada renglón y divide la cantidad entre scrap, retrabajo y
  material liberado.
- La revisión de Calidad presenta cada pieza como una ficha con código,
  descripción, cantidad, HCP y estado de completitud.
- Calidad ve la operación y el HCP como datos de sólo lectura. El servidor los
  vuelve a validar, pero no acepta modificaciones desde el formulario.
- Cada renglón tiene un comentario propio y visible, independiente de la
  observación general del vale.
- Producción puede registrar una observación específica en cada renglón. La
  observación se conserva y se muestra durante la validación de Calidad y en
  el detalle imprimible.
- La carga de piezas usa una grilla compacta: operación, HCP, cantidad, grupo
  y causa comparten la primera línea; el material afectado y la observación
  comparten la segunda cuando ambos corresponden.
- El último paso presenta un resumen operativo completo antes de guardar:
  totales, códigos diferentes, modalidad de responsabilidad, fecha, turno,
  unidad de gestión, célula, equipo y legajo.
- El resumen final muestra cada renglón con pieza, operación, HCP o lote,
  cantidad, grupo y causa, elemento afectado, responsable y observación.
- Calidad dispone de acciones masivas y atajos por renglón para casos de
  scrap total, retrabajo total o liberación total.
- La disposición del material y la investigación de responsabilidad son
  procesos separados: Calidad puede resolver el material y dejar la
  atribución pendiente sin bloquear la operación.
- Se distingue el origen sugerido por Producción de la responsabilidad
  confirmada por Calidad. La conclusión puede ser confirmada, probable,
  pendiente o no atribuible.
- La bandeja de Calidad separa las nuevas alertas de las investigaciones de
  responsabilidad pendientes.
- Configuración jerárquica de unidades de gestión y células. Una célula sólo
  puede pertenecer a una unidad y su código y nombre son únicos.
- Cada célula tiene un código interno y otro código independiente para buscar
  en `tablaequipos.CELULA`.
- Las células pueden eliminarse definitivamente. Las unidades de gestión
  pueden eliminarse cuando ya no contienen células.
- Producción completa los datos en orden: fecha, turno, célula y equipo.
  Célula queda bloqueada hasta seleccionar turno, y equipo hasta seleccionar
  célula.
- Turnos consultados desde `turnos` (`id`, `turno`) y equipos desde
  `tablaequipos` (`EQPO`, `DESC`, `CELULA`) en una base MySQL auxiliar.
- El equipo elegido se valida nuevamente en el servidor para impedir guardar
  un número que no corresponda a la célula.
- Bandeja de alertas pendientes en `/calidad`.
- La bandeja de Calidad consulta nuevas alertas cada 5 segundos sin recargar la
  página completa. Se pausa cuando la pestaña no está visible y se actualiza
  inmediatamente al volver.
- Las alertas recién recibidas se resaltan y el título de la pestaña muestra
  cuántas quedan por decidir.
- Categorías de defectos con causas detalladas editables y agrupadas.
- Producción selecciona primero el grupo y luego una causa filtrada dentro de
  ese grupo. Los selectores y botones siguientes permanecen deshabilitados
  hasta completar su dependencia.
- Cada renglón consulta sus operaciones en `produc21`. Si el código tiene
  operaciones, se obliga a elegir una; si no tiene, se muestra “No aplica”.
- El HCP se valida en `controlo` combinando `GCOD_`, `OPER_` y `NHCP_`. Para
  materia prima, el identificador ingresado se valida contra `LOTE_`.
- Las operaciones se conservan como aparecen en `produc21` (`010`, `020`,
  `030`), pero al consultar `controlo` se comparan numéricamente contra sus
  equivalentes (`10`, `20`, `30`).
- El HCP permanece bloqueado hasta elegir la operación. Si el código no tiene
  operaciones, se muestra “No aplica” y el HCP se habilita directamente.
- Calidad no puede alterar la operación ni el HCP informados por Producción.
- Calidad ve inicialmente el grupo y la causa como un resumen de sólo lectura
  con la leyenda “Informado por Producción”. El botón “Modificar motivo”
  despliega los buscadores completos únicamente cuando necesita corregirlos.
- La edición del motivo puede aplicarse o cancelarse. Al abrirla, el buscador de
  grupos muestra todas las alternativas en lugar de quedar filtrado por el dato
  informado anteriormente.
- La pantalla de Calidad presenta cada renglón como un panel compacto y cerrado.
  La cabecera resume pieza, motivo, operación, HCP, cantidad, destino y estado;
  el comentario, la corrección, las cantidades y la responsabilidad aparecen al
  desplegar el detalle.
- Las alertas nuevas comienzan con toda la cantidad asignada a scrap. Calidad
  puede cambiarla a retrabajo, liberación o división de cantidades.
- Si se intenta guardar con un renglón incompleto, ese panel se abre
  automáticamente para mostrar los campos pendientes.
- Todo renglón exige una indicación propia de Calidad, cualquiera sea el
  destino. Debe justificar el scrap, indicar el retrabajo necesario o explicar
  por qué se libera. La regla se controla en pantalla y nuevamente en el
  servidor.
- La indicación de Calidad permanece visible en la tarjeta resumida. En el
  flujo habitual no es necesario desplegar el renglón; el detalle se abre
  únicamente para modificar motivo, destino o responsabilidad.
- Los controles del detalle de Calidad usan una presentación más compacta:
  menor altura, botones e inputs reducidos y comentario en una sola franja.
- Interfaz basada en el mismo patrón del Sistema de Inventarios: sidebar
  angosta, topbar, módulos y portada de configuración por secciones.
- Scrap directo, retrabajo o declaración mixta.
- Pieza terminada, subconjunto, componente, materia prima, consignado u otro.
- La misma pieza puede cargarse en varios renglones con causas diferentes.
- Los motivos pueden configurarse para pedir un componente o una materia prima
  de la estructura. La materia prima se obtiene de `produc01.MATE_` para cada
  componente encontrado en `produc10`.
- Al cargar una pieza hija de la estructura, el selector de MP contempla tanto
  el `MATE_` de la propia pieza como el de sus componentes descendientes.
- La MP siempre se confirma desde una lista visible, aun cuando exista una sola
  alternativa, para que Producción pueda comprobar qué material está imputando.
- La carga de Producción está dividida en cuatro pasos claros: detección,
  piezas y causas, responsabilidad, y revisión.
- Después de agregar todas las piezas, Producción elige si el vale tendrá un
  responsable común o una asignación independiente por renglón.
- Cambiar entre responsable común e individual no elimina las asignaciones
  que ya se habían cargado pieza por pieza.
- La tecla Enter selecciona la opción activa y mueve el foco al próximo campo
  habilitado del paso actual; nunca avanza de paso automáticamente.
- Búsqueda en `produc01`.
- Estructura multinivel desde `produc10`.
- La estructura aparece completamente marcada. Si se conserva completa, se
  agrega un solo renglón para la pieza o subconjunto principal.
- Si se desmarca una parte, se omite el conjunto principal y se agregan
  únicamente las ramas que continúan seleccionadas.
- Búsqueda de operaciones desde `produc21`.
- Diferencia entre sector/célula que detecta y origen imputado.
- Imputación confirmada, presunta o no determinada.
- HCP obligatorio con cantidad de dígitos configurable.
- Cantidades separadas entre scrap directo y retrabajo.
- Seguimiento de retrabajo con resultados parciales.
- Piezas recuperadas y piezas que terminan en scrap.
- Tiempo, cantidad de personas y horas-hombre.
- Codificación configurable con prefijo y cantidad de dígitos. El formato
  inicial es `DNC-000001` y el correlativo continúa de manera incremental.
- Tabla configurable de piezas que requieren validación de scrap por
  Logística. La regla se toma al momento de la decisión de Calidad y queda
  guardada en el renglón como dato histórico.
- Logística recibe únicamente los renglones configurados que tengan scrap,
  confirma la cantidad física y registra su legajo. Si la cantidad difiere de
  la definida por Calidad, debe justificar la diferencia.
- La configuración administrativa informa por separado piezas activas e
  inactivas, evita respuestas cacheadas y reactiva un código existente cuando
  se lo vuelve a agregar. En modo de prueba advierte que la configuración no es
  la misma que la de la instalación productiva.
- Logística tiene una consulta de sólo lectura con todos los códigos activos.
  Su bandeja diferencia explícitamente la lista configurada de las tareas
  pendientes: una tarea se crea recién cuando Calidad asigna scrap a ese código.
- La bandeja de Logística se actualiza automáticamente sin interrumpir un
  formulario que se esté completando.
- Producción, Calidad y Logística tienen un historial propio desde el cual
  pueden consultar y reimprimir cualquier declaración.
- El DNC impreso funciona como un documento vivo: conserva siempre el mismo
  número e identifica si es el aviso inicial, la validación de Calidad o la
  validación parcial/completa de Logística.
- Al guardar una validación de Calidad o Logística se abre automáticamente una
  nueva ventana con la versión actualizada lista para imprimir. Si el navegador
  bloquea la ventana, se muestra un enlace directo para abrirla.
- El vale utiliza A4 vertical y presenta cada pieza en una ficha amplia. El
  código y la cantidad quedan destacados, y debajo se separan operación/HCP,
  problema, decisión de Calidad y responsabilidad/Logística. Al haber muchos
  renglones, las fichas continúan completas en hojas adicionales.
- Dentro de cada ficha, código de pieza, cantidad, operación, HCP y estado usan
  una jerarquía tipográfica reforzada para poder identificarlos de un vistazo.
- Las fichas reducen espacios internos y altura mínima, pero aumentan el tamaño
  de subtítulos y textos secundarios. Los renglones con información extensa se
  expanden sólo cuando es necesario.
- Administración puede editar declaraciones ya generadas desde el historial o
  desde su detalle. Se pueden corregir cabecera, pieza/HCP, motivo, cantidades,
  origen, responsabilidad y control de Logística; el número DNC permanece fijo
  y el estado se recalcula al guardar.
- Administración también puede eliminar una declaración completa escribiendo
  su número como confirmación. La eliminación incluye renglones e intervenciones
  de retrabajo asociadas y no está disponible para los demás roles.
- Formulario realmente diferente para scrap y retrabajo.
- Origen común aplicable a todas las piezas.
- Ítems compactos que se expanden sólo para editar.
- Opción de registrar el tiempo y resultado del retrabajo en la misma declaración
  cuando el trabajo ya fue realizado.
- Vista guiada y simplificada para Producción.
- Panel separado de Gestión.
- Origen externo por proveedor y número de remito.
- El número de proveedor se valida contra `controlt.NPRV_` y se muestra la
  descripción de `controlt.DPRV_`. No se puede continuar con un número
  inexistente.
- El backend repite la validación y guarda número y descripción para preservar
  el dato histórico.
- Los selectores de Producción y Calidad permiten escribir para filtrar por
  código o descripción, recorrer con flechas y confirmar con Enter.
- Todos los legajos aceptan únicamente números y un máximo de 5 dígitos. La
  restricción se aplica mientras se escribe y se valida nuevamente en el
  servidor para declarantes, Calidad, responsables y retrabajos.
- El buscador de proveedores acepta tanto `NPRV_` como texto contenido en
  `DPRV_`.
- Al buscar una pieza, Enter abre directamente la estructura del primer
  resultado.
- La cabecera de Producción ya no solicita Sector ni Lugar. El sistema guarda
  automáticamente la unidad de gestión como sector y la célula como lugar de
  detección para mantener compatibilidad histórica.
- Catálogos editables de motivos, unidades, células y lugares. Turnos, equipos
  y proveedores se sincronizan con el sistema productivo.
- En Gestión → Motivos se define si cada causa no pide datos adicionales, pide
  un componente, una materia prima de la estructura o un proceso relacionado.
- Parámetros generales editables sin modificar código.

## Direcciones

```text
http://127.0.0.1:5000/login
```

El sistema redirige automáticamente a cada sector después de ingresar:

| Usuario inicial | Contraseña inicial | Módulo |
| --- | --- | --- |
| `produccion` | `produccion` | Informes, retrabajos e historial |
| `calidad` | `calidad` | Bandeja y validaciones de Calidad |
| `logistica` | `logistica` | Validación de scrap e informes de recepción |
| `admin` | `admin` | Gestión y configuración completa |

Las claves iniciales se utilizan solamente al crear las cuentas por primera
vez. El administrador puede cambiarlas desde **Configuración → Usuarios y
contraseñas**. Los usuarios de sector no pueden acceder a los módulos de los
otros sectores aunque escriban manualmente su URL.

La sesión se cierra después de **5 minutos como máximo** desde el ingreso o al
presionar **Salir**. El plazo no se renueva por actividad ni por el
autorefresco de la pantalla de Calidad. Las cuentas identifican el sector y
los legajos de los formularios continúan identificando a la persona que
realizó cada acción.

El inicio de Producción consulta cada **15 segundos** si Calidad asignó nuevos
retrabajos y actualiza únicamente el sector de pendientes, sin recargar toda la
página ni extender la sesión.

## Migrar a MySQL

1. Cerrá la versión anterior.
2. Copiá `.env.example` como `.env` y completá las tres conexiones MySQL.
3. Pedile a un usuario autorizado que ejecute `estructura_mysql.sql` si las
   tablas todavía no existen.
4. Ejecutá `migrar_a_mysql.bat`.
5. Elegí una de las opciones:
   - **Verificar** para comprobar estructura y cantidades sin escribir.
   - **Copiar SQLite** para migrar a tablas MySQL vacías.
   - **Reemplazar** únicamente si MySQL contiene datos de prueba que deben
     borrarse antes de copiar SQLite.
6. Cuando termine, ejecutá `run.bat`.

El migrador de datos:

- no ejecuta `CREATE`, `ALTER` ni `DROP`;
- verifica las 12 tablas y todas sus columnas;
- copia declaraciones, renglones, retrabajos, usuarios y configuraciones desde
  SQLite conservando sus identificadores;
- combina automáticamente claves que SQLite distinguía pero MySQL considera
  iguales (por ejemplo, `RECEPCION` y `Recepcion`), conserva preferentemente el
  registro activo y actualiza sus referencias antes de insertar;
- no vuelve a cargar datos de ejemplo ni catálogos iniciales después de copiar;
- muestra los conteos encontrados, copiados y finalmente guardados;
- registra la versión de migración y verifica el resultado.

La copia se rechaza si la base MySQL destino ya tiene datos, para impedir
duplicaciones accidentales. `estructura_mysql.sql` contiene el DDL completo
para revisión o ejecución manual por un administrador de base de datos.

## Primera ejecución

- `run.bat` exige un archivo `.env` configurado para MySQL.
- Si falta la base, una tabla o una columna, el sistema se detiene y pide
  ejecutar el migrador. Nunca crea una base local ni corrige el esquema durante
  el arranque.
- Los modos demostración están deshabilitados en la instalación operativa.

Después de iniciar, abrí `http://127.0.0.1:5000`.

También se puede ejecutar manualmente:

```powershell
py -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python migrar_a_mysql.py --solo-verificar
# o bien:
python migrar_a_mysql.py --origen "C:\ruta\declaraciones_prueba.db"
python app.py
```

## Conectar las tablas productivas

Editá `.env`:

```env
PRODUCTIVE_DEMO_MODE=false
PRODUCTION_DATABASE_URL=mysql+pymysql://usuario:clave@servidor:3306/CGRSA?charset=utf8mb4
```

La contraseña debe codificarse como URL si contiene caracteres como `@`, `:`,
`/` o `#`.

Las columnas configuradas son:

- `produc01`: `GCOD_`, `CCOD_`, `MATE_`, `DESC_`, `STOK_`.
- `produc10`: `VCOD_`, `GCOD_`, `QXUN_`.
- `produc21`: `GCOD_`, `OPER_`, `CTITULO_`.
- `controlo`: `GCOD_`, `OPER_`, `LOTE_`, `NHCP_`.

Si algún nombre cambia en la instalación productiva puede corregirse en `.env`
sin tocar el código.

La configuración predeterminada para estas consultas es:

```env
OPERACIONES_TABLE=produc21
OPERACION_PIEZA_COL=GCOD_
OPERACION_CODIGO_COL=OPER_
OPERACION_TITULO_COL=CTITULO_

CONTROL_HCP_SCHEMA=CGRSA
CONTROL_HCP_TABLE=controlo
CONTROL_HCP_PIEZA_COL=GCOD_
CONTROL_HCP_OPERACION_COL=OPER_
CONTROL_HCP_LOTE_COL=LOTE_
CONTROL_HCP_NUMERO_COL=NHCP_
```

El maestro de proveedores usa, por defecto, la misma conexión productiva:

```env
PROVEEDORES_SCHEMA=CGRSA
PROVEEDORES_TABLE=controlt
PROVEEDOR_NUMERO_COL=NPRV_
PROVEEDOR_DESCRIPCION_COL=DPRV_
```

## Conectar turnos y equipos

La base auxiliar puede utilizar la misma conexión MySQL que las tablas
productivas o credenciales distintas:

```env
AUXILIARY_DEMO_MODE=false

# Dejar vacío para reutilizar PRODUCTION_DATABASE_URL:
AUXILIARY_DATABASE_URL=

# Nombre de la base que contiene ambas tablas:
AUXILIARY_SCHEMA=NOMBRE_BD_AUXILIAR

TURNOS_TABLE=turnos
TURNOS_ID_COL=id
TURNOS_NOMBRE_COL=turno

EQUIPOS_TABLE=tablaequipos
EQUIPOS_NUMERO_COL=EQPO
EQUIPOS_DESCRIPCION_COL=DESC
EQUIPOS_CELULA_COL=CELULA
```

El campo visible **Código de búsqueda de equipos** de cada célula debe coincidir
exactamente con el valor guardado en `tablaequipos.CELULA`. El nombre visible
puede ser distinto.

## Tablas propias del sistema

Todas se alojan en la base MySQL indicada por `DATABASE_URL`:

- `usuarios`
- `declaraciones`
- `declaracion_items`
- `unidades_gestion`
- `celulas`
- `grupos_motivo`
- `motivos`
- `catalogos`
- `configuraciones`
- `piezas_control_logistica`
- `retrabajo_intervenciones`
- `versiones_esquema`

Las pruebas automáticas continúan usando una base SQLite en memoria, aislada y
descartable. Esa ruta sólo existe bajo `TESTING` y nunca se utiliza al ejecutar
`python app.py`.

## Integridad y revisión del flujo

Las validaciones y pruebas de robustez, los permisos afectados, el criterio
histórico de los reportes y las instrucciones de prueba con MySQL están en
[docs/revision-integridad.md](docs/revision-integridad.md).
No se requieren migraciones para estas correcciones.
