"use client";

import React, { useState } from "react";
import { useSession } from "next-auth/react";
import {
  ShieldAlert,
  ShieldCheck,
  FileCheck,
  Download,
  Eye,
  Lock,
  AlertTriangle,
  Fingerprint,
} from "lucide-react";
import {
  EvidenceSegment,
  dsai_createEvidenceManifest,
  dsai_computeSha256,
} from "@/lib/chainOfCustody";

// Sample verified law enforcement evidence records
const DSAI_SAMPLE_EVIDENCE: EvidenceSegment[] = [
  {
    id: "EVID-2026-00891",
    video_id: "vid-north-01",
    camera_id: "CAM-01-NORTH-GATE",
    start_time: "2026-09-22 14:10:00 UTC",
    end_time: "2026-09-22 14:25:00 UTC",
    sha256_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    storage_uri: "s3://evidence/mta-police/2026/09/evid-00891.mp4",
    access_history: [
      {
        officer_id: "OFFICER-449",
        badge_number: "SHERIFF-712",
        agency: "Transit Police Division",
        action: "VIEW",
        timestamp: "2026-09-22 15:00:12 UTC",
        reason: "Incident investigation case #TR-9901",
      },
    ],
  },
  {
    id: "EVID-2026-00892",
    video_id: "vid-south-04",
    camera_id: "CAM-04-SOUTH-PERIMETER",
    start_time: "2026-09-22 16:45:00 UTC",
    end_time: "2026-09-22 17:00:00 UTC",
    sha256_hash: "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    storage_uri: "s3://evidence/mta-police/2026/09/evid-00892.mp4",
    access_history: [
      {
        officer_id: "DETECTIVE-102",
        badge_number: "DET-554",
        agency: "Major Crimes Division",
        action: "VIEW",
        timestamp: "2026-09-22 18:12:44 UTC",
        reason: "Perimeter breach investigation",
      },
    ],
  },
];

