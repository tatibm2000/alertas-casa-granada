# Monitor de viviendas · provincia de Granada → grupo de Telegram

Revisa cada 15 minutos 17 webs de inmobiliarias de Granada y avisa en un **grupo de Telegram** cuando aparece una vivienda en venta con **3 o más habitaciones por 220.000 € o menos**.

Además:

- **Regla de rescate.** Si una inmobiliaria no tiene nada en ese precio, avisa una vez de su anuncio más reciente con 3+ habitaciones, marcado como "fuera de precio".
- **Bajadas de precio.** Avisa si un piso ya avisado baja de precio, o si uno que estaba por encima baja y entra en el rango.
- **Duplicados.** Detecta el mismo piso publicado por varias agencias y manda solo un aviso corto.
- **Avisos de fallo.** Te avisa si una web deja de funcionar, lo que suele significar que la han cambiado.
- **Resumen diario.** A las 9:00 manda un mensaje de "sigo vivo".
- **Horas de silencio.** De 00:00 a 08:00 los mensajes llegan sin sonido.

Todo corre gratis en una máquina virtual **Oracle Cloud Always Free**, con una base de datos **SQLite** (un archivo en la propia máquina).

---

## Índice

1. [Crear el bot de Telegram](#1-crear-el-bot-de-telegram)
2. [Crear el grupo y meter al bot](#2-crear-el-grupo-y-meter-al-bot)
3. [Crear la cuenta de Oracle Cloud](#3-crear-la-cuenta-de-oracle-cloud)
4. [Crear la máquina virtual](#4-crear-la-máquina-virtual)
5. [Conectarte a la máquina por SSH](#5-conectarte-a-la-máquina-por-ssh)
6. [Subir el proyecto](#6-subir-el-proyecto)
7. [Instalar](#7-instalar)
8. [Configurar Telegram y probar](#8-configurar-telegram-y-probar)
9. [Dejarlo funcionando 24/7](#9-dejarlo-funcionando-247)
10. [Copias de seguridad](#10-copias-de-seguridad)
11. [Uso del día a día](#11-uso-del-día-a-día)
12. [Mantenimiento y problemas](#12-mantenimiento-y-problemas)
13. [Cómo está hecho](#13-cómo-está-hecho)

---

## 1. Crear el bot de Telegram

1. En Telegram, busca **@BotFather** (tiene la marca azul de verificado) y pulsa **Iniciar**.
2. Escribe `/newbot`.
3. Te pide un **nombre visible**, por ejemplo `Pisos Granada`.
4. Te pide un **usuario**, que debe acabar en `bot` y no estar cogido, por ejemplo `pisos_granada_tati_bot`.
5. BotFather te responde con el **token**, algo como `7123456789:AAH...xyz`. Guárdalo: es la contraseña del bot y no se comparte.

Opcional, también con BotFather:
- `/setuserpic` para ponerle una foto.
- `/setdescription` para añadirle una descripción.

## 2. Crear el grupo y meter al bot

1. En Telegram: **Nuevo grupo**. Añade a las personas que van a recibir los avisos.
2. Añade también al bot: busca su usuario (`@pisos_granada_tati_bot`) y agrégalo como miembro.
3. Opcional pero recomendable: en los ajustes del grupo, haz al bot **administrador**. No le hace falta ningún permiso especial; solo evita algunos límites en grupos grandes.
4. Escribe en el grupo este mensaje (cambiando el usuario por el de tu bot):
   ```
   /start@pisos_granada_tati_bot
   ```
   Sirve para que el bot "vea" el grupo y podamos sacar su identificador en el paso 8.

> **Si cambias el tipo de grupo,** el identificador del grupo cambia. Pasa, por ejemplo, al hacerlo público o al activar ciertas opciones, que lo convierten en "supergrupo". Si deja de llegar todo, mira el paso 8: el log del servicio te dirá el id nuevo.

## 3. Crear la cuenta de Oracle Cloud

1. Ve a <https://www.oracle.com/cloud/free/> y pulsa **Start for free**.
2. Rellena tus datos.
3. **Región de origen (Home Region).** Elige **Spain Central (Madrid)** o la más cercana que te deje. No se puede cambiar después. Si al crear la máquina te da error de capacidad, también funcionan Frankfurt, París o Marsella.
4. Te pide una tarjeta solo para verificar que eres una persona. Con recursos *Always Free* no se cobra nada. No actives el plan de pago (*Upgrade to Pay As You Go*) si no quieres.
5. Espera el correo de "cuenta lista", que puede tardar unos minutos, y entra en la consola.

## 4. Crear la máquina virtual

En la consola de Oracle: menú ☰ → **Compute** → **Instances** → **Create instance**.

| Campo | Qué poner |
|---|---|
| Name | `granada-monitor` |
| Image | **Change image** → **Canonical Ubuntu** → **24.04** (la versión *aarch64*) |
| Shape | **Change shape** → **Ampere** → **VM.Standard.A1.Flex** → **1 OCPU** y **6 GB** de memoria (aparece la etiqueta *Always Free-eligible*) |
| Networking | Deja lo que viene por defecto (crea una red nueva con IP pública) |
| Add SSH keys | **Generate a key pair for me** → pulsa **Save private key** y guarda el archivo `.key` en un sitio seguro |
| Boot volume | Por defecto (50 GB) |

Pulsa **Create**. En 1–2 minutos estará en verde (**Running**). Copia la **Public IP address**.

- **Si sale *Out of capacity*:** es habitual con las máquinas ARM gratuitas. Prueba otro *Availability Domain* en la misma pantalla o inténtalo un rato después.
- **Plan B:** usa la forma **VM.Standard.E2.1.Micro** (x86, 1 GB, siempre disponible). Funciona todo menos Deymar y KW Kinver, que necesitan navegador y no caben en 1 GB. Ponles `enabled: false` en `config.yaml`.

No hace falta abrir ningún puerto: el monitor solo hace peticiones hacia fuera.

## 5. Conectarte a la máquina por SSH

**Mac / Linux** (Terminal):
```bash
chmod 600 ~/Descargas/ssh-key-*.key
ssh -i ~/Descargas/ssh-key-*.key ubuntu@IP_PUBLICA
```

**Windows** (PowerShell):
```powershell
icacls "$HOME\Downloads\ssh-key.key" /inheritance:r /grant:r "$($env:USERNAME):(R)"
ssh -i "$HOME\Downloads\ssh-key.key" ubuntu@IP_PUBLICA
```

La primera vez pregunta si confías en la máquina: responde `yes`. Ya estás dentro, con el usuario `ubuntu`.

## 6. Subir el proyecto

Desde **tu ordenador**, en otra terminal y en la carpeta donde tengas `granada-monitor.zip`:

```bash
scp -i RUTA/A/ssh-key.key granada-monitor.zip ubuntu@IP_PUBLICA:~
```

Y en la **máquina virtual**:

```bash
sudo apt-get update && sudo apt-get install -y unzip
unzip granada-monitor.zip
cd granada-monitor
```

> Si prefieres tenerlo en GitHub: súbelo a un repo privado y en la VM haz `git clone`. Así cada cambio que hagas se instala con un `git pull`.

## 7. Instalar

En la máquina virtual, dentro de `~/granada-monitor`:

```bash
bash deploy/install.sh
```

El script hace lo siguiente (tarda unos 5 minutos):
- instala Python, SQLite y las librerías;
- instala Chromium para las dos webs que lo necesitan;
- pone la zona horaria de Madrid;
- crea el archivo `.env`;
- registra el servicio `granada-monitor`.

## 8. Configurar Telegram y probar

**8.1. Pega el token en `.env`:**

```bash
nano .env
```
```
TELEGRAM_BOT_TOKEN=7123456789:AAH...xyz
TELEGRAM_CHAT_ID=
```
Guarda con `Ctrl+O`, `Enter` y sal con `Ctrl+X`.

**8.2. Saca el id del grupo.** Asegúrate de haber escrito `/start@tu_bot` en el grupo (paso 2.4) y ejecuta:

```bash
.venv/bin/python -m monitor chat-id
```

Verás algo como:
```
-1002345678901	supergroup: Pisos Granada
```
o bien `-4567890123	group: Pisos Granada`. Copia el **número negativo** del grupo a `TELEGRAM_CHAT_ID` en `.env`.

Si no aparece nada, vuelve a escribir `/start@tu_bot` en el grupo y repite el comando.

**8.3. Mensaje de prueba:**
```bash
.venv/bin/python -m monitor telegram-test
```
Os tiene que llegar a todos un "👋 Hola…" en el grupo.

**8.4. Prueba las webs**, sin guardar ni enviar nada:
```bash
.venv/bin/python -m monitor check
```
Para cada inmobiliaria se listan los anuncios que entiende:
- `✅` cumple precio y habitaciones;
- `·3hab` tiene 3+ habitaciones pero está fuera de precio.

Para probar solo una web: `--source tecnocasa`.

**8.5. Ciclo en seco** (opcional). Simula una vuelta completa e imprime los mensajes en pantalla en vez de mandarlos:
```bash
.venv/bin/python -m monitor once --dry-run
```

## 9. Dejarlo funcionando 24/7

```bash
sudo systemctl enable --now granada-monitor
```

Con esto arranca ya y se vuelve a arrancar solo si la máquina se reinicia o el programa falla.

- **Primera vuelta.** Registra todos los anuncios actuales **sin avisar uno a uno**, para no inundar el grupo, y manda un único mensaje "✅ Fuentes inicializadas".
- **A partir de ahí,** solo avisa de lo nuevo.
- **Si queréis ver lo que ya cumple hoy,** ejecuta: `.venv/bin/python -m monitor resumen`.

Comandos útiles:

```bash
sudo systemctl status granada-monitor          # ¿está vivo?
journalctl -u granada-monitor -f               # ver el log en directo (Ctrl+C para salir)
journalctl -u granada-monitor --since "1 hour ago"
sudo systemctl restart granada-monitor         # tras cambiar config.yaml o .env
sudo systemctl stop granada-monitor            # pararlo
```

## 10. Copias de seguridad

La base de datos es el archivo `data/monitor.sqlite`. Para hacer una copia comprimida cada día a las 4:30 y guardar las 14 últimas:

```bash
crontab -e
```
Añade esta línea al final (si te pregunta el editor, elige `nano`):
```
30 4 * * * /home/ubuntu/granada-monitor/deploy/backup.sh >> /home/ubuntu/granada-monitor/backups/backup.log 2>&1
```

Para traerte una copia a tu ordenador:
```bash
scp -i RUTA/A/ssh-key.key "ubuntu@IP_PUBLICA:~/granada-monitor/backups/*.gz" .
```

## 11. Uso del día a día

### Mensajes que llegan al grupo

| Mensaje | Cuándo |
|---|---|
| 🏠 **NUEVO** | Vivienda nueva ≤ 220.000 € con 3+ hab. Lleva foto, precio, habitaciones, m², municipio y enlace. |
| 🏠 **NUEVO** + "📉 Ha bajado de…" | Un piso que estaba por encima del precio baja y entra en el rango. |
| 📉 **BAJADA DE PRECIO** | Un piso ya avisado baja de precio. |
| ℹ️ *"X no tiene nada ≤ 220.000 €"* | Regla de rescate: el anuncio más reciente con 3+ hab de esa inmobiliaria. Se manda una vez por anuncio. |
| 🔁 *"también lo anuncia…"* | El mismo piso ya avisado aparece en otra agencia. |
| ⚠️ / ✅ | Una web falla 3 veces seguidas / vuelve a funcionar. |
| 🟢 **Monitor activo** | Resumen diario a las 9:00. |

### Cambiar los criterios

Edita `config.yaml` (`nano config.yaml`) y reinicia el servicio:

```yaml
criteria:
  max_price: 220000
  min_rooms: 3
  fallback: true
interval_minutes: 15
quiet_hours: [0, 8]
heartbeat_hour: 9
```

Para desactivar una inmobiliaria, añade `enabled: false` en su bloque.

### Comandos

```bash
cd ~/granada-monitor
.venv/bin/python -m monitor resumen                 # manda al grupo todo lo que cumple ahora mismo
.venv/bin/python -m monitor estado                  # estado de cada web (último OK, nº anuncios, fallos)
.venv/bin/python -m monitor check --source deymar   # probar una web concreta
```

### Consultar la base de datos

```bash
sqlite3 -header -column data/monitor.sqlite \
  "SELECT source, price, rooms, municipality, url FROM listings
   WHERE active=1 AND is_sale=1 AND rooms>=3 AND price<=220000 ORDER BY price;"
```

Si la quieres ver con una interfaz web, sin abrir puertos, tienes dos opciones:
- **Datasette por túnel SSH.**
  1. En la VM: `.venv/bin/pip install datasette`.
  2. En la VM: `.venv/bin/datasette data/monitor.sqlite -p 8001`.
  3. En tu ordenador: `ssh -i clave.key -L 8001:localhost:8001 ubuntu@IP`.
  4. Abre <http://localhost:8001>.
- **Copiar el archivo y abrirlo en local:** `scp` del archivo y lo abres con *DB Browser for SQLite*.

## 12. Mantenimiento y problemas

**Una web cambia su diseño.** Llega un ⚠️ al grupo. Comprueba qué está leyendo:
```bash
.venv/bin/python -m monitor check --source NOMBRE -v
```
Si devuelve 0 o un error, hay que retocar su conector en `monitor/sources/`. Cada web tiene su propio conector y el resto sigue funcionando mientras tanto.

**Actualizar el sistema** cada cierto tiempo:
```bash
sudo apt-get update && sudo apt-get upgrade -y && sudo reboot
```

**Oracle y las máquinas inactivas.** Oracle puede reclamar instancias *Always Free* que considera infrautilizadas. El monitor trabaja cada 15 minutos, así que no debería pasar. Aun así, si un día no llega el 🟢 diario, entra en la consola y comprueba que la máquina sigue en *Running*.

| Problema | Solución |
|---|---|
| `telegram-test` dice error | Revisa el token, que el bot esté en el grupo y que `TELEGRAM_CHAT_ID` sea el número negativo. |
| `chat-id` no muestra el grupo | Escribe `/start@tu_bot` en el grupo y repite. Si el bot se añadió hace mucho, sácalo y vuelve a meterlo. |
| Dejan de llegar mensajes tras tocar el grupo | El grupo pasó a supergrupo. Mira `journalctl -u granada-monitor` y busca "supergrupo": ahí sale el id nuevo. Ponlo en `.env` y reinicia. |
| Deymar / KW Kinver no funcionan | `.venv/bin/playwright install --with-deps chromium`. En la máquina de 1 GB, desactívalas. |
| Llegan demasiados avisos de rescate | Pon `fallback: false` en `config.yaml`. |
| Quieres empezar de cero | `sudo systemctl stop granada-monitor && rm data/monitor.sqlite && sudo systemctl start granada-monitor`. Vuelve a registrar todo en silencio. |

## 13. Cómo está hecho

```
granada-monitor/
├── config.yaml              ← criterios, frecuencia y las 17 webs
├── .env                     ← token y chat id (no se comparte)
├── monitor/
│   ├── __main__.py          ← comandos (run, once, check, resumen, estado...)
│   ├── runner.py            ← ciclo: leer webs → guardar → decidir avisos → Telegram
│   ├── rules.py             ← qué es vivienda válida, filtro de precio/hab, huella anti-duplicados
│   ├── store.py             ← SQLite (anuncios, avisos enviados, estado de cada web)
│   ├── telegram.py          ← envío al grupo (con límites de Telegram)
│   ├── messages.py          ← formato de los mensajes
│   ├── municipios.py        ← municipios de Granada (para webs que mezclan provincias)
│   └── sources/             ← un conector por tipo de web
│       ├── inmovilla.py     ← Inmofuturo, Invivus, JyM, InmoAire, Neo Patrimonial
│       ├── apis.py          ← Plancasa, Ventaria, Grupo Torres, Comprarcasa (APIs JSON)
│       ├── simple_html.py   ← Inmo Arrayán, Remax Cima, InmoZafiro, Tecnocasa, DonPiso, Inmobiliaria 3.0
│       └── browser_sites.py ← Deymar y KW Kinver (Chromium sin interfaz)
├── deploy/                  ← instalación, servicio systemd y backups
└── tests/                   ← pruebas con HTML/JSON real de las webs
```

| Web | Cómo se lee |
|---|---|
| Inmofuturo, Invivus, JyM, InmoAire | Inmovilla: `/venta/?orden=5` (más recientes), ficha si falta el dato |
| Neo Patrimonial | Inmovilla dentro de un iframe (agencia 9329); se filtran los de Madrid |
| Grupo Torres | API JSON `/buscador/api/propiedades` |
| Comprarcasa Portal Home | API JSON `api.comprarcasa.com` |
| Plancasa | API REST de WordPress |
| Ventaria | API REST propia de WordPress |
| Inmo Arrayán | HTML de `buscarInmuebles` |
| Remax Cima | HTML de `buscador-de-inmuebles/venta/todos/granada/` |
| Tecnocasa | HTML paginado; listado completo cada ~2 h |
| DonPiso | HTML de `venta-casas-y-pisos/granada/listado` |
| Inmobiliaria 3.0 | HTML de `/quiero-comprar/` |
| InmoZafiro | HTML (microsite de pisos.com), ficha para las habitaciones |
| Deymar | Chromium (los anuncios se cargan por JavaScript) |
| KW Kinver | Chromium para el listado + ficha HTML para las habitaciones |

**Cómo se decide un aviso.**

1. Un anuncio "cumple" si se cumplen todas estas condiciones:
   - está en venta;
   - es vivienda, no garaje, local, solar ni terreno;
   - está en la provincia de Granada;
   - tiene 3+ habitaciones;
   - cuesta ≤ 220.000 €.
2. Es "nuevo" si su `(web, id)` no estaba en la base de datos.
3. La regla de rescate mira, por cada web y en cada ciclo, si hay alguno que cumpla. Si no hay ninguno, coge el más reciente con 3+ hab (por fecha o, si la web no la da, por id) y avisa una sola vez.

**Pruebas:**
```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

**Uso responsable.** El monitor consulta cada web como mucho cada 15 minutos (las de navegador, cada 30), con pausas entre peticiones y sin descargar imágenes. Es tráfico de una persona navegando, para uso personal.

---

## Alternativa gratuita: GitHub Actions (repositorio público)

Sin servidor: GitHub ejecuta `python -m monitor once` cada 15 minutos
(`.github/workflows/monitor.yml`) y guarda la base de datos en la caché de Actions.

1. Crea un repositorio **público** vacío en GitHub y sube el proyecto
   (`.env`, `data/` y el entorno virtual quedan fuera gracias a `.gitignore`).
2. En el repo: **Settings → Secrets and variables → Actions → New repository secret**:
   `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.
3. Pestaña **Actions** → workflow **monitor** → **Run workflow** para la primera ejecución
   (siembra en silencio y manda "Fuentes inicializadas").
4. A partir de ahí se ejecuta solo. Para lanzar a mano otro comando (resumen, ejemplo,
   estado, telegram-test) usa **Run workflow** y escríbelo en "comando".

Notas: GitHub puede retrasar las ejecuciones programadas unos minutos; si un repo público
pasa 60 días sin cambios desactiva la programación (el workflow hace un commit vacío a los 45
días para evitarlo). Si la caché se pierde, el monitor vuelve a sembrar sin reenviar todo.