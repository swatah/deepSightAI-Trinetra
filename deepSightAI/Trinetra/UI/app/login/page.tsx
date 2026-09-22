"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Eye, EyeOff, Shield, AlertCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Zod validation schema for the login form.
 * Email must be a valid address; password is required (non-empty).
 */
const dsai_loginSchema = z.object({
  dsai_email: z.string().email("Please enter a valid email address."),
  dsai_password: z.string().min(1, "Password is required."),
});

type DsaiLoginFormValues = z.infer<typeof dsai_loginSchema>;

/**
 * Branded enterprise login page for deepSightAI Trinetra.
 *
 * Features:
 * - react-hook-form + Zod client-side validation
 * - Calls NextAuth signIn() with CredentialsProvider
 * - Reads callbackUrl query param and redirects after successful login
 * - Displays descriptive error banners for invalid credentials / network issues
 * - Loading spinner during authentication request
 * - Responsive across mobile, tablet, and desktop viewports
 */
export default function DsaiLoginPage() {
  const dsai_router = useRouter();
  const dsai_searchParams = useSearchParams();
  const dsai_callbackUrl = dsai_searchParams.get("callbackUrl") || "/";

  const [dsai_showPassword, dsai_setShowPassword] = useState(false);
  const [dsai_errorMessage, dsai_setErrorMessage] = useState<string | null>(null);

  const {
    register: dsai_register,
    handleSubmit: dsai_handleSubmit,
    formState: { errors: dsai_errors, isSubmitting: dsai_isSubmitting },
  } = useForm<DsaiLoginFormValues>({
    resolver: zodResolver(dsai_loginSchema),
    defaultValues: { dsai_email: "", dsai_password: "" },
  });

  const dsai_onSubmit = async (dsai_values: DsaiLoginFormValues) => {
    dsai_setErrorMessage(null);

    const dsai_result = await signIn("credentials", {
      email: dsai_values.dsai_email,
      password: dsai_values.dsai_password,
      redirect: false,
    });

    if (!dsai_result || dsai_result.error) {
      if (dsai_result?.error === "CredentialsSignin") {
        dsai_setErrorMessage("Invalid email or password. Please try again.");
      } else {
        dsai_setErrorMessage(
          "Unable to reach the authentication service. Please check your network connection and try again."
        );
      }
      return;
    }

    // Successful login — redirect to the originally requested page (or home)
    dsai_router.push(dsai_callbackUrl);
    dsai_router.refresh();
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 px-4 py-12">
      <div className="w-full max-w-md space-y-8">
        {/* Brand header */}
        <div className="text-center">
          <div className="flex items-center justify-center gap-3 mb-4">
            <Shield className="h-10 w-10 text-blue-400" aria-hidden="true" />
            <span className="text-3xl font-bold text-white tracking-tight">
              Trinetra
            </span>
          </div>
          <p className="text-slate-400 text-sm">
            deepSightAI Visual Intelligence Platform
          </p>
          <p className="text-slate-500 text-xs mt-1">
            Authorised access only — all sessions are audited
          </p>
        </div>

        {/* Login card */}
        <Card className="bg-slate-900 border-slate-700 shadow-2xl">
          <CardHeader className="pb-4">
            <CardTitle className="text-white text-xl">Sign in</CardTitle>
            <CardDescription className="text-slate-400">
              Enter your credentials to access your workspace.
            </CardDescription>
          </CardHeader>

          <CardContent>
            {/* Error banner */}
            {dsai_errorMessage && (
              <div
                role="alert"
                className="mb-4 flex items-start gap-3 rounded-md bg-red-900/30 border border-red-700/50 px-4 py-3 text-sm text-red-300"
              >
                <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" aria-hidden="true" />
                <span>{dsai_errorMessage}</span>
              </div>
            )}

            <form
              onSubmit={dsai_handleSubmit(dsai_onSubmit)}
              noValidate
              className="space-y-5"
              aria-label="Login form"
            >
              {/* Email field */}
              <div className="space-y-1.5">
                <label
                  htmlFor="dsai-email"
                  className="text-sm font-medium text-slate-300"
                >
                  Email address
                </label>
                <Input
                  id="dsai-email"
                  type="email"
                  autoComplete="email"
                  placeholder="operator@trinetra.ai"
                  className="bg-slate-800 border-slate-600 text-white placeholder:text-slate-500 focus:border-blue-500 focus:ring-blue-500"
                  aria-invalid={!!dsai_errors.dsai_email}
                  aria-describedby={
                    dsai_errors.dsai_email ? "dsai-email-error" : undefined
                  }
                  {...dsai_register("dsai_email")}
                />
                {dsai_errors.dsai_email && (
                  <p
                    id="dsai-email-error"
                    role="alert"
                    className="text-xs text-red-400"
                  >
                    {dsai_errors.dsai_email.message}
                  </p>
                )}
              </div>

              {/* Password field */}
              <div className="space-y-1.5">
                <label
                  htmlFor="dsai-password"
                  className="text-sm font-medium text-slate-300"
                >
                  Password
                </label>
                <div className="relative">
                  <Input
                    id="dsai-password"
                    type={dsai_showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    placeholder="••••••••"
                    className="bg-slate-800 border-slate-600 text-white placeholder:text-slate-500 focus:border-blue-500 focus:ring-blue-500 pr-10"
                    aria-invalid={!!dsai_errors.dsai_password}
                    aria-describedby={
                      dsai_errors.dsai_password ? "dsai-password-error" : undefined
                    }
                    {...dsai_register("dsai_password")}
                  />
                  <button
                    type="button"
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 transition-colors"
                    onClick={() => dsai_setShowPassword((dsai_prev) => !dsai_prev)}
                    aria-label={
                      dsai_showPassword ? "Hide password" : "Show password"
                    }
                  >
                    {dsai_showPassword ? (
                      <EyeOff className="h-4 w-4" aria-hidden="true" />
                    ) : (
                      <Eye className="h-4 w-4" aria-hidden="true" />
                    )}
                  </button>
                </div>
                {dsai_errors.dsai_password && (
                  <p
                    id="dsai-password-error"
                    role="alert"
                    className="text-xs text-red-400"
                  >
                    {dsai_errors.dsai_password.message}
                  </p>
                )}
              </div>

              {/* Submit button */}
              <Button
                type="submit"
                disabled={dsai_isSubmitting}
                className="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold disabled:opacity-60 transition-colors"
              >
                {dsai_isSubmitting ? (
                  <>
                    <Loader2
                      className="mr-2 h-4 w-4 animate-spin"
                      aria-hidden="true"
                    />
                    Authenticating…
                  </>
                ) : (
                  "Sign In"
                )}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Footer note */}
        <p className="text-center text-xs text-slate-600">
          deepSightAI Trinetra &copy; {new Date().getFullYear()} — Enterprise Visual Intelligence
        </p>
      </div>
    </div>
  );
}
