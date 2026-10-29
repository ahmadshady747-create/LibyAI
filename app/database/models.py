from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import text
from sqlmodel import SQLModel, Field

# Server defaults are deliberate, not cosmetic: the legacy layer (db.py) and
# seed scripts insert rows with raw SQL that omits several columns. A Python
# default alone does not create a database default, so a table created first
# by SQLModel used to reject those inserts with NOT NULL errors, while a
# table created first by the legacy layer (which has its own defaults) did
# not. That made test and startup outcomes depend on import order. These
# server defaults make both creation orders behave the same.


class Doctor(SQLModel, table=True):
    __tablename__ = "doctors"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    specialty: str = Field(index=True)
    room_number: Optional[str] = Field(default="غير محدد")
    regular_schedule: str
    schedule_days: str = Field(
        default="السبت,الأحد,الإثنين,الثلاثاء,الأربعاء,الخميس",
        sa_column_kwargs={"server_default": text("'السبت,الأحد,الإثنين,الثلاثاء,الأربعاء,الخميس'")},
    )
    status: str = Field(default="available", sa_column_kwargs={"server_default": text("'available'")})
    today_status: str = Field(default="available", sa_column_kwargs={"server_default": text("'available'")})  # 'available', 'apologized', 'delayed', 'left', 'arrived', 'booking_closed'
    daily_note: Optional[str] = Field(default="")
    today_note: Optional[str] = Field(default="")
    consultation_fee: float = Field(default=40.0, sa_column_kwargs={"server_default": text("40.0")})
    is_active: bool = Field(default=True, sa_column_kwargs={"server_default": text("1")})
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")})


class Service(SQLModel, table=True):
    __tablename__ = "services"

    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(index=True)  # مختبر, أشعة, كشوفات, طوارئ
    name: str = Field(index=True)
    price: float = Field(default=0.0, sa_column_kwargs={"server_default": text("0.0")})
    instructions: Optional[str] = Field(default="")
    prep_instructions: Optional[str] = Field(default="")
    availability: str = Field(default="متاح خلال ساعات العمل الرسمية", sa_column_kwargs={"server_default": text("'متاح خلال ساعات العمل الرسمية'")})
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")})


class ClinicConfig(SQLModel, table=True):
    __tablename__ = "clinic_config"

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)
    value: str
    description: Optional[str] = None


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    sender: str
    raw_message: str
    action_type: str
    extracted_data: str
    confirmation_sent: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
