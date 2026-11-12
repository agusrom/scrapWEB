# Usuario de consulta y análisis de scrap

## Uso y permisos

Administración puede crear la cuenta desde **Configuración → Usuarios y accesos
→ Crear usuario de consulta**, con nombre de usuario, nombre visible y contraseña
confirmada. El rol es siempre `CONSULTA`; no se acepta otro rol enviado por el
formulario. No hay contraseña predeterminada ni alta automática al arrancar.
Las contraseñas se guardan mediante el mismo hash del sistema.

El usuario ingresa directamente a `/analisis`. Puede consultar el historial y
el detalle de las DNC, imprimir y exportar a Excel, y consultar el reporte por
componentes existente. Administración también puede utilizar el panel.
Producción, Calidad y Logística conservan sus permisos anteriores y no acceden
a esta analítica administrativa.

El control del servidor usa una lista de endpoints de lectura para `CONSULTA`,
con métodos GET/HEAD. Bloquea alta, edición, eliminación, configuración,
validaciones y APIs operativas incluso por URL directa o solicitudes manipuladas.
El cierre de sesión está permitido. La interfaz tampoco presenta esas acciones.

## Fuente productiva

Se usa la misma conexión `PRODUCTION_DATABASE_URL` y el mismo `ERP_SCHEMA` que
la estructura productiva. Los valores predeterminados son:

| Variable configurable | Valor |
| --- | --- |
| `PRODUCCION_TABLE` | `produc04` |
| `PRODUCCION_FECHA_COL` | `FPRO_` |
| `PRODUCCION_CANTIDAD_COL` | `CANT_` |
| `PRODUCCION_OPERACION_COL` | `NPRO_` |
| `PRODUCCION_PIEZA_COL` | `GCOD_` |

`FPRO_` debe ser DATE/DATETIME/TIMESTAMP y `CANT_` una cantidad numérica de
**piezas buenas**, como indicó el usuario. La consulta agrupa por fecha, código y
operación. El rango es `fecha >= desde AND fecha < día posterior a hasta`, de
modo que se incluye todo el último día aunque contenga horas. Se conserva el
calendario de la sesión MySQL y no se reinterpretan cadenas de fecha.

El adaptador solo ejecuta SELECT con parámetros. Los identificadores
configurables pasan por la validación de nombres ya existente. La cuenta externa
necesita SELECT sobre la tabla; no se conceden ni se utilizan permisos de
escritura. No se modifican índices o tablas externas. La nueva fuente se consulta
al pedir el análisis y no se convierte en una condición adicional para arrancar
los módulos operativos ya existentes.

## Cálculo y criterios

`% scrap = scrap / (buenas + scrap) × 100`

- Se compara por **código de pieza + operación**, equiparando `010`, `10` y
  variantes con ceros iniciales o espacios. Las operaciones no numéricas se
  conservan como códigos de texto.
- Se suman buenas de la misma combinación durante el rango, nunca las buenas
  de todas las operaciones como si fueran piezas únicas. No se publica una tasa
  global que mezcle etapas productivas.
- Scrap es directo más scrap final de retrabajos, sin sumar nuevamente el
  material recibido por Logística ni las cantidades enviadas a retrabajo.
- Los componentes que tienen producción propia se comparan por su propio
  código. No se usan cantidades teóricas explotadas desde una pieza padre como
  si fueran descartes realmente declarados de cada componente.
- Las unidades se filtran por separado. Solo PZS se compara con producción;
  no se mezclan piezas, kilos u otras unidades en un total o porcentaje.
- Sin operación, sin registros productivos, con cantidades productivas nulas o
  negativas, o sin unidades para comparar, la tasa queda **Sin datos**. Un registro
  explícito de cero buenas y scrap positivo puede dar 100%; ausencia de registros
  no se convierte en una producción de cero.
- Si la fuente falla, el scrap interno sigue visible con un aviso; buenas y
  porcentajes quedan sin datos. El Excel conserva ese aviso y las celdas de tasa
  vacías. El modo demo no inventa producción.
- Los filtros por causa, célula, equipo, turno, cliente, proveedor o estado no
  tienen un denominador equivalente en la fuente informada. Se muestra el scrap
  filtrado, sin buenas ni tasas supuestamente desglosadas por esos atributos.
  Para habilitar la comparación se usan solo fecha de evento, unidad PZS, scrap
  directo + retrabajo, y opcionalmente código y operación.

### Fechas y alcance histórico

Por defecto se filtra el scrap directo por la **última fecha de validación** y
el scrap de retrabajo por la fecha de su intervención. Los documentos antiguos
con disposición pero sin fecha de validación conservan la fecha de la DNC como
referencia. Una alerta pendiente de Calidad no constituye scrap.

