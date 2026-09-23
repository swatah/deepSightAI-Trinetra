/**
 * CSV Export utility for Tenant Analytics & Audit Activity (REL-66 / Issue #52).
 */

export interface ActivityLogEntry {
  timestamp: string;
  event_type: string;
  user_id: string;
  camera_id: string;
  details: string;
}

/**
 * Escapes a single CSV value according to RFC 4180:
 * Encloses values in quotes if they contain commas, double quotes, or newlines,
 * and escapes internal quotes by doubling them (" -> "").
 */
export function dsai_escapeCsvCell(dsai_value: string | number | null | undefined): string {
  if (dsai_value === null || dsai_value === undefined) return '""';
  const dsai_str = String(dsai_value);
  if (/[",\n\r]/.test(dsai_str)) {
    return `"${dsai_str.replace(/"/g, '""')}"`;
  }
  return `"${dsai_str}"`;
}

/**
 * Formats an array of string values into a single CSV row.
 */
export function dsai_formatCsvRow(dsai_fields: (string | number | null | undefined)[]): string {
  return dsai_fields.map(dsai_escapeCsvCell).join(",");
}

/**
 * Converts a list of activity records into a complete RFC 4180 CSV string with headers.
 */
export function dsai_exportActivityLogToCsv(dsai_records: ActivityLogEntry[]): string {
  const dsai_headers = ["Timestamp", "Event Type", "User ID", "Camera ID", "Details"];
  const dsai_lines = [dsai_formatCsvRow(dsai_headers)];

  for (const dsai_item of dsai_records) {
    dsai_lines.push(
      dsai_formatCsvRow([
        dsai_item.timestamp,
        dsai_item.event_type,
        dsai_item.user_id,
        dsai_item.camera_id,
        dsai_item.details,
      ])
    );
  }

  return dsai_lines.join("\r\n");
}

/**
 * Triggers a client-side browser file download for CSV content.
 */
export function dsai_downloadCsvFile(dsai_csvContent: string, dsai_filename: string): void {
  if (typeof window === "undefined") return;

  const dsai_blob = new Blob([dsai_csvContent], { type: "text/csv;charset=utf-8;" });
  const dsai_url = URL.createObjectURL(dsai_blob);
  const dsai_link = document.createElement("a");
  dsai_link.setAttribute("href", dsai_url);
  dsai_link.setAttribute("download", dsai_filename);
  document.body.appendChild(dsai_link);
  dsai_link.click();
  document.body.removeChild(dsai_link);
  URL.revokeObjectURL(dsai_url);
}
