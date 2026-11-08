// Чистые функции без DOM — их покрывают тесты в frontend/tests.

const DAYS_IN_YEAR = 365.25;

/**
 * Превращает пары [имя, значение] из формы в запись для POST /predict.
 * Все поля числовые; возраст в форме — в годах, а модель ждёт дни (как в датасете).
 */
export function buildRecord(entries) {
  const record = {};
  for (const [name, rawValue] of entries) {
    const value = String(rawValue).trim();
    if (value === '') continue;
    if (name === 'age_years') {
      record.age = Math.round(Number(value) * DAYS_IN_YEAR);
    } else {
      record[name] = Number(value);
    }
  }
  return record;
}

export function formatPercent(probability) {
  return `${(probability * 100).toFixed(1)}%`;
}

/** Достаёт читаемый текст из ответа об ошибке формата {status, detail}. */
export function describeError(body, fallback = 'Неизвестная ошибка') {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((error) => `${error.field}: ${error.message}`).join('; ');
  }
  return fallback;
}

/** Первые limit строк таблицы, колонки в порядке первой записи. */
export function previewTable(records, limit = 20) {
  if (!records.length) return { columns: [], rows: [] };
  const columns = Object.keys(records[0]);
  const rows = records
    .slice(0, limit)
    .map((record) => columns.map((column) => record[column] ?? ''));
  return { columns, rows };
}

/** Строки для графика ROC-AUC моделей, лучшая — первой. */
export function metricsBars(metrics) {
  if (!metrics?.models) return [];
  return Object.entries(metrics.models)
    .map(([name, scores]) => ({
      name,
      value: scores.test_roc_auc,
      best: name === metrics.best_model,
    }))
    .sort((a, b) => b.value - a.value);
}
