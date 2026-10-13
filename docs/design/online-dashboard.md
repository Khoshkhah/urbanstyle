# The dashboard online

Status: proposed, 2026-10-13. To be agreed before coding.

## Goal

A link on the documentation site opens the dashboard of the pilot area, West Broadway × Granville Street. A visitor uses Find,
Filter and Ask in the browser, with no install and no server.

## What is different from `urbanstyle serve`

GitHub Pages serves only static files. `urbanstyle serve` answers the panel from Python and DuckDB (`/api/meta`, `search`, `tree`,
`query`, `focus`, `ask`). Online, the browser does this work itself:

| `serve` | Online |
|---|---|
| `meta`, `tree` | made once at publish time, as JSON files |
| `focus` of each space and block | made once at publish time, as one JSON file |
| `search`, `query` (Filter) | SQL in the browser with DuckDB-WASM, on Parquet files of the panel's layers |
| `ask` | Gemini, called from the browser; its SQL tool runs on DuckDB-WASM, read-only |
| Street View | a second Google Maps key, restricted to `https://khoshkhah.github.io/*`, from the GitHub secret `GOOGLE_MAPS_DEMO_KEY`; with no key, Street View is off |

The geometry goes into the Parquet files as GeoJSON text, with each row's length and area, so DuckDB-WASM does not need its
spatial extension. The panel (`explore.html`) stays one file. It calls one function, `api(path, body)`, that goes to the server
or, when the page has no server, to the browser's own code.

## The Gemini key

A key in a public page is visible to every visitor. Google can also revoke a key that it finds in a public GitHub repository.
The rules:

1. The key never goes in the repository. The Pages workflow puts it into the page from a GitHub secret, `GEMINI_DEMO_KEY`.
2. The key belongs to a separate Google Cloud project with no billing account. Only the free tier is possible, so it costs no money.
   When its daily requests are used, Ask says so and asks for the visitor's own key.
3. In the Google Cloud console the key is restricted to the HTTP referrer `https://khoshkhah.github.io/*` and to the Generative
   Language API.
4. Ask has a field for the visitor's own key. The browser keeps it in `localStorage` only.

Kaveh makes the project and the key, and adds the secret to the repository.

## The base map

The base map is CARTO's Voyager. CARTO's tiles need an API key: with no key, every tile comes back stamped "API KEY REQUIRED". The
local page takes the key from `CARTO_API_KEY` (roadstyle's `get_api_key`) and writes it into the page. Online:

- a CARTO key for the online page, from the GitHub secret `CARTO_DEMO_KEY`, restricted to `https://khoshkhah.github.io/*` if CARTO
  allows a restriction;
- with no key, roadstyle's keyless base map `esri_street` (Esri World Street Map) instead.

## What is published, and what is not

- The space tables, buildings, street objects and the bridge model: from OpenStreetMap (ODbL), the City of Vancouver's open data
  and LiDAR. The page names them and their licenses.
- Not Mapillary's detections or photos: they are CC BY-SA and stay local (`docs/design/mapillary.md`). The online page is built
  without them.
- Not the local Google Maps key: it allows `localhost:8784` only.

## Where the files live

The page is about 9 MB and the Parquet files about 10-20 MB. If they go into the repository, every update adds that size to its
history. Instead, a new command, `urbanstyle publish DB OUT_DIR`, writes them, and they go up as the assets of a GitHub release,
`demo-data`. The Pages workflow downloads them into `site/demo/`. The documentation links to
`https://khoshkhah.github.io/urbanstyle/demo/`.
