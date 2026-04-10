/** Extracts user-facing error messages from backend and route payloads. */
type ValidationIssue = {
  loc?: unknown;
  msg?: unknown;
};

function formatValidationIssue(issue: ValidationIssue): string | null {
  if (typeof issue.msg !== 'string' || issue.msg.trim() === '') {
    return null;
  }

  const location = Array.isArray(issue.loc)
    ? issue.loc
        .filter((segment): segment is string | number => typeof segment === 'string' || typeof segment === 'number')
        .map(String)
        .join('.')
    : '';

  return location === '' ? issue.msg : `${location}: ${issue.msg}`;
}

/** Collapses FastAPI-style validation issue arrays into a single readable sentence. */
function formatDetailMessage(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim() !== '') {
    return detail;
  }

  if (!Array.isArray(detail)) {
    return null;
  }

  const formattedIssues = detail
    .map((issue) => (issue && typeof issue === 'object' ? formatValidationIssue(issue as ValidationIssue) : null))
    .filter((issue): issue is string => issue !== null);

  if (formattedIssues.length === 0) {
    return null;
  }

  return formattedIssues.join('; ');
}

/** Picks the best available display message from a route error payload. */
export function getApiErrorDisplayMessage(payload: App.Error | null | undefined): string {
  if (!payload) {
    return 'Unexpected application error.';
  }

  const detailMessage = formatDetailMessage((payload as App.Error & { detail?: unknown }).detail);
  if (detailMessage !== null) {
    return detailMessage;
  }

  if (typeof payload.message === 'string' && payload.message.trim() !== '') {
    return payload.message;
  }

  return 'Unexpected application error.';
}
