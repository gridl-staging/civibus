/** Relative and absolute pull-date formatting helpers for trust sections. */
const MILLISECONDS_PER_DAY = 86_400_000;

function toUtcDayStartTimestamp(value: Date): number {
  return Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate());
}

function formatFutureDays(daysUntil: number): string {
  return daysUntil === 1 ? "in 1 day" : `in ${daysUntil} days`;
}

function formatPastDays(daysAgo: number): string {
  return daysAgo === 1 ? "1 day ago" : `${daysAgo} days ago`;
}

export function formatAbsolutePullDate(pullDate: string): string {
  const parsed = new Date(pullDate);

  if (Number.isNaN(parsed.getTime())) {
    throw new TypeError(`formatAbsolutePullDate requires a parseable timestamp: ${pullDate}`);
  }

  const year = parsed.getUTCFullYear();
  const month = String(parsed.getUTCMonth() + 1).padStart(2, "0");
  const day = String(parsed.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Formats a pull timestamp relative to the supplied `now` date using UTC day boundaries. */
export function formatRelativePullDate(pullDate: string, now: Date = new Date()): string {
  const parsedPullDate = new Date(pullDate);
  const parsedPullDateTimestamp = parsedPullDate.getTime();

  if (Number.isNaN(parsedPullDateTimestamp)) {
    throw new TypeError(`formatRelativePullDate requires a parseable timestamp: ${pullDate}`);
  }

  const nowDayStartTimestamp = toUtcDayStartTimestamp(now);
  const pullDayStartTimestamp = toUtcDayStartTimestamp(parsedPullDate);
  const dayDelta = Math.floor((nowDayStartTimestamp - pullDayStartTimestamp) / MILLISECONDS_PER_DAY);

  if (dayDelta === 0) {
    return "today";
  }

  if (dayDelta < 0) {
    return formatFutureDays(Math.abs(dayDelta));
  }

  return formatPastDays(dayDelta);
}
