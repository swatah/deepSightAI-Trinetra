/**
 * NextAuth type augmentation for deepSightAI Trinetra.
 * Extends the default Session and JWT interfaces with Trinetra-specific fields.
 */
import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    /** RS256 access token from AuthService — attach to every backend API request */
    dsai_accessToken: string;
    /** Tenant identifier for multi-tenant data isolation */
    dsai_tenantId: string;
    /** RBAC roles array: ["admin"], ["operator"], or ["viewer"] */
    dsai_roles: string[];
  }

  interface User {
    dsai_accessToken: string;
    dsai_tenantId: string;
    dsai_roles: string[];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    dsai_accessToken: string;
    dsai_tenantId: string;
    dsai_roles: string[];
  }
}
