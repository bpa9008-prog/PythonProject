"""create clinic schema

Revision ID: 0001
Revises:
Create Date: 2026-11-08 13:11:31.980920
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnoses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("icd_code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diagnoses")),
        sa.UniqueConstraint("icd_code", name=op.f("uq_diagnoses_icd_code")),
    )
    op.create_table(
        "doctors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("specialty", sa.String(length=100), nullable=False),
        sa.Column("license_number", sa.String(length=30), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctors")),
        sa.UniqueConstraint("license_number", name=op.f("uq_doctors_license_number")),
    )
    with op.batch_alter_table("doctors", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_doctors_specialty"), ["specialty"], unique=False)

    op.create_table(
        "patients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.Integer(), nullable=True),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("gender", sa.String(length=1), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("gender IN ('F', 'M')", name=op.f("ck_patients_gender_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        sa.UniqueConstraint("external_id", name=op.f("uq_patients_external_id")),
        sa.UniqueConstraint("phone", name=op.f("uq_patients_phone")),
    )
    with op.batch_alter_table("patients", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_patients_full_name"), ["full_name"], unique=False)

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="scheduled", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('scheduled', 'completed', 'cancelled', 'no_show')", name=op.f("ck_appointments_status_valid")
        ),
        sa.CheckConstraint("ends_at > scheduled_at", name=op.f("ck_appointments_ends_after_start")),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_appointments_doctor_id_doctors"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_appointments_patient_id_patients"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
    )
    with op.batch_alter_table("appointments", schema=None) as batch_op:
        batch_op.create_index(
            "uq_appointments_doctor_active_slot",
            ["doctor_id", "scheduled_at"],
            unique=True,
            sqlite_where=sa.text("status IN ('scheduled', 'completed')"),
            postgresql_where=sa.text("status IN ('scheduled', 'completed')"),
        )
        batch_op.create_index("ix_appointments_doctor_time", ["doctor_id", "scheduled_at"], unique=False)
        batch_op.create_index("ix_appointments_patient_time", ["patient_id", "scheduled_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_appointments_status"), ["status"], unique=False)

    op.create_table(
        "appointment_diagnoses",
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("diagnosis_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name=op.f("fk_appointment_diagnoses_appointment_id_appointments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["diagnosis_id"],
            ["diagnoses.id"],
            name=op.f("fk_appointment_diagnoses_diagnosis_id_diagnoses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("appointment_id", "diagnosis_id", name=op.f("pk_appointment_diagnoses")),
    )
    with op.batch_alter_table("appointment_diagnoses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_appointment_diagnoses_diagnosis_id"), ["diagnosis_id"], unique=False)

    op.create_table(
        "examinations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=True),
        sa.Column("measured_at", sa.DateTime(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("ap_hi", sa.Integer(), nullable=False),
        sa.Column("ap_lo", sa.Integer(), nullable=False),
        sa.Column("cholesterol", sa.Integer(), nullable=False),
        sa.Column("gluc", sa.Integer(), nullable=False),
        sa.Column("smoke", sa.Boolean(), nullable=False),
        sa.Column("alco", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("risk_probability", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(length=6), nullable=True),
        sa.CheckConstraint(
            "risk_level IS NULL OR risk_level IN ('low', 'medium', 'high')",
            name=op.f("ck_examinations_risk_level_valid"),
        ),
        sa.CheckConstraint("ap_hi >= ap_lo", name=op.f("ck_examinations_pressure_order")),
        sa.CheckConstraint("cholesterol IN (1, 2, 3)", name=op.f("ck_examinations_cholesterol_valid")),
        sa.CheckConstraint("gluc IN (1, 2, 3)", name=op.f("ck_examinations_gluc_valid")),
        sa.CheckConstraint("height > 0 AND weight > 0", name=op.f("ck_examinations_body_positive")),
        sa.CheckConstraint(
            "risk_probability IS NULL OR risk_probability BETWEEN 0 AND 1", name=op.f("ck_examinations_risk_range")
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name=op.f("fk_examinations_appointment_id_appointments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_examinations_patient_id_patients"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_examinations")),
    )
    with op.batch_alter_table("examinations", schema=None) as batch_op:
        batch_op.create_index("ix_examinations_measured_at", ["measured_at"], unique=False)
        batch_op.create_index("ix_examinations_patient_time", ["patient_id", "measured_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_examinations_risk_level"), ["risk_level"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("examinations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_examinations_risk_level"))
        batch_op.drop_index("ix_examinations_patient_time")
        batch_op.drop_index("ix_examinations_measured_at")

    op.drop_table("examinations")
    with op.batch_alter_table("appointment_diagnoses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_appointment_diagnoses_diagnosis_id"))

    op.drop_table("appointment_diagnoses")
    with op.batch_alter_table("appointments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_appointments_status"))
        batch_op.drop_index("ix_appointments_patient_time")
        batch_op.drop_index("ix_appointments_doctor_time")
        batch_op.drop_index("uq_appointments_doctor_active_slot")

    op.drop_table("appointments")
    with op.batch_alter_table("patients", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_patients_full_name"))

    op.drop_table("patients")
    with op.batch_alter_table("doctors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_doctors_specialty"))

    op.drop_table("doctors")
    op.drop_table("diagnoses")
