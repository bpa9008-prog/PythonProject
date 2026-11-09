// Чистые функции страницы клиники — без DOM, покрыты тестами в frontend/tests.

const STATUS_LABELS = {
  scheduled: 'Запланирован',
  completed: 'Состоялся',
  cancelled: 'Отменён',
  no_show: 'Неявка',
};

const RISK_LABELS = { low: 'Низкий', medium: 'Средний', high: 'Высокий' };

const EXAMINATION_NUMBERS = ['height', 'weight', 'ap_hi', 'ap_lo', 'cholesterol', 'gluc'];
const EXAMINATION_FLAGS = ['smoke', 'alco', 'active'];

export const statusLabel = (status) => STATUS_LABELS[status] ?? status;
export const riskLabel = (level) => RISK_LABELS[level] ?? level;

/** Строка запроса из объекта; пустые значения пропускаются. */
export function buildQuery(params) {
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') query.set(name, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : '';
}

/**
 * Тело запроса для пациента. При создании пустой телефон не отправляем,
 * при обновлении отправляем null, чтобы телефон можно было очистить.
 */
export function buildPatientPayload(entries, { forUpdate = false } = {}) {
  const payload = {};
  for (const [name, rawValue] of entries) {
    const value = String(rawValue).trim();
    if (value === '') {
      if (name === 'phone' && forUpdate) payload.phone = null;
      continue;
    }
    payload[name] = value;
  }
  return payload;
}

/** Тело запроса медосмотра: числа — числами, неотмеченные чекбоксы — false. */
export function buildExaminationPayload(entries) {
  const values = new Map(entries);
  const payload = {};
  for (const name of EXAMINATION_NUMBERS) payload[name] = Number(values.get(name));
  for (const name of EXAMINATION_FLAGS) payload[name] = values.has(name);
  return payload;
}

/** Значение datetime-local («2026-11-10T10:00», местное время) в ISO-строку UTC. */
export function localInputToUtcIso(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) throw new Error('Укажите дату и время приёма');
  return date.toISOString();
}

/** Сервер отдаёт время UTC без часового пояса; показываем его в местном времени. */
export function utcToLocalLabel(naiveUtc, timeZone) {
  const date = new Date(`${naiveUtc}Z`);
  return date.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short', timeZone });
}

/** Какие операции доступны для приёма: менять статус можно только у запланированного. */
export function availableActions(appointment) {
  return appointment.status === 'scheduled' ? ['cancel', 'complete', 'no-show'] : [];
}

export function pageInfo({ total, limit, offset }) {
  if (total === 0) return { from: 0, to: 0, hasPrev: false, hasNext: false };
  return {
    from: offset + 1,
    to: Math.min(offset + limit, total),
    hasPrev: offset > 0,
    hasNext: offset + limit < total,
  };
}

/** Столбики динамики риска: ширина — средний риск (0..1). */
export function riskBars(points) {
  return points.map((point) => ({
    label: point.period,
    value: point.avg_risk,
    caption: `${point.examinations} осм., высокий риск у ${(point.high_risk_share * 100).toFixed(0)}%`,
  }));
}
