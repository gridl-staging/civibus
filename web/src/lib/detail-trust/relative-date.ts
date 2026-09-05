/** Relative and absolute pull-date formatting helpers for trust sections. */
const MILLISECONDS_PER_DAY = 86_400_000;
const ISO_CALENDAR_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})(?:T|$)/;

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

// Date.parse normalizes some impossible ISO dates, so validate the supplied
// calendar components before trusting its timestamp.
function isPossibleIsoCalendarDate(value: string): boolean {
  const match = ISO_CALENDAR_DATE_PATTERN.exec(value.trim());
  if (match === null) {
    return true;
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const daysByMonth = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

  return month >= 1 && month <= 12 && day >= 1 && day <= daysByMonth[month - 1];
}

export function parsePullDateTimestamp(value: string): number | null {
  const timestamp = Date.parse(value);

  if (Number.isNaN(timestamp) || !isPossibleIsoCalendarDate(value)) {
    return null;
  }

  return timestamp;
}

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
  const parsedTimestamp = parsePullDateTimestamp(pullDate);

  if (parsedTimestamp === null) {
    throw new TypeError(`formatAbsolutePullDate requires a parseable timestamp: ${pullDate}`);
  }

  const parsed = new Date(parsedTimestamp);
  const year = parsed.getUTCFullYear();
  const month = String(parsed.getUTCMonth() + 1).padStart(2, "0");
  const day = String(parsed.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Formats a pull timestamp relative to the supplied `now` date using UTC day boundaries. */
export function formatRelativePullDate(pullDate: string, now: Date = new Date()): string {
  const parsedPullDateTimestamp = parsePullDateTimestamp(pullDate);

  if (parsedPullDateTimestamp === null) {
    throw new TypeError(`formatRelativePullDate requires a parseable timestamp: ${pullDate}`);
  }

  const parsedPullDate = new Date(parsedPullDateTimestamp);
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
