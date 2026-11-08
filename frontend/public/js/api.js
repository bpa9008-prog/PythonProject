import { describeError, uploadHeaders } from './format.js';

// По умолчанию фронтенд раздаётся тем же FastAPI, поэтому API на том же origin.
const API_BASE = window.API_BASE ?? '';

export class ApiError extends Error {}

export async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch {
    throw new ApiError('Сервис недоступен');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(describeError(body, `HTTP ${response.status}`));
  }
  return response;
}

function formWithFile(file) {
  const data = new FormData();
  data.append('file', file);
  return data;
}

export async function getModelInfo() {
  return (await request('/model-info')).json();
}

export async function predict(record) {
  const response = await request('/predict', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ records: [record] }),
  });
  return (await response.json()).predictions[0];
}

export async function predictCsv(file) {
  return (await request('/predict-from-csv', { method: 'POST', body: formWithFile(file) })).json();
}

export async function predictCsvFile(file) {
  const response = await request('/predict-from-csv?output=csv', {
    method: 'POST',
    body: formWithFile(file),
  });
  return response.blob();
}

export async function uploadModel(file, token) {
  const options = { method: 'POST', headers: uploadHeaders(token), body: formWithFile(file) };
  return (await request('/upload-model', options)).json();
}
