# Praxis frontend

The dashboard is a standalone Vite/React client. It only communicates with the
versioned backend API and has no imports from `qnx/` or `freesolo/`.

The first screen asks for the participant username used on the QNX device. It
resolves or creates that record through `POST /api/v1/users/resolve`, then shows
the participant's latest session, history, run details, trends, and compatible
comparisons. Username access is record matching, not authentication.

## Development

```bash
cd frontend
npm install
npm run dev
```

The Vite development server proxies `/api` to `http://localhost:8000`. Set
`VITE_API_URL` to use another API origin. Open `http://localhost:5173`.

## Verification

```bash
npm run lint
npm run test
npm run build
```

The component tests cover username resolution, empty and error states, session
history, run detail, comparison, and returning to the username screen.
