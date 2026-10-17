# Pick List Desktop

Pick List Desktop lee PDFs locales, procesa los resultados en memoria y permite exportar las listas Bodega y Local como PDF. La aplicación no inicia FastAPI, no requiere cuenta ni conexión a Internet durante su uso. Los nuevos paquetes macOS incorporan el runtime de Python y las dependencias detectadas por PyInstaller; el procedimiento Nuitka anterior se conserva como referencia.

## Requisitos de desarrollo y compilación

- macOS o Windows en la misma plataforma y arquitectura que se desea compilar.
- Git y Bash. En Windows, ejecutar los comandos desde Git Bash.
- uv **0.12.5** y CPython **3.12.13**. El workflow instala estas versiones.
- Conexión a Internet durante la primera instalación de dependencias; la aplicación empaquetada funciona offline.

Las dependencias de aplicación, Desktop y pruebas están fijadas por `backend/uv.lock`. PyInstaller y su herramienta de build se fijan aparte en `scripts/pyinstaller/requirements-macos.txt`, para que el empaquetador quede fuera de las dependencias de ejecución. Las compilaciones deben usar `--locked`; no actualizar el lock durante una compilación.

## Instalar dependencias y ejecutar localmente

Desde `backend/`:

```sh
uv sync --locked --no-default-groups --extra desktop --group test --python 3.12.13
uv run --locked --no-sync --extra desktop --python 3.12.13 pick-list
```

Para ejecutar las pruebas:

```sh
QT_QPA_PLATFORM=offscreen uv run --locked --no-sync --python 3.12.13 python -m pytest -q
```

El workflow PyInstaller instala el grupo `test` además de la extra `desktop`. Después instala el toolchain fijado en `scripts/pyinstaller/requirements-macos.txt` dentro del entorno independiente del runner.

Los datos permanecen en memoria mientras la aplicación está abierta. Los PDFs exportados permanecen en la ruta elegida por el usuario.

## Compilar un paquete standalone

El script `scripts/build-desktop.sh` conserva el procedimiento Nuitka anterior como referencia. Los nuevos paquetes macOS usan `scripts/build-pyinstaller-macos.sh` y `scripts/pyinstaller/PickList.spec`, con un runner nativo por arquitectura:

```sh
# macOS Apple Silicon arm64
uv sync --project backend --locked --no-default-groups --extra desktop --group test --python 3.12.13
uv pip install --python backend/.venv/bin/python --no-deps --requirements scripts/pyinstaller/requirements-macos.txt
./scripts/build-pyinstaller-macos.sh arm64

# macOS Intel x86_64 (ejecutar en un runner o Mac Intel)
./scripts/build-pyinstaller-macos.sh x86_64
```

El script rechaza compilaciones cruzadas, comprueba Python 3.12.13, PyInstaller 6.22.3, PySide6 6.12.0 y PyMuPDF 1.28.2, y escribe cada ejecución en un directorio único bajo `dist/macos/pyinstaller/<arquitectura>/`. Genera un bundle `Pick List.app` onedir/windowed y un ZIP mediante `ditto -c -k --keepParent`; no reemplaza los resultados de ejecuciones anteriores. El verificador comprueba arquitectura Mach-O, estructura e identificador del bundle, enlaces simbólicos, plugin Cocoa de Qt, bibliotecas MuPDF, firma ad hoc y preservación de permisos/enlaces en el ZIP.

GitHub Actions define jobs independientes en `macos-15` (arm64) y `macos-15-intel` (x86_64). Cada runner crea un entorno limpio, ejecuta la suite offscreen y publica `Pick-List-macOS-arm64.zip` o `Pick-List-macOS-x86_64.zip`. El workflow se inicia manualmente y no compila con Nuitka. Un artefacto Intel de CI acredita el build, pero no sustituye una prueba de ejecución en un Mac Intel real.

La configuración funcional de PyInstaller se basó en el bundle probado `dist/diagnostics/pyinstaller-desktop/attempt-03/`; el `.spec` versionado evita las rutas absolutas locales e incorpora un identificador estable `com.picklist.desktop`.

