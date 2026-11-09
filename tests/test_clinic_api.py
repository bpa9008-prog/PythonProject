"""Интеграционные тесты REST API клиники (TestClient, БД SQLite в памяти, фиксированные часы)."""

from datetime import datetime, timedelta

import pytest

TOMORROW_10 = "2026-11-10T10:00:00Z"  # «сейчас» в тестах — 2026-11-09 09:00 UTC

HEALTHY = {"height": 175, "weight": 70, "ap_hi": 105, "ap_lo": 70, "cholesterol": 1, "gluc": 1}
SICK = {"height": 170, "weight": 95, "ap_hi": 178, "ap_lo": 105, "cholesterol": 3, "gluc": 2, "smoke": True}


def make_patient(client, **overrides) -> dict:
    payload = {"full_name": "Иванов Иван", "birth_date": "1970-05-20", "gender": "M", **overrides}
    response = client.post("/patients", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_doctor(client, **overrides) -> dict:
    payload = {"full_name": "Петров Пётр", "specialty": "Кардиолог", "license_number": "MD-0001", **overrides}
    response = client.post("/doctors", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_diagnosis(client, code="I10", name="Гипертензия") -> dict:
    response = client.post("/diagnoses", json={"icd_code": code, "name": name})
    assert response.status_code == 201, response.text
    return response.json()


def book(client, patient, doctor, at=TOMORROW_10, **overrides):
    payload = {"patient_id": patient["id"], "doctor_id": doctor["id"], "scheduled_at": at, **overrides}
    return client.post("/appointments", json=payload)


@pytest.fixture
def patient(client):
    return make_patient(client)


@pytest.fixture
def doctor(client):
    return make_doctor(client)


# --- Пациенты ---------------------------------------------------------------


def test_create_patient_returns_201_and_entity(client):
    response = client.post(
        "/patients",
        json={"full_name": "Сидорова Анна", "birth_date": "1980-01-02", "gender": "F", "phone": "+79991112233"},
    )

    body = response.json()
    assert response.status_code == 201
    assert body["id"] > 0
    assert body["external_id"] is None
    assert body["phone"] == "+79991112233"


def test_create_patient_validation_errors_use_unified_format(client):
    response = client.post("/patients", json={"full_name": "A", "birth_date": "2999-01-01", "gender": "X"})

    body = response.json()
    fields = {error["field"] for error in body["detail"]}
    assert response.status_code == 422
    assert body["status"] == "error"
    assert {"body.full_name", "body.birth_date", "body.gender"} <= fields


def test_create_patient_duplicate_phone_returns_409(client):
    make_patient(client, phone="+79990001122")

    response = client.post(
        "/patients", json={"full_name": "Другой", "birth_date": "1990-01-01", "gender": "M", "phone": "+79990001122"}
    )

    assert response.status_code == 409
    assert "телефон" in response.json()["detail"]


def test_get_unknown_patient_returns_404(client):
    response = client.get("/patients/999")

    assert response.status_code == 404
    assert response.json() == {"status": "error", "detail": "Пациент с id=999 не найден"}


def test_patch_patient_updates_only_given_fields(client, patient):
    response = client.patch(f"/patients/{patient['id']}", json={"full_name": "Иванов Иван Петрович"})

    body = response.json()
    assert response.status_code == 200
    assert body["full_name"] == "Иванов Иван Петрович"
    assert body["birth_date"] == patient["birth_date"]


def test_patch_patient_cannot_take_foreign_phone(client, patient):
    make_patient(client, full_name="Второй пациент", phone="+79990002233")

    response = client.patch(f"/patients/{patient['id']}", json={"phone": "+79990002233"})

    assert response.status_code == 409


def test_list_patients_paginates_filters_and_sorts(client):
    for name, gender in [("Андреев А", "M"), ("Борисова Б", "F"), ("Васильев В", "M"), ("Громова Г", "F")]:
        make_patient(client, full_name=name, gender=gender)

    first_page = client.get("/patients", params={"limit": 2, "offset": 0}).json()
    second_page = client.get("/patients", params={"limit": 2, "offset": 2}).json()
    women = client.get("/patients", params={"gender": "F", "sort_by": "full_name", "order": "desc"}).json()
    search = client.get("/patients", params={"search": "асиль"}).json()

    assert first_page["total"] == 4
    assert [p["full_name"] for p in first_page["items"]] == ["Андреев А", "Борисова Б"]
    assert [p["full_name"] for p in second_page["items"]] == ["Васильев В", "Громова Г"]
    assert [p["full_name"] for p in women["items"]] == ["Громова Г", "Борисова Б"]
    assert [p["full_name"] for p in search["items"]] == ["Васильев В"]


def test_list_patients_rejects_bad_query_params(client):
    assert client.get("/patients", params={"limit": 0}).status_code == 422
    assert client.get("/patients", params={"sort_by": "password"}).status_code == 422


def test_delete_patient_returns_204_then_404(client, patient):
    assert client.delete(f"/patients/{patient['id']}").status_code == 204
    assert client.get(f"/patients/{patient['id']}").status_code == 404


def test_delete_patient_with_appointments_is_forbidden(client, patient, doctor):
    assert book(client, patient, doctor).status_code == 201

    response = client.delete(f"/patients/{patient['id']}")

    assert response.status_code == 409
    assert client.get(f"/patients/{patient['id']}").status_code == 200


# --- Врачи и справочник -----------------------------------------------------


def test_doctor_license_must_be_unique(client, doctor):
    response = client.post(
        "/doctors", json={"full_name": "Другой Врач", "specialty": "Терапевт", "license_number": "MD-0001"}
    )

    assert response.status_code == 409


def test_list_doctors_filters_by_specialty_and_activity(client, doctor):
    therapist = make_doctor(client, full_name="Орлова", specialty="Терапевт", license_number="MD-0002")
    client.patch(f"/doctors/{therapist['id']}", json={"is_active": False})

    cardiologists = client.get("/doctors", params={"specialty": "Кардиолог"}).json()
    inactive = client.get("/doctors", params={"is_active": False}).json()

    assert [d["id"] for d in cardiologists["items"]] == [doctor["id"]]
    assert [d["id"] for d in inactive["items"]] == [therapist["id"]]


def test_diagnosis_catalog_rejects_duplicates_and_bad_codes(client):
    make_diagnosis(client, "I10")

    assert client.post("/diagnoses", json={"icd_code": "I10", "name": "Дубль"}).status_code == 409
    assert client.post("/diagnoses", json={"icd_code": "hypertension", "name": "Не код"}).status_code == 422
    assert client.get("/diagnoses", params={"search": "i1"}).json()["total"] == 1


# --- Запись на приём --------------------------------------------------------


def test_book_appointment_returns_201_with_end_time(client, patient, doctor):
    response = book(client, patient, doctor, duration_minutes=45, reason="Контроль давления")

    body = response.json()
    assert response.status_code == 201
    assert body["status"] == "scheduled"
    assert body["scheduled_at"] == "2026-11-10T10:00:00"
    assert body["ends_at"] == "2026-11-10T10:45:00"
    assert body["diagnoses"] == []


def test_book_appointment_accepts_timezone_offset(client, patient, doctor):
    response = book(client, patient, doctor, at="2026-11-10T13:00:00+03:00")

    assert response.json()["scheduled_at"] == "2026-11-10T10:00:00"


def test_book_in_the_past_is_rejected(client, patient, doctor):
    response = book(client, patient, doctor, at="2026-11-09T08:00:00Z")

    assert response.status_code == 422
    assert "прошедшее" in response.json()["detail"]


@pytest.mark.parametrize("at", ["2026-11-10T07:30:00Z", "2026-11-10T19:45:00Z", "2026-11-10T23:00:00Z"])
def test_book_outside_working_hours_is_rejected(client, patient, doctor, at):
    response = book(client, patient, doctor, at=at, duration_minutes=30)

    assert response.status_code == 422
    assert "Клиника принимает" in response.json()["detail"]


def test_book_busy_doctor_returns_409(client, patient, doctor):
    other_patient = make_patient(client, full_name="Второй пациент")
    assert book(client, patient, doctor).status_code == 201

    overlapping = book(client, other_patient, doctor, at="2026-11-10T10:15:00Z")
    adjacent = book(client, other_patient, doctor, at="2026-11-10T10:30:00Z")

    assert overlapping.status_code == 409
    assert "Врач занят" in overlapping.json()["detail"]
    assert adjacent.status_code == 201  # приём заканчивается ровно в момент начала следующего


def test_book_busy_patient_returns_409(client, patient, doctor):
    second_doctor = make_doctor(client, full_name="Орлова", license_number="MD-0002")
    assert book(client, patient, doctor).status_code == 201

    response = book(client, patient, second_doctor, at="2026-11-10T10:10:00Z")

    assert response.status_code == 409
    assert "пациента" in response.json()["detail"]


def test_book_with_inactive_doctor_returns_409(client, patient, doctor):
    client.patch(f"/doctors/{doctor['id']}", json={"is_active": False})

    assert book(client, patient, doctor).status_code == 409


def test_book_with_unknown_patient_or_doctor_returns_404(client, patient, doctor):
    assert book(client, {"id": 999}, doctor).status_code == 404
    assert book(client, patient, {"id": 999}).status_code == 404


def test_book_validates_duration(client, patient, doctor):
    assert book(client, patient, doctor, duration_minutes=10).status_code == 422
    assert book(client, patient, doctor, duration_minutes=33).status_code == 422


# --- Статусы приёма ---------------------------------------------------------


def test_cancel_frees_the_slot_for_rebooking(client, patient, doctor):
    appointment = book(client, patient, doctor).json()

    cancelled = client.post(f"/appointments/{appointment['id']}/cancel")
    rebooked = book(client, make_patient(client, full_name="Второй пациент"), doctor)

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert rebooked.status_code == 201


def test_cancel_less_than_two_hours_before_start_is_rejected(client, clock, patient, doctor):
    appointment = book(client, patient, doctor).json()
    clock.value = datetime(2026, 11, 10, 8, 30)

    response = client.post(f"/appointments/{appointment['id']}/cancel")

    assert response.status_code == 409
    assert "не позднее чем за 2 ч" in response.json()["detail"]


def test_finished_appointment_cannot_change_status_again(client, clock, patient, doctor):
    appointment = book(client, patient, doctor).json()
    clock.value = datetime(2026, 11, 10, 10, 5)
    assert client.post(f"/appointments/{appointment['id']}/complete").status_code == 200

    assert client.post(f"/appointments/{appointment['id']}/cancel").status_code == 409
    assert client.post(f"/appointments/{appointment['id']}/complete").status_code == 409
    assert client.post(f"/appointments/{appointment['id']}/no-show").status_code == 409


def test_complete_before_start_is_rejected(client, patient, doctor):
    appointment = book(client, patient, doctor).json()

    response = client.post(f"/appointments/{appointment['id']}/complete")

    assert response.status_code == 422
    assert "до его начала" in response.json()["detail"]


def test_complete_saves_diagnoses_and_notes(client, clock, patient, doctor):
    first, second = make_diagnosis(client, "I10"), make_diagnosis(client, "E78", "Дислипидемия")
    appointment = book(client, patient, doctor).json()
    clock.value = datetime(2026, 11, 10, 10, 5)

    response = client.post(
        f"/appointments/{appointment['id']}/complete",
        json={"diagnosis_ids": [second["id"], first["id"]], "notes": "Наблюдение"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "completed"
    assert [d["icd_code"] for d in body["diagnoses"]] == ["E78", "I10"]
    assert body["notes"] == "Наблюдение"


def test_complete_with_unknown_diagnosis_returns_404(client, clock, patient, doctor):
    appointment = book(client, patient, doctor).json()
    clock.value = datetime(2026, 11, 10, 10, 5)

    response = client.post(f"/appointments/{appointment['id']}/complete", json={"diagnosis_ids": [404]})

    assert response.status_code == 404


def test_no_show_only_after_the_appointment_ended(client, clock, patient, doctor):
    appointment = book(client, patient, doctor).json()
    url = f"/appointments/{appointment['id']}/no-show"

    clock.value = datetime(2026, 11, 10, 10, 10)
    too_early = client.post(url)
    clock.value = datetime(2026, 11, 10, 10, 31)
    on_time = client.post(url)

    assert too_early.status_code == 422
    assert on_time.json()["status"] == "no_show"


def test_list_appointments_filters_and_sorts(client, patient, doctor):
    other = make_patient(client, full_name="Второй пациент")
    first = book(client, patient, doctor, at="2026-11-10T10:00:00Z").json()
    second = book(client, other, doctor, at="2026-11-11T12:00:00Z").json()
    client.post(f"/appointments/{second['id']}/cancel")

    by_doctor = client.get("/appointments", params={"doctor_id": doctor["id"], "order": "desc"}).json()
    cancelled = client.get("/appointments", params={"status": "cancelled"}).json()
    on_day = client.get("/appointments", params={"date_from": "2026-11-10", "date_to": "2026-11-10"}).json()
    by_patient = client.get("/appointments", params={"patient_id": other["id"]}).json()

    assert [a["id"] for a in by_doctor["items"]] == [second["id"], first["id"]]
    assert [a["id"] for a in cancelled["items"]] == [second["id"]]
    assert [a["id"] for a in on_day["items"]] == [first["id"]]
    assert by_patient["total"] == 1


def test_get_appointment_404(client):
    assert client.get("/appointments/12345").status_code == 404


# --- Осмотры и ML-оценка риска ---------------------------------------------


def test_examination_without_model_returns_503(client, patient):
    response = client.post(f"/patients/{patient['id']}/examinations", json=HEALTHY)

    assert response.status_code == 503
    assert client.get(f"/patients/{patient['id']}/examinations").json()["total"] == 0


def test_examination_is_scored_by_the_model(client_with_model, patient):
    low = client_with_model.post(f"/patients/{patient['id']}/examinations", json=HEALTHY)
    high = client_with_model.post(f"/patients/{patient['id']}/examinations", json=SICK)

    assert low.status_code == 201
    assert low.json()["risk_level"] == "low"
    assert high.json()["risk_level"] == "high"
    assert 0.9 < high.json()["risk_probability"] <= 1
    assert high.json()["measured_at"] == "2026-11-09T09:00:00"


def test_examination_history_is_newest_first(client_with_model, patient):
    older = client_with_model.post(
        f"/patients/{patient['id']}/examinations", json={**HEALTHY, "measured_at": "2026-10-01T09:00:00Z"}
    ).json()
    newer = client_with_model.post(f"/patients/{patient['id']}/examinations", json=SICK).json()

    history = client_with_model.get(f"/patients/{patient['id']}/examinations").json()

    assert [e["id"] for e in history["items"]] == [newer["id"], older["id"]]


def test_examination_validation_and_business_rules(client_with_model, patient):
    url = f"/patients/{patient['id']}/examinations"
    child = make_patient(client_with_model, full_name="Ребёнок", birth_date="2015-01-01", phone="+79990009999")

    reversed_pressure = client_with_model.post(url, json={**HEALTHY, "ap_hi": 80, "ap_lo": 120})
    impossible = client_with_model.post(url, json={**HEALTHY, "ap_hi": 16020})
    future = client_with_model.post(url, json={**HEALTHY, "measured_at": "2026-12-01T09:00:00Z"})
    underage = client_with_model.post(f"/patients/{child['id']}/examinations", json=HEALTHY)
    unknown = client_with_model.post("/patients/999/examinations", json=HEALTHY)

    assert [r.status_code for r in (reversed_pressure, impossible, future, underage, unknown)] == [
        422,
        422,
        422,
        422,
        404,
    ]
    assert "18 лет" in underage.json()["detail"]


def test_complete_after_high_risk_requires_a_diagnosis(client_with_model, clock, patient, doctor):
    client = client_with_model
    diagnosis = make_diagnosis(client)
    assert client.post(f"/patients/{patient['id']}/examinations", json=SICK).status_code == 201
    appointment = book(client, patient, doctor).json()
    clock.value = datetime(2026, 11, 10, 10, 5)
    url = f"/appointments/{appointment['id']}/complete"

    without = client.post(url, json={"notes": "осмотр"})
    with_diagnosis = client.post(url, json={"diagnosis_ids": [diagnosis["id"]]})

    assert without.status_code == 422
    assert "высокий риск" in without.json()["detail"]
    assert with_diagnosis.status_code == 200


def test_complete_after_low_risk_does_not_require_a_diagnosis(client_with_model, clock, patient, doctor):
    client = client_with_model
    client.post(f"/patients/{patient['id']}/examinations", json=HEALTHY)
    appointment = book(client, patient, doctor).json()
    clock.value = datetime(2026, 11, 10, 10, 5)

    assert client.post(f"/appointments/{appointment['id']}/complete").status_code == 200


# --- Аналитика --------------------------------------------------------------


def test_doctor_workload_counts_statuses(client, clock, patient, doctor):
    idle = make_doctor(client, full_name="Без приёмов", license_number="MD-0009")
    other = make_patient(client, full_name="Второй пациент")
    done = book(client, patient, doctor, at="2026-11-10T10:00:00Z").json()
    missed = book(client, other, doctor, at="2026-11-10T11:00:00Z").json()
    cancelled = book(client, other, doctor, at="2026-11-12T11:00:00Z").json()
    book(client, patient, doctor, at="2026-11-13T11:00:00Z")
    client.post(f"/appointments/{cancelled['id']}/cancel")
    clock.value = datetime(2026, 11, 10, 12, 0)
    client.post(f"/appointments/{done['id']}/complete")
    client.post(f"/appointments/{missed['id']}/no-show")

    report = client.get("/analytics/doctor-workload").json()

    busy, free = report
    assert busy["doctor_id"] == doctor["id"]
    assert (busy["total"], busy["completed"], busy["no_show"], busy["cancelled"], busy["scheduled"]) == (4, 1, 1, 1, 1)
    assert busy["completion_rate"] == 0.5
    assert free["doctor_id"] == idle["id"]
    assert (free["total"], free["completion_rate"]) == (0, None)


def test_doctor_workload_respects_date_range(client, patient, doctor):
    book(client, patient, doctor, at="2026-11-10T10:00:00Z")
    book(client, patient, doctor, at="2026-11-20T10:00:00Z")

    report = client.get("/analytics/doctor-workload", params={"date_from": "2026-11-15"}).json()

    assert report[0]["total"] == 1


def test_risk_dynamics_groups_by_period(client_with_model, patient):
    client = client_with_model
    url = f"/patients/{patient['id']}/examinations"
    for measured_at, body in [
        ("2026-09-05T09:00:00Z", HEALTHY),
        ("2026-10-05T09:00:00Z", HEALTHY),
        ("2026-10-20T09:00:00Z", SICK),
    ]:
        assert client.post(url, json={**body, "measured_at": measured_at}).status_code == 201

    monthly = client.get("/analytics/risk-dynamics").json()
    yearly = client.get("/analytics/risk-dynamics", params={"period": "year"}).json()
    october = client.get("/analytics/risk-dynamics", params={"date_from": "2026-10-01", "period": "day"}).json()

    assert [(p["period"], p["examinations"], p["high_risk"]) for p in monthly] == [
        ("2026-09", 1, 0),
        ("2026-10", 2, 1),
    ]
    assert monthly[1]["high_risk_share"] == 0.5
    assert yearly[0]["period"] == "2026" and yearly[0]["examinations"] == 3
    assert [p["period"] for p in october] == ["2026-10-05", "2026-10-20"]
    assert client.get("/analytics/risk-dynamics", params={"period": "week"}).status_code == 422


def test_top_diagnoses_counts_only_completed_appointments(client, clock, patient, doctor):
    hypertension, lipids = make_diagnosis(client, "I10"), make_diagnosis(client, "E78", "Дислипидемия")
    appointments = [book(client, patient, doctor, at=f"2026-11-1{day}T10:00:00Z").json() for day in (0, 1, 2)]
    clock.value = datetime(2026, 11, 14, 9, 0)
    for appointment, ids in zip(
        appointments, ([hypertension["id"]], [hypertension["id"], lipids["id"]], []), strict=True
    ):
        client.post(f"/appointments/{appointment['id']}/complete", json={"diagnosis_ids": ids})

    top = client.get("/analytics/top-diagnoses", params={"limit": 1}).json()
    everything = client.get("/analytics/top-diagnoses").json()

    assert top == [{"icd_code": "I10", "name": "Гипертензия", "appointments": 2}]
    assert [d["icd_code"] for d in everything] == ["I10", "E78"]


def test_risk_followup_lists_high_risk_patients_without_appointment(client_with_model, patient, doctor):
    client = client_with_model
    healthy = make_patient(client, full_name="Здоровый", phone="+79990003344")
    client.post(f"/patients/{healthy['id']}/examinations", json=HEALTHY)
    client.post(f"/patients/{patient['id']}/examinations", json=SICK)

    before = client.get("/analytics/risk-followup").json()
    book(client, patient, doctor)
    after = client.get("/analytics/risk-followup").json()

    assert [p["patient_id"] for p in before["items"]] == [patient["id"]]
    assert before["total"] == 1
    assert after["items"] == []


def test_error_format_is_the_same_for_all_failures(client):
    responses = [
        client.get("/patients/1"),
        client.post("/predict", json={"records": []}),
        client.post("/appointments", json={}),
    ]

    for response in responses:
        assert set(response.json()) == {"status", "detail"}
        assert response.json()["status"] == "error"


def test_openapi_documents_clinic_endpoints(client):
    spec = client.get("/openapi.json").json()

    assert spec["info"]["title"] == "Cardio Clinic"
    assert {"/patients", "/appointments", "/analytics/doctor-workload"} <= set(spec["paths"])
    assert "example" in spec["components"]["schemas"]["AppointmentCreate"]
    assert datetime.fromisoformat("2026-11-10T10:00:00") + timedelta(minutes=30)  # sanity check of test constants
