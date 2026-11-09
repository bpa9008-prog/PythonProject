import * as api from './clinic-api.js';
import {
  availableActions,
  buildExaminationPayload,
  buildPatientPayload,
  localInputToUtcIso,
  pageInfo,
  riskBars,
  riskLabel,
  statusLabel,
  utcToLocalLabel,
} from './clinic-format.js';
import { $, clear, debounce, el, show, showError, withBusy } from './dom.js';
import { formatPercent } from './format.js';

const PATIENTS_PAGE_SIZE = 8;
const APPOINTMENTS_PAGE_SIZE = 8;

const state = {
  patients: { offset: 0, search: '' },
  appointments: { offset: 0, status: '' },
  editingPatientId: null,
  doctors: new Map(),
  patientNames: new Map(),
};

const patientName = (id) => state.patientNames.get(id) ?? `Пациент #${id}`;
const doctorName = (id) => state.doctors.get(id)?.full_name ?? `Врач #${id}`;

function button(text, onClick, className = 'button--small') {
  const node = el('button', { type: 'button', textContent: text, className });
  node.addEventListener('click', onClick);
  return node;
}

function table(columns, rows) {
  return el('div', { className: 'table-wrap' }, [
    el('table', {}, [
      el('thead', {}, [
        el(
          'tr',
          {},
          columns.map((c) => el('th', { textContent: c })),
        ),
      ]),
      el('tbody', {}, rows),
    ]),
  ]);
}

function row(...cells) {
  return el(
    'tr',
    {},
    cells.map((cell) =>
      el('td', {}, [cell instanceof Node ? cell : document.createTextNode(cell)]),
    ),
  );
}

function renderPager(container, page, onPage) {
  const info = pageInfo(page);
  container.replaceChildren(
    el('span', { className: 'hint', textContent: `${info.from}–${info.to} из ${page.total}` }),
    button('←', () => onPage(page.offset - page.limit)),
    button('→', () => onPage(page.offset + page.limit)),
  );
  const [, prev, next] = container.children;
  prev.disabled = !info.hasPrev;
  next.disabled = !info.hasNext;
}

// --- Пациенты ---------------------------------------------------------------

function fillPatientForm(patient) {
  const form = $('#patient-form');
  state.editingPatientId = patient?.id ?? null;
  form.full_name.value = patient?.full_name ?? '';
  form.birth_date.value = patient?.birth_date ?? '';
  form.gender.value = patient?.gender ?? 'M';
  form.phone.value = patient?.phone ?? '';
  $('#patient-form-title').textContent = patient
    ? `Изменить пациента #${patient.id}`
    : 'Новый пациент';
  $('#patient-form button[type=submit]').textContent = patient ? 'Сохранить' : 'Создать';
  $('#patient-cancel').hidden = !patient;
}

async function loadPatients() {
  const page = await api.listPatients({
    limit: PATIENTS_PAGE_SIZE,
    offset: state.patients.offset,
    search: state.patients.search,
  });
  for (const patient of page.items) state.patientNames.set(patient.id, patient.full_name);
  const rows = page.items.map((patient) =>
    row(
      String(patient.id),
      patient.full_name,
      patient.birth_date,
      patient.gender === 'F' ? 'Ж' : 'М',
      patient.phone ?? '—',
      el('span', { className: 'actions' }, [
        button('Изменить', () => fillPatientForm(patient)),
        button('Удалить', () => removePatient(patient)),
      ]),
    ),
  );
  $('#patients-table').replaceChildren(table(['ID', 'ФИО', 'Родился', 'Пол', 'Телефон', ''], rows));
  renderPager($('#patients-pager'), page, (offset) => {
    state.patients.offset = Math.max(0, offset);
    loadPatients().catch((error) => showError($('#patients-error'), error));
  });
}

async function removePatient(patient) {
  if (!window.confirm(`Удалить пациента «${patient.full_name}»?`)) return;
  try {
    await api.deletePatient(patient.id);
    clear($('#patients-error'));
    await loadPatients();
  } catch (error) {
    showError($('#patients-error'), error);
  }
}

