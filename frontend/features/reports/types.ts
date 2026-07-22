import { z } from "zod";

export const rosterEmployeeSchema = z.object({
  emp_code: z.string(),
  name: z.string(),
  department: z.string(),
});

export const exportRosterSchema = z.object({
  employees: z.array(rosterEmployeeSchema),
});

export type RosterEmployee = z.infer<typeof rosterEmployeeSchema>;
export type ExportRoster = z.infer<typeof exportRosterSchema>;