También se puede analizar por fecha de emisión de la DNC. Ese modo reúne los
resultados de las DNC emitidas en el rango, aunque se hayan registrado después;
por ese motivo no muestra una tasa contra producción del mismo período.

La tasa por eventos es una comparación de movimientos del período, no una tasa
por lote de fabricación: las piezas descartadas pueden haberse producido antes.
El scrap de un retrabajo se vincula con la operación original del renglón, no con
el texto libre que describe el trabajo efectuado.

No existe un registro inmutable de decisiones: una revalidación o corrección
administrativa puede cambiar fechas, causas o cantidades de un informe anterior.
El panel lo explicita; no reconstruye un histórico que la base no contiene.

Se incluyen ensayos de Calidad en el scrap total. **No se clasifican todos los
descartes de Calidad como fallas del proceso ni se excluyen ensayos automáticamente.**
Para separar consistentemente consumo planificado y defectos hace falta acordar
una clasificación explícita de causas; no se inventó esa categoría para los datos
históricos.

## Información del panel y exportación

- Scrap directo, posterior a retrabajo y total, y cantidad de DNC con scrap.
- Buenas y tasa por pieza y operación, con los criterios anteriores.
- Pareto de causas, tendencia diaria y detalle con enlace al DNC.
- Desglose separado de célula/equipo/turno de detección y responsabilidad
  atribuida; las conclusiones confirmadas, probables y pendientes no se mezclan.
- Recuperadas y horas-hombre de las intervenciones del período. La recuperación
  es recuperadas / (recuperadas + scrap final) sobre los resultados registrados,
  no sobre todo lo enviado a retrabajo. No se muestra esa tasa con un filtro
  parcial de causa u origen del scrap.
- Pendientes actuales de retrabajo y controles logísticos de DNC emitidas en el
  período; no es una reconstrucción del inventario pendiente al día de corte.
- El filtro de origen selecciona el scrap; las métricas de trabajos y pendientes
  conservan su alcance indicado en pantalla.

La pantalla pagina la comparación de 100 en 100, presenta hasta diez entradas en
los desgloses y 100 movimientos detallados. El Excel contiene **todos** los
resultados filtrados, indicadores, detección, responsabilidad, causas, tendencia,
detalle y criterios. Pantalla y exportación usan el mismo constructor de datos.
Los textos se escriben como texto en Excel para evitar que se interpreten como
fórmulas. Los filtros y los valores vacíos se conservan de forma explícita.

## Compatibilidad y validación

No hay migración de estructura: `usuarios.rol` ya admite `CONSULTA`. El alta es
una operación administrativa explícita sobre esa tabla. No se alteran DNC
existentes ni sus estados, cálculos, impresión o exportaciones anteriores.
El arranque sigue sin crear estructura, SQLite o datos de ejemplo en operación.

Archivos principales: `analisis.py`, `productivo.py`, `app.py`, las plantillas
`analisis.html` y `analisis_error.html`, navegación, historial y gestión de
usuarios; `static/js/analisis.js` y estilos adaptables del panel.

Para ejecutar todas las pruebas, incluidas las de MySQL real, seguir
[las instrucciones del servidor desechable](revision-integridad.md#validación-reproducible).
La suite nueva está en `tests/test_analisis.py` y cubre fórmula, fechas, piezas y
operaciones, unidades, pendientes, causas, permisos, creación de cuentas,
persistencia, errores de fuente y Excel. Las pruebas de fuente usan bases
sintéticas desechables con una cuenta SELECT y verifican que un UPDATE se rechace.
No se probó la conexión a la base productiva real de la instalación: este entorno
no tiene sus credenciales configuradas.

En volúmenes grandes conviene medir los planes de consulta y los índices de las
fechas de declaración, validación e intervención. No se agregaron índices sin
medir ni se alteraron índices de la fuente externa. La paginación limita lo
mostrado; los resultados del intervalo se construyen completos para el análisis
y el Excel, por lo que un período muy amplio puede requerir más memoria y tiempo.

Resultado de validación: **223 pruebas aprobadas, 0 fallidas y 0 omitidas** con
MySQL 8.4 desechable. Se verificaron los 12 archivos Python, los 16 JavaScript
y las 40 plantillas Jinja2. Chromium comprobó creación de cuenta por
Administración, ingreso con rol de consulta, rango histórico y orden de fechas,
el ejemplo de 97 buenas + 3 scrap = 3%, exportación, detalle DNC, bloqueo por URL
y diseño móvil sin desborde horizontal.
