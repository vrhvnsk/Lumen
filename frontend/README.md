# Frontend

A small website with no build step and no dependencies: `index.html`, `styles.css`, `app.js`.

The FastAPI backend serves this folder at `/`, so starting the backend is enough (see the main README). The page talks to the API with relative URLs such as `/api/search`.

- **Describe it / Pick a mood:** the two search modes.
- **Hide obscure films:** a toggle that sends the `min_*` filters (ratings and vote counts if `/api/health` says the dataset has them, otherwise the best-known 40 %).
- **Fine-tune:** sliders for popularity and for title matching (with a "Decide automatically" checkbox). Changes re-run the last search.
- **Title matches:** a card shows "Title match" instead of a similarity percentage when the film's name matched the query.
- **Order switch:** Best match, Balanced or Popular first. It sends a `popularity` value (0, 0.35 or 0.7) with every search and re-runs the last search when changed.
- **Result cards:** click one to open the detail dialog with the plot, cast and a web of similar movies (19, 33 or 61 films depending on the Few / More / Most switch).
- **The web:** a small force-directed layout computed in the browser (`layoutGraph` in `app.js`). Similar films sit closer together, hovering a dot highlights its links, and clicking it moves to that movie. "See the list" gives the same web as text for keyboard and screen-reader users.
- All text from the API is inserted with `textContent`, never as HTML.
- System fonts only, so the page makes no requests to font providers. Posters are loaded from TMDB's image server.

To work on the frontend from another address (for example a dev server on port 5173), set `CORS_ORIGINS` for the backend and change the `fetch` URLs in `app.js` to the backend address.
