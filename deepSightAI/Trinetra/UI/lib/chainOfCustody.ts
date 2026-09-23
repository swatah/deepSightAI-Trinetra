/**
 * Chain of Custody & Cryptographic Verification utilities for Law Enforcement Evidence.
 * (REL-65 / Issue #49)
 */

export interface EvidenceAccessRecord {
  officer_id: string;
  badge_number: string;
  agency: string;
  action: "VIEW" | "EXPORT" | "VERIFY";
  timestamp: string;
  reason?: string;
}

export interface EvidenceSegment {
  id: string;
  video_id: string;
  camera_id: string;
  start_time: string;
  end_time: string;
  sha256_hash: string;
  storage_uri: string;
  access_history: EvidenceAccessRecord[];
}

export interface EvidenceManifest {
  manifest_version: string;
  export_id: string;
  generated_at: string;
  exporting_officer: {
    officer_id: string;
    agency: string;
    reason: string;
  };
  compliance: {
    cjis_policy_version: string;
    retention_period_years: number;
    tamper_evident: boolean;
  };
  evidence_segments: {
    id: string;
    sha256_hash: string;
    camera_id: string;
    timestamp_range: string;
  }[];
}

/**
 * Calculates SHA-256 hex string for given text or buffer using Web Crypto API.
 */
export async function dsai_computeSha256(dsai_data: string | ArrayBuffer): Promise<string> {
  let dsai_buffer: ArrayBuffer;
  if (typeof dsai_data === "string") {
    dsai_buffer = new TextEncoder().encode(dsai_data).buffer;
  } else {
    dsai_buffer = dsai_data;
  }

  const dsai_cryptoSubtle =
    typeof globalThis !== "undefined" && globalThis.crypto?.subtle
      ? globalThis.crypto.subtle
      : (require("crypto").webcrypto.subtle as SubtleCrypto);

  const dsai_hashBuffer = await dsai_cryptoSubtle.digest("SHA-256", dsai_buffer);
  const dsai_hashArray = Array.from(new Uint8Array(dsai_hashBuffer));
  return dsai_hashArray.map((dsai_b) => dsai_b.toString(16).padStart(2, "0")).join("");
}

/**
 * Verifies that the computed hash of data matches the expected cryptographic evidence hash.
 */
export async function dsai_verifyEvidenceHash(
  dsai_data: string | ArrayBuffer,
  dsai_expectedHash: string
): Promise<boolean> {
  const dsai_computed = await dsai_computeSha256(dsai_data);
  return dsai_computed.toLowerCase() === dsai_expectedHash.trim().toLowerCase();
}

/**
 * Builds a standardized CJIS-compliant evidence export manifest.
 */
export function dsai_createEvidenceManifest(
  dsai_exportId: string,
  dsai_officerId: string,
  dsai_agency: string,
  dsai_reason: string,
  dsai_segments: EvidenceSegment[]
): EvidenceManifest {
  return {
    manifest_version: "1.0-CJIS",
    export_id: dsai_exportId,
    generated_at: new Date().toISOString(),
    exporting_officer: {
      officer_id: dsai_officerId,
      agency: dsai_agency,
      reason: dsai_reason,
    },
    compliance: {
      cjis_policy_version: "5.9.2",
      retention_period_years: 7,
      tamper_evident: true,
    },
    evidence_segments: dsai_segments.map((dsai_seg) => ({
      id: dsai_seg.id,
      sha256_hash: dsai_seg.sha256_hash,
      camera_id: dsai_seg.camera_id,
      timestamp_range: `${dsai_seg.start_time} - ${dsai_seg.end_time}`,
    })),
  };
}
