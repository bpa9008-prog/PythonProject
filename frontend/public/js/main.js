import * as api from './api.js';
import { $, el, show, showError, withBusy } from './dom.js';
import { buildRecord, formatPercent, metricsBars, previewTable } from './format.js';

function renderModelStatus(info) {
  const status = $('#model-status');
  status.className = `status status--${info.loaded ? 'ok' : 'missing'}`;
  status.textContent = info.loaded
    ? `Модель загружена: ${info.model_type}`
    : 'Модель не загружена — загрузите pkl в разделе «Модель»';
}

function renderMetrics(metrics) {
  const bars = metricsBars(metrics);
  if (!bars.length) {
    $('#metrics').replaceChildren();
    return;
  }
  const rows = bars.map(({ name, value, best }) =>
    el('div', { className: `bar${best ? ' bar--best' : ''}` }, [
      el('span', { className: 'bar__label', textContent: name }),
      el('span', { className: 'bar__track' }, [
        el('span', { className: 'bar__fill', style: `width: ${value * 100}%` }),
      ]),
      el('span', { className: 'bar__value', textContent: value.toFixed(4) }),
    ]),
  );
  $('#metrics').replaceChildren(
    el('h3', { textContent: 'ROC-AUC на тестовой выборке' }),
    ...rows,
    el('p', {
      className: 'hint',
      textContent: `Признаки модели: ${metrics.features.join(', ')}`,
    }),
  );
}

async function refreshModelInfo() {
  try {
    const info = await api.getModelInfo();
    renderModelStatus(info);
    renderMetrics(info.metrics);
  } catch (error) {
    $('#model-status').textContent = error.message;
  }
}

function renderPrediction(prediction) {
  const lowRisk = prediction.cardio === 'low_risk';
  show(
    $('#predict-result'),
    el('p', {
      className: `verdict verdict--${lowRisk ? 'ok' : 'bad'}`,
      textContent: lowRisk ? 'Низкий риск сердечно-сосудистого заболевания' : 'Высокий риск',
    }),
    el('p', {
      textContent: `Вероятность заболевания: ${formatPercent(prediction.risk_probability)}`,
    }),
    el('p', {
      className: 'hint',
      textContent: 'Это оценка учебной модели, а не медицинский диагноз.',
    }),
  );
}

function renderTable({ columns, rows }) {
  return el('div', { className: 'table-wrap' }, [
    el('table', {}, [
      el('thead', {}, [
        el(
          'tr',
          {},
          columns.map((c) => el('th', { textContent: c })),
        ),
      ]),
      el(
        'tbody',
        {},
        rows.map((row) =>
          el(
            'tr',
            {},
            row.map((v) => el('td', { textContent: String(v) })),
          ),
        ),
      ),
    ]),
  ]);
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  el('a', { href: url, download: filename }).click();
  URL.revokeObjectURL(url);
}

function renderCsvResult(result, file) {
  const auc = result.roc_auc === null ? 'не рассчитан (нет колонки cardio)' : result.roc_auc;
  const download = el('button', { type: 'button', textContent: 'Скачать CSV с предсказаниями' });
  download.addEventListener('click', async () => {
    try {
      downloadBlob(await api.predictCsvFile(file), 'predictions.csv');
    } catch (error) {
      showError($('#csv-result'), error);
    }
  });
  show(
    $('#csv-result'),
    el('p', {
      textContent: `Строк: ${result.rows} · формат: ${result.input_format} · ROC-AUC: ${auc}`,
    }),
    download,
    renderTable(previewTable(result.records)),
    el('p', { className: 'hint', textContent: 'Показаны первые 20 строк' }),
  );
}

$('#predict-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  withBusy(form, async () => {
    try {
      renderPrediction(await api.predict(buildRecord(new FormData(form).entries())));
    } catch (error) {
      showError($('#predict-result'), error);
    }
  });
});

$('#csv-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const file = form.elements.file.files[0];
  withBusy(form, async () => {
    try {
      renderCsvResult(await api.predictCsv(file), file);
    } catch (error) {
      showError($('#csv-result'), error);
    }
  });
});

$('#upload-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  withBusy(form, async () => {
    const result = $('#upload-result');
    try {
      const response = await api.uploadModel(form.elements.file.files[0]);
      result.className = 'result';
      result.textContent = response.message;
      result.hidden = false;
      await refreshModelInfo();
    } catch (error) {
      result.className = 'result error';
      result.textContent = error.message;
      result.hidden = false;
    }
  });
});

refreshModelInfo();
