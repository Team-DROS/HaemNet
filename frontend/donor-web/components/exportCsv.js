// Download rows as a CSV file (web). Cells starting with = + - @ are prefixed
// so spreadsheets never run them as formulas.

const clean = (value) => {
  let text = value === null || value === undefined ? '' : String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
};

export function toCsv(columns, rows) {
  const head = columns.map((c) => clean(c.label)).join(',');
  const body = rows.map((row) => columns.map((c) => clean(c.value(row))).join(','));
  return [head, ...body].join('\r\n');
}

export function downloadCsv(filename, columns, rows) {
  if (typeof document === 'undefined') return false;
  const blob = new Blob([`﻿${toCsv(columns, rows)}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return true;
}
