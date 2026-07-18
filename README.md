# LaunchKit

A production-shaped starter for a React + Tailwind frontend and a uv-managed FastAPI API with Auth0 authentication, MongoDB Atlas persistence, and the Gemini API.

## What is included

- React 19, TypeScript, Tailwind CSS 4, and the Auth0 React SDK
- FastAPI with generated OpenAPI docs and CORS configured for the frontend
- Auth0 bearer-token validation on protected API routes
- Async MongoDB access with the official PyMongo `AsyncMongoClient`
- Gemini text generation through the official `google-genai` SDK
- Authenticated note CRUD and a protected Gemini playground
- Backend unit/integration tests and a server-rendered frontend smoke test

## 1. Configure the services

Create local environment files:

```powershell
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
```

### Auth0

1. Create an Auth0 **Single Page Application**.
2. Add `http://localhost:3000` to Allowed Callback URLs, Allowed Logout URLs, and Allowed Web Origins.
3. Create an Auth0 **API** using `https://launchkit-api` as its Identifier and RS256 as its signing algorithm.
4. Put the SPA Domain and Client ID in the root `.env` file.
5. Put the same Domain and API Identifier in `backend/.env`.

The Auth0 domain should look like `your-tenant.us.auth0.com`; do not include `https://`.

### MongoDB Atlas

1. Create a cluster, database user, and network access rule in Atlas.
2. Choose **Connect > Drivers > Python** and copy the connection string.
3. Set `MONGODB_URI` in `backend/.env`, replacing the username and password placeholders.

The `notes` collection is created by MongoDB on the first insert.

### Gemini

Create an API key in Google AI Studio and set `GEMINI_API_KEY` in `backend/.env`. The default model is configurable through `GEMINI_MODEL`.

## 2. Install and run

From the repository root:

```powershell
npm install
uv sync --project backend
```

Start the API:

```powershell
uv run --project backend uvicorn --app-dir backend/src atlas_gemini_api.main:app --reload --port 8000
```

Start the frontend in a second terminal:

```powershell
npm run dev
```

Open `http://localhost:3000`. The FastAPI documentation is available at `http://localhost:8000/docs` outside production.

## 3. Verify

```powershell
uv run --project backend ruff check backend
uv run --project backend pytest
npm run lint
npm test
```

## API surface

| Method | Route | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/health` | Public | Process and integration configuration status |
| `GET` | `/api/ready` | Public | Atlas connectivity and service readiness |
| `GET` | `/api/me` | Auth0 | Validated token identity |
| `GET` | `/api/notes` | Auth0 | List the current user's notes |
| `POST` | `/api/notes` | Auth0 | Create a note owned by the current user |
| `DELETE` | `/api/notes/{id}` | Auth0 | Delete an owned note |
| `POST` | `/api/ai/generate` | Auth0 | Generate text with Gemini |

## Structure

```text
app/                              React/Tailwind frontend
backend/
  src/atlas_gemini_api/           FastAPI application package
  tests/                          API tests with cloud services mocked
  pyproject.toml                  uv project and tool configuration
  uv.lock                         reproducible Python dependency lock
.env.example                     browser-safe frontend configuration
backend/.env.example             server-only configuration
```

For production, deploy the FastAPI service to a Python host, set `NEXT_PUBLIC_API_URL` to its HTTPS URL before building the frontend, and allow the deployed frontend origin in both Auth0 and `FRONTEND_ORIGINS`.
