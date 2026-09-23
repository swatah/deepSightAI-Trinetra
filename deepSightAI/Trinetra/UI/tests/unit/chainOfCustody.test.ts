import {
  dsai_computeSha256,
  dsai_verifyEvidenceHash,
  dsai_createEvidenceManifest,
  EvidenceSegment,
} from "../../lib/chainOfCustody";

describe("Chain of Custody & CJIS Compliance Suite (#49)", () => {
  it("computes standard SHA-256 hex hash for string input", async () => {
    // SHA-256 of empty string is e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
    const hash = await dsai_computeSha256("");
    expect(hash).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  });

  it("verifies matching evidence hash correctly", async () => {
    const data = "video-evidence-segment-raw-bytes";
    const expected = await dsai_computeSha256(data);

    const isMatch = await dsai_verifyEvidenceHash(data, expected);
    expect(isMatch).toBe(true);

    const isTampered = await dsai_verifyEvidenceHash(data, "0000000000000000000000000000000000000000000000000000000000000000");
    expect(isTampered).toBe(false);
  });

  it("builds a CJIS-compliant evidence manifest with 7-year retention", () => {
    const mockSegments: EvidenceSegment[] = [
      {
        id: "EVID-101",
        video_id: "vid-1",
        camera_id: "cam-gate",
        start_time: "2026-09-22 10:00:00 UTC",
        end_time: "2026-09-22 10:15:00 UTC",
        sha256_hash: "abcd1234efef5678",
        storage_uri: "s3://evidence/vid-1.mp4",
        access_history: [],
      },
    ];

    const manifest = dsai_createEvidenceManifest(
      "EXP-999",
      "OFFICER-77",
      "Sheriff Dept",
      "Subpoena 123",
      mockSegments
    );

    expect(manifest.export_id).toBe("EXP-999");
    expect(manifest.compliance.retention_period_years).toBe(7);
    expect(manifest.compliance.cjis_policy_version).toBe("5.9.2");
    expect(manifest.compliance.tamper_evident).toBe(true);
    expect(manifest.evidence_segments).toHaveLength(1);
    expect(manifest.evidence_segments[0].id).toBe("EVID-101");
  });
});