$('#patient-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  withBusy(form, async () => {
    try {
      const entries = new FormData(form).entries();
      if (state.editingPatientId === null) {
        await api.createPatient(buildPatientPayload(entries));
      } else {
        await api.updatePatient(
          state.editingPatientId,
          buildPatientPayload(entries, { forUpdate: true }),
        );
      }
      clear($('#patients-error'));
      fillPatientForm(null);
      await loadPatients();
    } catch (error) {
      showError($('#patients-error'), error);
    }
  });
});

$('#patient-cancel').addEventListener('click', () => fillPatientForm(null));

$('#patient-search').addEventListener(
  'input',
  debounce((event) => {
    state.patients = { offset: 0, search: event.target.value.trim() };
    loadPatients().catch((error) => showError($('#patients-error'), error));
  }, 300),
);

// --- Выбор пациента по поиску (в списке десятки тысяч записей) ---------------

function setupPatientPicker(searchInput, select) {
  const refresh = async () => {
    const page = await api.listPatients({ limit: 20, search: searchInput.value.trim() });
    for (const patient of page.items) state.patientNames.set(patient.id, patient.full_name);
    select.replaceChildren(
      ...page.items.map((p) =>
        el('option', { value: p.id, textContent: `${p.full_name} (#${p.id})` }),
      ),
    );
  };
  searchInput.addEventListener(
    'input',
    debounce(() => refresh().catch(() => {}), 300),
  );
  return refresh;
}

// --- Запись на приём --------------------------------------------------------

async function loadDoctors() {
  const page = await api.listDoctors({ limit: 100, is_active: true });
  state.doctors = new Map(page.items.map((doctor) => [doctor.id, doctor]));
  $('#booking-doctor').replaceChildren(
    ...page.items.map((d) =>
      el('option', { value: d.id, textContent: `${d.full_name} — ${d.specialty}` }),
    ),
  );
}

async function loadDiagnoses() {
  const page = await api.listDiagnoses({ limit: 100 });
  $('#complete-diagnosis').replaceChildren(
    el('option', { value: '', textContent: 'без диагноза' }),
    ...page.items.map((d) =>
      el('option', { value: d.id, textContent: `${d.icd_code} — ${d.name}` }),
    ),
  );
}

$('#booking-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  withBusy(form, async () => {
    const result = $('#booking-result');
    try {
      const appointment = await api.bookAppointment({
        patient_id: Number(form.patient_id.value),
        doctor_id: Number(form.doctor_id.value),
        scheduled_at: localInputToUtcIso(form.scheduled_at.value),
        duration_minutes: Number(form.duration_minutes.value),
        reason: form.reason.value.trim() || null,
      });
      show(
        result,
        el('p', {
          className: 'verdict verdict--ok',
          textContent: `Запись создана: ${utcToLocalLabel(appointment.scheduled_at)}, приём #${appointment.id}`,
        }),
      );
      await Promise.all([loadAppointments(), loadAnalytics()]);
    } catch (error) {
      showError(result, error);
    }
  });
});

// --- Список приёмов и смена статуса -----------------------------------------

async function loadAppointments() {
  const page = await api.listAppointments({
    limit: APPOINTMENTS_PAGE_SIZE,
    offset: state.appointments.offset,
    status: state.appointments.status,
    sort_by: 'scheduled_at',
    order: 'desc',
  });
  const unknown = [...new Set(page.items.map((a) => a.patient_id))].filter(
    (id) => !state.patientNames.has(id),
  );
  await Promise.all(
    unknown.map(async (id) => {
      const patient = await api.getPatient(id);
      state.patientNames.set(id, patient.full_name);
    }),
  );

  const rows = page.items.map((appointment) =>
    row(
      String(appointment.id),
      patientName(appointment.patient_id),
      doctorName(appointment.doctor_id),
      utcToLocalLabel(appointment.scheduled_at),
      statusLabel(appointment.status),
      appointment.diagnoses.map((d) => d.icd_code).join(', ') || '—',
      el(
        'span',
        { className: 'actions' },
        availableActions(appointment).map((action) =>
          button({ cancel: 'Отменить', complete: 'Завершить', 'no-show': 'Неявка' }[action], () =>
            changeStatus(appointment, action),
          ),
        ),
      ),
    ),
  );
  $('#appointments-table').replaceChildren(
    table(['ID', 'Пациент', 'Врач', 'Время', 'Статус', 'Диагнозы', ''], rows),
  );
  renderPager($('#appointments-pager'), page, (offset) => {
    state.appointments.offset = Math.max(0, offset);
    loadAppointments().catch((error) => showError($('#appointments-error'), error));
  });
}

