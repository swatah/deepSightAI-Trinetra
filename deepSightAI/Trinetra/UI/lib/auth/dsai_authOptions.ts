import { type NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import { z } from "zod";
import { jwtDecode } from "jwt-decode";

/**
 * Zod schema for validating login form credentials before sending to AuthService.
 */
const dsai_CredentialsSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

/**
 * Shape of the RS256 JWT payload issued by AuthService.
 * AuthService issues ONLY `roles` — never a `permissions` array.
 */
interface DsaiJwtClaims {
  sub: string;
  email: string;
  tenant_id: string;
  roles: string[];
  exp: number;
  iat: number;
}

/**
 * NextAuth configuration for deepSightAI Trinetra.
 * Authenticates directly against AuthService (POST /auth/login, port 8002).
 */
export const dsai_authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: "deepSightAI Trinetra",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(dsai_credentials) {
        // Validate input shape with Zod before hitting the network
        const dsai_parsed = dsai_CredentialsSchema.safeParse(dsai_credentials);
        if (!dsai_parsed.success) return null;

        const { email: dsai_email, password: dsai_password } = dsai_parsed.data;

        const dsai_authServiceUrl =
          process.env.AUTH_SERVICE_URL || "http://auth-service:8002";

        try {
          const dsai_response = await fetch(
            `${dsai_authServiceUrl}/auth/login`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                email: dsai_email,
                password: dsai_password,
              }),
            }
          );

          if (!dsai_response.ok) return null;

          const dsai_responseData = await dsai_response.json();
          const dsai_accessToken: string = dsai_responseData.access_token;

          if (!dsai_accessToken) return null;

          // Decode RS256 JWT claims — sub, email, tenant_id, roles
          const dsai_claims = jwtDecode<DsaiJwtClaims>(dsai_accessToken);

          return {
            id: dsai_claims.sub,
            email: dsai_claims.email,
            dsai_tenantId: dsai_claims.tenant_id,
            dsai_roles: dsai_claims.roles,
            dsai_accessToken,
          };
        } catch {
          // Network failure or invalid JSON — return null for clean 401
          return null;
        }
      },
    }),
  ],

  callbacks: {
    /**
     * Persist custom claims (access_token, tenant_id, roles) into the JWT cookie.
     * Runs on sign-in and on every session validation.
     */
    async jwt({ token: dsai_token, user: dsai_user }) {
      if (dsai_user) {
        dsai_token.dsai_accessToken = (dsai_user as any).dsai_accessToken;
        dsai_token.dsai_tenantId = (dsai_user as any).dsai_tenantId;
        dsai_token.dsai_roles = (dsai_user as any).dsai_roles;
        dsai_token.email = dsai_user.email;
      }
      return dsai_token;
    },

    /**
     * Expose custom claims to the client-side useSession() hook.
     */
    async session({ session: dsai_session, token: dsai_token }) {
      dsai_session.dsai_accessToken = dsai_token.dsai_accessToken as string;
      dsai_session.dsai_tenantId = dsai_token.dsai_tenantId as string;
      dsai_session.dsai_roles = dsai_token.dsai_roles as string[];
      if (dsai_session.user) {
        dsai_session.user.email = dsai_token.email as string;
      }
      return dsai_session;
    },
  },

  pages: {
    signIn: "/login",
    error: "/login",
  },

  session: {
    strategy: "jwt",
    // AuthService tokens expire in 60 minutes — match session lifetime
    maxAge: 60 * 60,
  },

  secret: process.env.NEXTAUTH_SECRET,
};
