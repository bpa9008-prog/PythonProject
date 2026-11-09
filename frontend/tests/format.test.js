import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  buildRecord,
  describeError,
  formatPercent,
  metricsBars,
  previewTable,
  uploadHeaders,
} from '../public/js/format.js';

describe('buildRecord', () => {
  it('converts fields to numbers', () => {
    const record = buildRecord([
      ['weight', '62.5'],
      ['ap_hi', '120'],
      ['cholesterol', '2'],
    ]);
    assert.deepEqual(record, { weight: 62.5, ap_hi: 120, cholesterol: 2 });
  });

  it('converts age from years to days', () => {
    assert.deepEqual(buildRecord([['age_years', '50']]), { age: 18263 });
  });

  it('omits empty fields', () => {
    assert.deepEqual(buildRecord([['height', '  ']]), {});
  });
});

describe('formatPercent', () => {
  it('formats probability with one decimal', () => {
    assert.equal(formatPercent(0.6741), '67.4%');
  });
});

describe('describeError', () => {
  it('returns string detail as is', () => {
    assert.equal(describeError({ detail: 'Модель не загружена' }), 'Модель не загружена');
  });

  it('joins validation errors', () => {
    const body = {
      detail: [
        { field: 'body.records.0.ap_hi', message: 'Input should be less than or equal to 300' },
        { field: 'body.records.0.gluc', message: 'Input should be 1, 2 or 3' },
      ],
    };
    assert.equal(
      describeError(body),
      'body.records.0.ap_hi: Input should be less than or equal to 300; body.records.0.gluc: Input should be 1, 2 or 3',
    );
  });

  it('falls back when body is not JSON', () => {
    assert.equal(describeError(null, 'HTTP 500'), 'HTTP 500');
  });
});

describe('previewTable', () => {
  it('limits rows and replaces nulls with empty strings', () => {
    const records = [
      { a: 1, b: null },
      { a: 2, b: 'x' },
      { a: 3, b: 'y' },
    ];
    assert.deepEqual(previewTable(records, 2), {
      columns: ['a', 'b'],
      rows: [
        [1, ''],
        [2, 'x'],
      ],
    });
  });

  it('handles empty input', () => {
    assert.deepEqual(previewTable([]), { columns: [], rows: [] });
  });
});

describe('metricsBars', () => {
  it('sorts models by test ROC-AUC and marks the best', () => {
    const bars = metricsBars({
      best_model: 'gb',
      models: { lr: { test_roc_auc: 0.86 }, gb: { test_roc_auc: 0.94 } },
    });
    assert.deepEqual(bars, [
      { name: 'gb', value: 0.94, best: true },
      { name: 'lr', value: 0.86, best: false },
    ]);
  });

  it('returns empty list without metrics', () => {
    assert.deepEqual(metricsBars(null), []);
  });
});

describe('uploadHeaders', () => {
  it('sends the token header only when a token is entered', () => {
    assert.deepEqual(uploadHeaders(' s3cret '), { 'X-Upload-Token': 's3cret' });
  });

  it('sends no extra headers for an empty or missing token', () => {
    assert.deepEqual(uploadHeaders(''), {});
    assert.deepEqual(uploadHeaders('   '), {});
    assert.deepEqual(uploadHeaders(undefined), {});
  });
});
