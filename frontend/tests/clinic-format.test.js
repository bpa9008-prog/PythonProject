import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  availableActions,
  buildExaminationPayload,
  buildPatientPayload,
  buildQuery,
  localInputToUtcIso,
  pageInfo,
  riskBars,
  riskLabel,
  statusLabel,
  utcToLocalLabel,
} from '../public/js/clinic-format.js';

describe('buildQuery', () => {
  it('skips empty values and encodes the rest', () => {
    assert.equal(
      buildQuery({ search: 'иван', status: '', offset: 0, gender: undefined }),
      '?search=%D0%B8%D0%B2%D0%B0%D0%BD&offset=0',
    );
  });

  it('returns an empty string when there is nothing to send', () => {
    assert.equal(buildQuery({ a: '', b: null }), '');
  });
});

describe('buildPatientPayload', () => {
  const entries = [
    ['full_name', ' Иванов Иван '],
    ['gender', 'M'],
    ['phone', ''],
  ];

  it('omits an empty phone when creating', () => {
    assert.deepEqual(buildPatientPayload(entries), { full_name: 'Иванов Иван', gender: 'M' });
  });

  it('sends null for an empty phone when updating so it can be cleared', () => {
    assert.deepEqual(buildPatientPayload(entries, { forUpdate: true }), {
      full_name: 'Иванов Иван',
      gender: 'M',
      phone: null,
    });
  });
});

describe('buildExaminationPayload', () => {
  it('converts numbers and turns unchecked checkboxes into false', () => {
    const payload = buildExaminationPayload([
      ['height', '172'],
      ['weight', '84.5'],
      ['ap_hi', '145'],
      ['ap_lo', '92'],
      ['cholesterol', '2'],
      ['gluc', '1'],
      ['smoke', 'on'],
    ]);
    assert.deepEqual(payload, {
      height: 172,
      weight: 84.5,
      ap_hi: 145,
      ap_lo: 92,
      cholesterol: 2,
      gluc: 1,
      smoke: true,
      alco: false,
      active: false,
    });
  });
});

describe('time helpers', () => {
  it('converts a local datetime input to a UTC ISO string', () => {
    const iso = localInputToUtcIso('2026-11-10T10:00');
    assert.equal(new Date(iso).getTime(), new Date('2026-11-10T10:00').getTime());
    assert.match(iso, /Z$/);
  });

  it('rejects an empty datetime', () => {
    assert.throws(() => localInputToUtcIso(''), /дату и время/);
  });

  it('shows server UTC time in the requested time zone', () => {
    assert.equal(utcToLocalLabel('2026-11-10T10:00:00', 'UTC'), '10.11.2026, 10:00');
    assert.equal(utcToLocalLabel('2026-11-10T10:00:00', 'Europe/Moscow'), '10.11.2026, 13:00');
  });
});

describe('labels and actions', () => {
  it('translates known statuses and falls back to the raw value', () => {
    assert.equal(statusLabel('no_show'), 'Неявка');
    assert.equal(statusLabel('weird'), 'weird');
    assert.equal(riskLabel('high'), 'Высокий');
  });

  it('allows status changes only for scheduled appointments', () => {
    assert.deepEqual(availableActions({ status: 'scheduled' }), ['cancel', 'complete', 'no-show']);
    assert.deepEqual(availableActions({ status: 'completed' }), []);
    assert.deepEqual(availableActions({ status: 'cancelled' }), []);
  });
});

describe('pageInfo', () => {
  it('describes the middle page', () => {
    assert.deepEqual(pageInfo({ total: 25, limit: 10, offset: 10 }), {
      from: 11,
      to: 20,
      hasPrev: true,
      hasNext: true,
    });
  });

  it('describes the last page and an empty list', () => {
    assert.deepEqual(pageInfo({ total: 25, limit: 10, offset: 20 }), {
      from: 21,
      to: 25,
      hasPrev: true,
      hasNext: false,
    });
    assert.deepEqual(pageInfo({ total: 0, limit: 10, offset: 0 }), {
      from: 0,
      to: 0,
      hasPrev: false,
      hasNext: false,
    });
  });
});

describe('riskBars', () => {
  it('builds bars with a readable caption', () => {
    const bars = riskBars([
      { period: '2026', avg_risk: 0.5, examinations: 4, high_risk_share: 0.25 },
    ]);
    assert.deepEqual(bars, [{ label: '2026', value: 0.5, caption: '4 осм., высокий риск у 25%' }]);
  });
});
