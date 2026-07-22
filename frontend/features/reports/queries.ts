import { useQuery } from "@tanstack/react-query";

import { getExportRoster } from "./api";
import type { ReportView } from "./download";

export function useExportRoster(view: ReportView) {
  return useQuery({
    queryKey: ["export-roster", view.mode, view.date, view.start, view.end],
    queryFn: () => getExportRoster(view),
    // The roster changes rarely; no need to poll while the dialog is open.
    staleTime: 5 * 60_000,
  });
}
