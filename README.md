# header-capture

En liten Docker-baserad testapplikation som simulerar en mottagande Bifrost-server.
Den tar emot HTTP-anrop på `/capture`, sparar dem persistent i SQLite under `/data`
och visar de senaste anropen på en enkel webbsida.

## Endpoints

| Endpoint            | Metoder                                         | Beskrivning                                     |
|---------------------|-------------------------------------------------|-------------------------------------------------|
| `/capture`          | GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD    | Sparar anropet. Även `/capture/<valfri/sökväg>` |
| `/`                 | GET                                             | Webbsida med senaste 100 anropen, senaste först |
| `/clear`            | POST                                            | Rensar all historik                             |
| `/api/requests`     | GET                                             | Samma data som JSON (`?limit=N`, max 1000)      |
| `/health`           | GET                                             | Hälsokontroll                                   |

För varje anrop sparas: timestamp (UTC), metod, path, query parameters, samtliga headers,
body (upp till 1 MiB, därefter trunkerad), body-storlek och remote IP
(inkl. `X-Forwarded-For` om den finns). `/capture` svarar `200` med JSON
(`{"status":"captured","id":..,"timestamp":..}`), och `OPTIONS` svarar `204` med `Allow`/CORS-headers.

## Starta

```bash
docker compose up -d --build
open http://localhost:8000/
```

## Testa

```bash
curl -X POST http://localhost:8000/capture \
  -H "Content-Type: application/json" \
  -H "X-Custom-Header: custom-value" \
  -H "X-Bifrost-Test: hello" \
  -d '{"message":"test från lokal docker"}'
```

Rensa historiken:

```bash
curl -X POST http://localhost:8000/clear
```

Hela testflödet (bygg, start, anrop, kontroll av webbsida, omstart, persistens) körs med:

```bash
bash test.sh
```

## Data och persistens

Datan ligger i `/data/requests.db` i containern, som är monterad på den namngivna
volymen `header_capture_data`. Den överlever `docker compose restart` och
`docker compose down`, men tas bort med `docker compose down -v`.

## Konfiguration (miljövariabler)

| Variabel         | Standard   | Beskrivning                       |
|------------------|------------|-----------------------------------|
| `DATA_DIR`       | `/data`    | Var SQLite-filen sparas           |
| `MAX_DISPLAY`    | `100`      | Antal anrop som visas på `/`      |
| `MAX_BODY_BYTES` | `1048576`  | Max antal bytes body som sparas   |

## Köra utan Docker

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data gunicorn -b 0.0.0.0:8000 app:app
```

> Endast för lokal utveckling/test. Applikationen saknar autentisering och sparar
> alla headers i klartext, inklusive eventuella `Authorization`-tokens.
