# LLM Scout v1.1

Agente de escritorio: detecta qué tarea estás haciendo mirando la ventana en
foco y sugiere los 3 mejores LLMs para esa tarea, según benchmarks. Mide
**adopción real** cruzando las sugerencias con los pedidos que registran tus
gateways locales (ModelMatch Desktop / FreeLLMAPI). Y de yapa: noticias de IA
que aparecen de vez en cuando y panel con transparencia ajustable.

## Cómo correr

Doble clic en **`Iniciar LLMScout.bat`** (panel siempre-arriba, abajo a la
derecha, sin consola; si ya hay una instancia, no duplica). Para que arranque
solo con Windows: **`Instalar autoinicio.bat`** (y `Quitar autoinicio.bat`
para sacarlo).

```powershell
python scout.py            # panel
python scout.py --scan     # qué detecta ahora mismo (5 muestras)
python scout.py --top coding   # top 3 para una categoría
python scout.py --stats    # adopción real + manual
```

Sin dependencias: Python estándar + tkinter + SQLite.

## Cómo funciona

1. **Detector** (`detector.py`): cada 3 s lee la ventana en foco (Win32) y la
   clasifica por proceso y título en 7 categorías. Si te equivoca, el botón
   "⋯" de cada tarjeta reasigna la categoría de esa app y lo recuerda
   (`data/overrides.json`). Si no hay input hace 5 minutos o la PC está
   bloqueada, deja de contar sugerencias: el denominador de la métrica no se
   infla solo.

2. **Benchmarks** (`benchmarks.py`): snapshot local 0-100 por dimensión +
   precios y contexto **en vivo desde OpenRouter** (público, cache 24 h).
   Si definís `ARTIFICIAL_ANALYSIS_API_KEY` suma el índice de inteligencia
   en vivo. Cada categoría pondera distinto: en código manda coding 55%,
   en escritura writing 75%; el precio es desempate, no criterio.

3. **Panel** (`scout.py`): top 3 con motivo, botones **"✓ Usé este"**
   (adopción manual), **"Abrir ↗"** (chat web del modelo: claude.ai,
   chatgpt.com, chat.z.ai, kimi.com…) y **Copiar**. Checkbox "Solo
   FreeLLMAPI" filtra a los modelos del gateway 3001 y marca "● local".
   Recuerda posición, "siempre arriba" y **transparencia** (menú clic derecho →
   Transparencia, 100–60 %, default 88 %); una sola instancia a la vez.

4. **Adopción real** (`gateway.py`): cada ~60 s lee los pedidos nuevos de
   **ModelMatch Desktop** (`Escritorio\ModelMatch\datos\modelmatch.db`, la
   tabla `requests`, lectura de solo lectura con watermark). Si dentro de
   60 minutos de la sugerencia hubo un pedido resuelto (status 200) a ese
   modelo o su familia → adopción real, contada una sola vez por pedido.
   Esa es la métrica de éxito de v1; el botón manual es el fallback cuando
   el pedido sale por otro lado.

5. **Noticias de IA** (`noticias.py`): una franja fina que aparece **de vez
   en cuando**, no siempre — cada ~12 min entra con un titular, rota cada
   45 s durante ~2,5 min y se esconde sola (✕ la cierra antes; el mouse
   encima pospone). Fuentes RSS/Atom sin dependencias: Google News ES,
   TechCrunch y The Verge (máx. 3 por fuente, filtro de promos). Cache de
   30 min, refresco en background. Menú: "Ver noticias ahora" y checkbox
   para apagar. Clic en el titular → abre la nota.

## Archivos

| Archivo | Qué es |
|---|---|
| `data/scout.db` | impresiones, usos manuales, adopciones reales |
| `data/benchmarks.json` | snapshot de calidad (fecha y fuente adentro) |
| `data/cache_precios.json` | precios OpenRouter (24 h) |
| `data/noticias.json` | cache del feed de noticias (30 min) |
| `data/overrides.json` | correcciones del detector |
| `data/ui.json` | posición, siempre-arriba, transparencia, ruta de la DB de ModelMatch |
| `data/scout.log` | errores (nada muere mudo) |
| `medir_recursos.py` | mide RAM/CPU del panel en ejecución |

## Consumo de recursos (medido)

21/09/2026, panel v1.1 en ejecución (noticias + transparencia activas),
medido con `python medir_recursos.py` sobre el proceso `pythonw`:

```
RAM working set :   63.4 MB  (0.4 % de 16 GB)
RAM privada     :   42.2 MB  (costo real)
CPU acumulada   :    1.8 s en ~20 min de uso (~0.2 % promedio)
```

Letra chica: el working set incluye DLLs compartidas de Python/Tkinter que
otros procesos también mapean; la memoria privada (42 MB) es el costo real de
tener el panel abierto — menos que una pestaña de Chrome. La franja de
noticias no se nota: son 12 títulos en memoria y un temporizador, sin
imágenes ni webviews.

## Datos del snapshot

19/09/2026, base [Artificial Analysis](https://artificialanalysis.ai/models)
(Intelligence Index v4.3) y SWE-bench de [Vellum](https://www.vellum.ai) e
[Iternal](https://iternal.ai). Puntajes por dimensión aproximados; lo fresco
(precios/contexto) se baja solo de OpenRouter.

## Fuera de alcance (v2+)

Leer contenido de pantalla, integración con IDE, notificaciones push, o
mover el ruteo al panel: LLM Scout sugiere, ModelMatch ejecuta y mide.
