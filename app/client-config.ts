export const clientConfig = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  appUrl: process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000",
  auth0Domain: process.env.NEXT_PUBLIC_AUTH0_DOMAIN ?? "",
  auth0ClientId: process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID ?? "",
  auth0Audience: process.env.NEXT_PUBLIC_AUTH0_AUDIENCE ?? "",
};

export const auth0Configured = Boolean(
  clientConfig.auth0Domain &&
    clientConfig.auth0ClientId &&
    clientConfig.auth0Audience,
);