async function changeStatus(appointment, action) {
  try {
    if (action === 'cancel') await api.cancelAppointment(appointment.id);
    if (action === 'no-show') await api.markNoShow(appointment.id);
    if (action === 'complete') {
      const diagnosisId = $('#complete-diagnosis').value;
      await api.completeAppointment(appointment.id, diagnosisId ? [Number(diagnosisId)] : []);
    }
    clear($('#appointments-error'));
    await Promise.all([loadAppointments(), loadAnalytics()]);
  } catch (error) {
    showError($('#appointments-error'), error);
  }
}

$('#appointments-status').addEventListener('change', (event) => {
  state.appointments = { offset: 0, status: event.target.value };
  loadAppointments().catch((error) => showError($('#appointments-error'), error));
});

// --- Медосмотр и оценка риска -----------------------------------------------

$('#examination-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  withBusy(form, async () => {
    const result = $('#examination-result');
    try {
      const examination = await api.createExamination(
        Number(form.patient_id.value),
        buildExaminationPayload(new FormData(form).entries()),
      );
      const high = examination.risk_level === 'high';
      show(
        result,
        el('p', {
          className: `verdict verdict--${high ? 'bad' : 'ok'}`,
          textContent: `Риск: ${riskLabel(examination.risk_level)} (${formatPercent(examination.risk_probability)})`,
        }),
        el('p', {
          className: 'hint',
          textContent: 'Оценка учебной модели, не медицинский диагноз.',
        }),
      );
      await loadAnalytics();
    } catch (error) {
      showError(result, error);
    }
  });
});

// --- Аналитика --------------------------------------------------------------

async function loadAnalytics() {
  const [workload, dynamics, followup] = await Promise.all([
    api.doctorWorkload(),
    api.riskDynamics({ period: 'year' }),
    api.riskFollowup({ limit: 5 }),
  ]);

  $('#workload').replaceChildren(
    table(
      ['Врач', 'Всего', 'Запл.', 'Состоялось', 'Отмены', 'Неявки', 'Явка'],
      workload.map((w) =>
        row(
          w.full_name,
          String(w.total),
          String(w.scheduled),
          String(w.completed),
          String(w.cancelled),
          String(w.no_show),
          w.completion_rate === null ? '—' : formatPercent(w.completion_rate),
        ),
      ),
    ),
  );

  $('#risk-dynamics').replaceChildren(
    ...riskBars(dynamics).map((bar) =>
      el('div', { className: 'bar' }, [
        el('span', { className: 'bar__label', textContent: bar.label }),
        el('span', { className: 'bar__track' }, [
          el('span', { className: 'bar__fill', style: `width: ${bar.value * 100}%` }),
        ]),
        el('span', { className: 'bar__value', textContent: formatPercent(bar.value) }),
        el('span', { className: 'hint bar__caption', textContent: bar.caption }),
      ]),
    ),
  );

  $('#followup').replaceChildren(
    el('h3', { textContent: `Высокий риск без приёма после осмотра: ${followup.total}` }),
    table(
      ['Пациент', 'Осмотр', 'Риск'],
      followup.items.map((p) =>
        row(p.full_name, utcToLocalLabel(p.measured_at), formatPercent(p.risk_probability)),
      ),
    ),
  );
}

// --- Старт ------------------------------------------------------------------

async function init() {
  const bookingPicker = setupPatientPicker($('#booking-patient-search'), $('#booking-patient'));
  const examinationPicker = setupPatientPicker(
    $('#examination-patient-search'),
    $('#examination-patient'),
  );
  try {
    await Promise.all([loadDoctors(), loadDiagnoses(), bookingPicker(), examinationPicker()]);
    await Promise.all([loadPatients(), loadAppointments(), loadAnalytics()]);
  } catch (error) {
    showError($('#global-error'), error);
  }
}

fillPatientForm(null);
init();
