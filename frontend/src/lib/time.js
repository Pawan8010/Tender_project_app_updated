export function parseApiDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  const text = String(value);
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(text);
  return new Date(hasTimezone ? text : `${text}Z`);
}

export function formatApiDateTime(value, options = {}) {
  const date = parseApiDate(value);
  if (!date || Number.isNaN(date.getTime())) return "Waiting";
  return date.toLocaleString([], options);
}
