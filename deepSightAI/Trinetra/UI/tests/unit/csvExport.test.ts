import {
  dsai_escapeCsvCell,
  dsai_formatCsvRow,
  dsai_exportActivityLogToCsv,
  ActivityLogEntry,
} from "../../lib/csvExport";

describe("CSV Export & Activity Log Suite (#52)", () => {
  it("escapes CSV values containing commas and internal quotes", () => {
    expect(dsai_escapeCsvCell("StandardText")).toBe('"StandardText"');
    expect(dsai_escapeCsvCell('Alert "CRITICAL" detected')).toBe('"Alert ""CRITICAL"" detected"');
    expect(dsai_escapeCsvCell("Gate 1, Zone B")).toBe('"Gate 1, Zone B"');
    expect(dsai_escapeCsvCell(null)).toBe('""');
  });

  it("formats CSV row joined by commas", () => {
    const row = dsai_formatCsvRow(["2026-09-22 14:00:00", "SEARCH", "user_1", "CAM-01", "Details text"]);
    expect(row).toBe('"2026-09-22 14:00:00","SEARCH","user_1","CAM-01","Details text"');
  });

  it("converts activity log entries into valid RFC 4180 CSV with standard headers", () => {
    const records: ActivityLogEntry[] = [
      {
        timestamp: "2026-09-22 10:00:00 UTC",
        event_type: "LOGIN",
        user_id: "admin_1",
        camera_id: "N/A",
        details: "Authenticated via password",
      },
      {
        timestamp: "2026-09-22 10:15:00 UTC",
        event_type: "SEARCH",
        user_id: "officer_2",
        camera_id: "CAM-05",
        details: 'Queried "black SUV, speed > 40"',
      },
    ];

    const csv = dsai_exportActivityLogToCsv(records);
    const lines = csv.split("\r\n");

    expect(lines).toHaveLength(3);
    expect(lines[0]).toBe('"Timestamp","Event Type","User ID","Camera ID","Details"');
    expect(lines[1]).toContain('"LOGIN"');
    expect(lines[2]).toContain('""black SUV, speed > 40""');
  });
});
