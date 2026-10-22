from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Doctor(SQLModel, table=True):
    __tablename__ = "doctors"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    specialty: str = Field(index=True)
    room_number: Optional[str] = Field(default="غير محدد")
    regular_schedule: str
    schedule_days: str = Field(default="السبت,الأحد,الإثنين,الثلاثاء,الأربعاء,الخميس")
    status: str = Field(default="available")
    today_status: str = Field(default="available")  # 'available', 'apologized', 'delayed', 'left', 'arrived', 'booking_closed'
    daily_note: Optional[str] = Field(default="")
    today_note: Optional[str] = Field(default="")
    consultation_fee: float = Field(default=40.0)
    is_active: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Service(SQLModel, table=True):
    __tablename__ = "services"

    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(index=True)  # مختبر, أشعة, كشوفات, طوارئ
    name: str = Field(index=True)
    price: float = Field(default=0.0)
    instructions: Optional[str] = Field(default="")
    prep_instructions: Optional[str] = Field(default="")
    availability: str = Field(default="متاح خلال ساعات العمل الرسمية")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


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
    created_at: datetime = Field(default_factory=datetime.utcnow)