El flujo Nuitka existente puede seguir ejecutándose como referencia:

```sh
./scripts/build-desktop.sh
```

El script sincroniza con `uv sync --locked`, usa CPython 3.12.13 y Nuitka standalone, activa el plugin de PySide6 e incluye datos de PyMuPDF, fitz, pdfplumber, pdfminer y ReportLab. Los plugins Qt se recopilan mediante el plugin de PySide6.

- macOS: cada ejecución guarda el bundle `.app`, archivos standalone, `build.log` y el directorio de trabajo aislado bajo `dist/macos/nuitka-low-memory/build-<fecha-pid>/`. Los informes automáticos de fallo quedan en el directorio `work/` de esa ejecución, sin sobrescribir informes previos.
- Windows: `dist/windows/` contiene el ejecutable sin consola y los archivos standalone necesarios. Distribuir la carpeta completa; no copiar el `.exe` de forma aislada.

La caché compartida de Nuitka usa `dist/.nuitka-cache` por defecto. Puede elegirse otra ruta con `NUITKA_CACHE_DIR`; el script normaliza la ruta, comprueba que se pueda escribir y verifica también el directorio de caché de módulos antes de sincronizar o compilar.

No se deben compartir builds entre sistemas operativos o arquitecturas. No se ejecutan compilaciones cruzadas. El workflow previo de GitHub Actions permanece en `.github/workflows/desktop-build.yml` como referencia de Nuitka/Windows; el workflow nuevo de PyInstaller no lo invoca.

## CI y artefactos

`.github/workflows/desktop-pyinstaller-macos.yml` instala uv 0.12.5 y Python 3.12.13 para cada arquitectura, sincroniza dependencias bloqueadas, instala PyInstaller y sus dependencias exactas, ejecuta la suite offscreen y compila/publica un ZIP por runner. `.github/workflows/desktop-build.yml` es el workflow anterior, conservado como referencia.

El artefacto CI es una compilación standalone con firma ad hoc; no es una firma Developer ID ni un instalador final. La compilación PyInstaller de macOS todavía debe validarse en los dos runners; el build de Windows requiere ejecutarse en su runner nativo antes de afirmar compatibilidad.

## Validación antes de distribuir

Para cada artefacto:

1. Descargar y descomprimir el artefacto en una máquina limpia de la plataforma correspondiente.
2. Desconectar la red y abrir la aplicación sin instalar Python ni dependencias.
3. Procesar un PDF de texto, un documento con OCR requerido y un PDF inválido; revisar los errores y que no haya datos parciales.
4. Buscar y filtrar productos; comparar las métricas y los resultados con la referencia de la aplicación.
5. Exportar Bodega y Local; abrir los PDFs generados y comprobar su contenido.
6. Probar minimización, cierre durante procesamiento y controles de teclado en macOS y Windows.

El indicador «Requiere OCR» identifica documentos sin texto seleccionable; el procesamiento actual no ejecuta OCR ni incluye Tesseract. Esa capacidad no forma parte de esta configuración de distribución.

## Compilación, instalación, firma y notarización

La **compilación** genera el bundle/carpeta standalone descrito arriba. En macOS, PyInstaller aplica firma ad hoc para la integridad local del bundle; la **firma Developer ID** requiere certificados del propietario y se configura aparte. La **instalación** todavía no se automatiza: no se generan DMG, PKG ni MSI en esta etapa. La **notarización de macOS** requiere credenciales de Apple Developer y tampoco se ejecuta aquí. Hasta completar firma/notarización, macOS puede mostrar advertencias al abrir la aplicación; Windows puede mostrar avisos de SmartScreen.

## Archivos locales y Git

Versionar `backend/uv.lock`, `backend/pyproject.toml`, `scripts/build-desktop.sh`, `.github/workflows/desktop-build.yml` y esta documentación. Mantener fuera de Git los entornos `.venv`, la caché `backend/.uv-cache`, los productos de compilación `dist/` y los archivos locales de `output/`. Las reglas de ignore no eliminan ni mueven esos archivos.
