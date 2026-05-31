// Status pills for the Worked-time column of the Employees tables.
//
// Both mirror the dashboard Flags panel's tag styling (rounded, 11px,
// medium) so attendance status reads the same across the product:
//   - AbsentPill  → red   (bg-danger-bg / text-danger-text): expected,
//                   never punched, no excuse.
//   - OnLeavePill → pale  (bg-leave-bg  / text-leave-text):  absence
//                   excused by an approved full-day Time Off entry.
const PILL_BASE = "rounded px-[9px] py-[3px] text-[11px] font-medium";

export function AbsentPill() {
  return (
    <span className={`${PILL_BASE} bg-danger-bg text-danger-text`}>Absent</span>
  );
}

export function OnLeavePill() {
  return (
    <span className={`${PILL_BASE} bg-leave-bg text-leave-text`}>On leave</span>
  );
}