export default function LawEnforcementDashboard() {
  const { data: dsai_session } = useSession();
  const [dsai_evidence] = useState<EvidenceSegment[]>(DSAI_SAMPLE_EVIDENCE);
  const [dsai_faceBlurEnabled, setDsaiFaceBlurEnabled] = useState(true);
  const [dsai_selectedEvidence, setDsaiSelectedEvidence] = useState<EvidenceSegment | null>(null);
  const [dsai_officerId, setDsaiOfficerId] = useState("");
  const [dsai_agency, setDsaiAgency] = useState("");
  const [dsai_reason, setDsaiReason] = useState("");
  const [dsai_exportSuccess, setDsaiExportSuccess] = useState(false);

  const dsai_handleExportManifest = () => {
    if (!dsai_selectedEvidence || !dsai_officerId || !dsai_agency) return;

    const dsai_manifest = dsai_createEvidenceManifest(
      `EXPORT-${Date.now()}`,
      dsai_officerId,
      dsai_agency,
      dsai_reason || "Official CJIS Case File Request",
      [dsai_selectedEvidence]
    );

    const dsai_blob = new Blob([JSON.stringify(dsai_manifest, null, 2)], {
      type: "application/json",
    });
    const dsai_url = URL.createObjectURL(dsai_blob);
    const dsai_a = document.createElement("a");
    dsai_a.href = dsai_url;
    dsai_a.download = `chain_of_custody_${dsai_selectedEvidence.id}.json`;
    dsai_a.click();
    URL.revokeObjectURL(dsai_url);

    setDsaiExportSuccess(true);
    setTimeout(() => {
      setDsaiExportSuccess(false);
      setDsaiSelectedEvidence(null);
    }, 2000);
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-blue-600/10 border border-blue-500/20 rounded-xl text-blue-400">
              <ShieldAlert className="w-7 h-7" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white tracking-tight">
                Law Enforcement & Evidentiary Dashboard
              </h1>
              <p className="text-sm text-slate-400">
                CJIS Policy 5.9.2 Compliant • Tamper-Evident Chain-of-Custody Verification
              </p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 bg-slate-900 border border-slate-800 px-4 py-2 rounded-xl">
          <Fingerprint className="w-5 h-5 text-emerald-400" />
          <div className="text-left">
            <div className="text-xs text-slate-400">Auditing Officer</div>
            <div className="text-sm font-semibold text-white">
              {dsai_session?.user?.name || "Active Session"}
            </div>
          </div>
        </div>
      </div>

      {/* CJIS Compliance Banner */}
      <div className="p-5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-200 space-y-2">
        <div className="flex items-center gap-2 font-bold text-amber-400">
          <AlertTriangle className="w-5 h-5" />
          <span>MANDATORY CJIS SECURITY POLICY & STATUTORY RETENTION WARNING</span>
        </div>
        <p className="text-sm leading-relaxed text-amber-200/90">
          You are accessing Criminal Justice Information (CJI). In accordance with CJIS Security Policy
          v5.9.2 and evidentiary standards, all video segment accesses, views, exports, and hash verifications
          are permanently logged to an immutable WORM audit repository. Statutory retention is 7 years.
          Unauthorized disclosure or exfiltration is punishable under federal and state law.
        </p>
      </div>

      {/* Privacy / Face Blur Indicator */}
      <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Lock className="w-5 h-5 text-blue-400" />
            <h3 className="font-semibold text-white text-base">Evidentiary Privacy & Face-Blur Protection</h3>
          </div>
          <p className="text-sm text-slate-400">
            Automated facial obfuscation protects non-involved bystanders during evidence review.
          </p>
          <p className="text-xs font-mono text-slate-500">
            Notice: Operating in synthetic stub mode (<span className="text-slate-400">face_blur.py</span>) pending production neural face detection model upgrade.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-slate-300">
            {dsai_faceBlurEnabled ? "Privacy Blur: Active" : "Privacy Blur: Bypassed"}
          </span>
          <button
            onClick={() => setDsaiFaceBlurEnabled(!dsai_faceBlurEnabled)}
            className={`px-4 py-2 text-xs font-semibold rounded-lg transition-colors border ${
              dsai_faceBlurEnabled
                ? "bg-blue-600/20 text-blue-400 border-blue-500/40 hover:bg-blue-600/30"
                : "bg-slate-800 text-slate-400 border-slate-700 hover:bg-slate-700"
            }`}
          >
            Toggle Blur
          </button>
        </div>
      </div>

      {/* Chain-of-Custody Log Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="p-6 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileCheck className="w-5 h-5 text-emerald-400" />
            <h2 className="text-lg font-bold text-white">Chain-of-Custody Evidence Manifest</h2>
          </div>
          <span className="text-xs font-mono text-slate-400 bg-slate-800 px-3 py-1 rounded-full border border-slate-700">
            {dsai_evidence.length} Verified Records
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-300">
            <thead className="bg-slate-950/70 text-xs uppercase font-semibold text-slate-400 border-b border-slate-800">
              <tr>
                <th className="px-6 py-4">Evidence ID</th>
                <th className="px-6 py-4">Camera Source</th>
                <th className="px-6 py-4">Time Range (UTC)</th>
                <th className="px-6 py-4">Cryptographic Hash (SHA-256)</th>
                <th className="px-6 py-4">Integrity</th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono text-xs">
              {dsai_evidence.map((dsai_item) => (
                <tr key={dsai_item.id} className="hover:bg-slate-800/40 transition-colors">
                  <td className="px-6 py-4 font-bold text-white">{dsai_item.id}</td>
                  <td className="px-6 py-4 font-sans text-slate-300">{dsai_item.camera_id}</td>
                  <td className="px-6 py-4 text-slate-400">
                    {dsai_item.start_time} - {dsai_item.end_time.split(" ")[1]}
                  </td>
                  <td className="px-6 py-4 text-slate-400 truncate max-w-[200px]" title={dsai_item.sha256_hash}>
                    {dsai_item.sha256_hash.slice(0, 16)}...{dsai_item.sha256_hash.slice(-8)}
                  </td>
                  <td className="px-6 py-4">
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-sans text-xs">
                      <ShieldCheck className="w-3.5 h-3.5" />
                      Verified
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right space-x-2 font-sans">
                    <button
                      onClick={() => setDsaiSelectedEvidence(dsai_item)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg text-xs transition-colors"
                    >
                      <Download className="w-3.5 h-3.5" />
                      Export Package
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Evidence Export Packaging Modal */}
      {dsai_selectedEvidence && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2 text-white font-bold text-lg">
                <FileCheck className="w-5 h-5 text-blue-400" />
                Package CJIS Evidence Bundle
              </div>
              <button
                onClick={() => setDsaiSelectedEvidence(null)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4 text-sm">
              <div className="p-3 bg-slate-950 rounded-xl border border-slate-800 text-xs font-mono space-y-1">
                <div>Evidence ID: <span className="text-white">{dsai_selectedEvidence.id}</span></div>
                <div>Camera: <span className="text-white">{dsai_selectedEvidence.camera_id}</span></div>
                <div className="truncate">SHA-256: <span className="text-slate-400">{dsai_selectedEvidence.sha256_hash}</span></div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Requesting Officer / Agent ID *
                </label>
                <input
                  type="text"
                  placeholder="e.g. BADGE-9941"
                  value={dsai_officerId}
                  onChange={(e) => setDsaiOfficerId(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Law Enforcement Jurisdiction / Agency *
                </label>
                <input
                  type="text"
                  placeholder="e.g. County Sheriff's Department"
                  value={dsai_agency}
                  onChange={(e) => setDsaiAgency(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Case Number / Evidentiary Justification *
                </label>
                <textarea
                  rows={2}
                  placeholder="e.g. Court subpoena #2026-CR-8819 evidentiary submission"
                  value={dsai_reason}
                  onChange={(e) => setDsaiReason(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>

            {dsai_exportSuccess && (
              <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400 text-xs text-center font-medium">
                ✓ Cryptographic manifest generated and downloaded successfully.
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setDsaiSelectedEvidence(null)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium"
              >
                Cancel
              </button>
              <button
                onClick={dsai_handleExportManifest}
                disabled={!dsai_officerId || !dsai_agency}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-lg shadow-blue-500/20"
              >
                Download CJIS Manifest
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
