# Declaración directa de scrap por Calidad

Calidad dispone de **Declarar scrap** en su navegación y en su bandeja. El
formulario reutiliza la carga de Producción: fecha, turno, equipo, legajo,
piezas, operación, HCP/lote, grupo, causa y observación por renglón.

## Comportamiento

- Solo Calidad y Administración pueden abrir y enviar `/calidad/scrap/nuevo`.
  Producción y Logística reciben 403 incluso por URL directa.
- La única célula de detección es la célula existente cuyo nombre sea
  `Calidad` (sin distinguir mayúsculas). Debe estar activa y pertenecer a una
  unidad activa. Se selecciona automáticamente después del turno; su equipo
  debe corresponder a esa célula. El servidor repite estos controles.
- El origen y la responsabilidad quedan automáticamente asignados a la propia
  célula Calidad, con el legajo declarante y el proceso `Ensayos de Calidad`.
  Es la decisión funcional confirmada para estos ensayos. No se aceptan otros
  orígenes enviados mediante campos manipulados.
- Toda la cantidad se registra como scrap directo. No se admiten cantidades
  negativas, cero, fracciones, no finitas, fuera del rango de MySQL, ni destinos
  a retrabajo o liberación. El máximo entero es 999999999.
- Cada renglón exige una observación de hasta 255 caracteres para indicar el
  ensayo o motivo (por ejemplo, corte de probeta de soldadura). Se conserva como
  observación del renglón y como indicación de Calidad.
- Las operaciones, HCP/lotes y datos adicionales exigidos por el motivo se
  validan con las mismas funciones que utiliza la carga operativa de Producción.
- Al guardar se registra la fecha de validación y el legajo de Calidad usando
  los datos del declarante. No se vuelve a enviar el documento a decidir por
  Calidad ni se abre una investigación de responsabilidad.
- Sin piezas que requieran control, la DNC queda **CERRADA**. Si al menos una
  pieza está configurada para control logístico, queda **PENDIENTE LOGISTICA**;
  solo esos renglones aparecen en la bandeja de Logística. Al completar sus
  controles se cierra la declaración.
- El guardado es transaccional: si falla un renglón no se guarda ninguno de la
  declaración nueva. Las DNC existentes mantienen su flujo y sus cantidades.

## Impresión, reportes y compatibilidad

Se conserva el mismo número DNC y se ofrece la impresión actualizada al guardar.
El documento muestra la validación de Calidad, el ensayo y el estado logístico
cuando corresponde. La nueva declaración aparece en los historiales existentes.

El scrap se incluye en el reporte y en Excel como **scrap directo**, con la
célula Calidad como origen de detección. Los reportes continúan reservados a
Administración y usando la estructura productiva vigente al consultar.

No se agregan tablas ni columnas y **no hay migración MySQL**. No se actualizan
masivamente DNC anteriores, no se crean células/equipos automáticamente y el
arranque operativo sigue sin crear estructura ni datos demo. Las fuentes
productivas y auxiliares continúan siendo de solo lectura. Si no existe una
única célula Calidad habilitada o no tiene equipos asociados, Administración
debe revisar su configuración; no se sustituye por una célula de Producción.

## Archivos y comprobaciones

- `app.py`: ruta nueva, restricción de célula, validación inmediata y derivación
  mediante la regla logística ya existente.
- `templates/produccion_nueva.html` y `static/js/produccion.js`: formulario
  compartido, célula automática, responsabilidad propia e indicación obligatoria.
- `templates/base.html` y `templates/calidad_bandeja.html`: accesos del sector.
- `tests/test_scrap_calidad.py`: flujo normal, permisos, peticiones manipuladas,
  campos inválidos, cantidades límite, múltiples renglones, Logística,
  impresión, Excel, validaciones externas y persistencia al reiniciar.

La suite nueva se ejecuta tanto con SQLite aislado como con MySQL real usando
el servidor desechable descrito en [revision-integridad.md](revision-integridad.md).
La prueba de reinicio de esta funcionalidad utiliza un archivo temporal aislado;
las pruebas operativas MySQL existentes verifican que el arranque no ejecute DDL
ni cargue semillas y que las fuentes externas rechacen escrituras.

Validación de la entrega: **149 pruebas aprobadas, 0 fallidas y 0 omitidas** con
MySQL 8.4. Se compilaron los 10 archivos Python, se verificó la sintaxis de los
15 JavaScript y se cargaron las 38 plantillas. En Chromium con viewport móvil
se recorrieron login, selección automática de célula, carga de una probeta,
guardado directo e impresión del documento cerrado, sin errores JavaScript.
