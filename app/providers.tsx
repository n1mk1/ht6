"use client";

import { Auth0Provider } from "@auth0/auth0-react";
import type { ReactNode } from "react";

import { auth0Configured, clientConfig } from "./client-config";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <Auth0Provider
      domain={clientConfig.auth0Domain || "not-configured.auth0.com"}
      clientId={clientConfig.auth0ClientId || "not-configured"}
      authorizationParams={{
        redirect_uri: clientConfig.appUrl,
        ...(auth0Configured ? { audience: clientConfig.auth0Audience } : {}),
      }}
      skipRedirectCallback={!auth0Configured}
    >
      {children}
    </Auth0Provider>
  );
}
