import { request } from './api.js';
import { buildQuery } from './clinic-format.js';

const JSON_HEADERS = { 'Content-Type': 'application/json' };

async function json(path, options) {
  return (await request(path, options)).json();
}

function send(method, path, body) {
  return json(path, {
    method,
    headers: JSON_HEADERS,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export const listPatients = (params) => json(`/patients${buildQuery(params)}`);
export const getPatient = (id) => json(`/patients/${id}`);
export const createPatient = (payload) => send('POST', '/patients', payload);
export const updatePatient = (id, payload) => send('PATCH', `/patients/${id}`, payload);
export const deletePatient = (id) => request(`/patients/${id}`, { method: 'DELETE' });

export const listDoctors = (params) => json(`/doctors${buildQuery(params)}`);
export const listDiagnoses = (params) => json(`/diagnoses${buildQuery(params)}`);

export const listAppointments = (params) => json(`/appointments${buildQuery(params)}`);
export const bookAppointment = (payload) => send('POST', '/appointments', payload);
export const cancelAppointment = (id) => send('POST', `/appointments/${id}/cancel`);
export const markNoShow = (id) => send('POST', `/appointments/${id}/no-show`);
export const completeAppointment = (id, diagnosisIds) =>
  send('POST', `/appointments/${id}/complete`, { diagnosis_ids: diagnosisIds });

export const createExamination = (patientId, payload) =>
  send('POST', `/patients/${patientId}/examinations`, payload);

export const doctorWorkload = () => json('/analytics/doctor-workload');
export const riskDynamics = (params) => json(`/analytics/risk-dynamics${buildQuery(params)}`);
export const riskFollowup = (params) => json(`/analytics/risk-followup${buildQuery(params)}`);
