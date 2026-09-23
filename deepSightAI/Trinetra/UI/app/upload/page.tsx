import { redirect } from "next/navigation";

/**
 * /upload redirect route — forwards traffic to the canonical /ingest upload flow.
 * Prevents 404s if users access /upload directly or follow legacy links.
 */
export default function UploadRedirectPage() {
  redirect("/ingest");
}
