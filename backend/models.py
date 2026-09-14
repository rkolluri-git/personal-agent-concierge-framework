from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class FamilyMember(Base):
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="adult", server_default="adult")
    encrypted_age: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def age(self) -> int | None:
        from sensitive_crypto import decrypt_age

        return decrypt_age(self.encrypted_age)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'in_progress', 'completed')", name="task_status_valid"),
        CheckConstraint(
            "reminder_minutes_before IS NULL OR reminder_minutes_before BETWEEN 0 AND 10080",
            name="task_reminder_valid",
        ),
        CheckConstraint("repeat_interval IN ('none', 'weekly')", name="task_repeat_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("family_members.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reminder_minutes_before: Mapped[int | None] = mapped_column(Integer)
    repeat_interval: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assignee: Mapped[FamilyMember | None] = relationship(lazy="joined")

    @property
    def assigned_to_name(self) -> str | None:
        return self.assignee.name if self.assignee else None


class DepartureSettings(Base):
    __tablename__ = "departure_settings"
    __table_args__ = (
        CheckConstraint("arrival_buffer_minutes BETWEEN 0 AND 180", name="arrival_buffer_valid"),
        CheckConstraint("parking_walk_minutes BETWEEN 0 AND 180", name="parking_walk_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    home_address: Mapped[str] = mapped_column(String(500))
    arrival_buffer_minutes: Mapped[int] = mapped_column(Integer, default=10)
    parking_walk_minutes: Mapped[int] = mapped_column(Integer, default=10)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DepartureTripPreference(Base):
    __tablename__ = "departure_trip_preferences"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    round_trip: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CommuteSchedule(Base):
    __tablename__ = "commute_schedules"
    __table_args__ = (
        CheckConstraint("kind IN ('work', 'school')", name="commute_kind_valid"),
        CheckConstraint("send_time ~ '^[0-2][0-9]:[0-5][0-9]$'", name="commute_time_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id"), index=True)
    label: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    encrypted_destination_address: Mapped[str] = mapped_column(Text)
    send_time: Mapped[str] = mapped_column(String(5))
    weekdays: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4")
    use_school_calendar: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    member: Mapped[FamilyMember] = relationship(lazy="joined")

    @property
    def member_name(self) -> str:
        return self.member.name

    @property
    def destination_address(self) -> str | None:
        from sensitive_crypto import decrypt_text

        return decrypt_text(self.encrypted_destination_address)


class CommuteRun(Base):
    __tablename__ = "commute_runs"
    __table_args__ = (
        UniqueConstraint("schedule_id", "run_date", name="uq_commute_run_schedule_date"),
        CheckConstraint("status IN ('claimed', 'completed', 'failed')", name="commute_run_status_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("commute_schedules.id", ondelete="CASCADE"), index=True)
    run_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="claimed")
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    distance_meters: Mapped[int | None] = mapped_column(Integer)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WeatherSettings(Base):
    __tablename__ = "weather_settings"
    __table_args__ = (
        CheckConstraint("rain_probability_percent BETWEEN 0 AND 100", name="weather_rain_threshold_valid"),
        CheckConstraint("jacket_below_fahrenheit BETWEEN -50 AND 100", name="weather_jacket_threshold_valid"),
        CheckConstraint("dress_light_above_fahrenheit BETWEEN 40 AND 140", name="weather_light_threshold_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    location_name: Mapped[str] = mapped_column(String(200))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    timezone_name: Mapped[str] = mapped_column(String(100))
    rain_probability_percent: Mapped[int] = mapped_column(Integer, default=50)
    jacket_below_fahrenheit: Mapped[int] = mapped_column(Integer, default=55)
    dress_light_above_fahrenheit: Mapped[int] = mapped_column(Integer, default=80)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MorningBriefingSettings(Base):
    __tablename__ = "morning_briefing_settings"
    __table_args__ = (
        CheckConstraint("send_time ~ '^[0-2][0-9]:[0-5][0-9]$'", name="morning_time_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    send_time: Mapped[str] = mapped_column(String(5), default="07:00")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MorningBriefingPreference(Base):
    __tablename__ = "morning_briefing_preferences"

    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    include_family_schedule: Mapped[bool] = mapped_column(Boolean, default=False)
    member: Mapped[FamilyMember] = relationship(lazy="joined")


class CalendarAssignment(Base):
    __tablename__ = "calendar_assignments"

    calendar_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id"), primary_key=True)


class MorningBriefingMarker(Base):
    __tablename__ = "morning_briefing_markers"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), unique=True)


class MorningBriefingRun(Base):
    __tablename__ = "morning_briefing_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'waiting_for_calendar', 'waiting_for_weather', 'queued', 'complete', 'no_contacts')",
            name="morning_briefing_run_status_valid",
        ),
    )

    briefing_date: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(30))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertContact(Base):
    __tablename__ = "alert_contacts"

    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id"), primary_key=True)
    encrypted_imessage_handle: Mapped[str] = mapped_column("imessage_handle", Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    member: Mapped[FamilyMember] = relationship(lazy="joined")

    @property
    def member_name(self) -> str:
        return self.member.name

    @property
    def imessage_handle(self) -> str | None:
        from sensitive_crypto import decrypt_text

        return decrypt_text(self.encrypted_imessage_handle)


class ConciergeInboxItem(Base):
    __tablename__ = "concierge_inbox_items"
    __table_args__ = (
        UniqueConstraint("message_guid", name="uq_concierge_inbox_message_guid"),
        CheckConstraint(
            "status IN ('pending', 'handled', 'dismissed')",
            name="concierge_inbox_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_guid: Mapped[str] = mapped_column(String(200), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id"), index=True)
    encrypted_request: Mapped[str] = mapped_column(Text)
    encrypted_plan: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    member: Mapped[FamilyMember] = relationship(lazy="joined")

    @property
    def member_name(self) -> str:
        return self.member.name


class ConciergeReplyReceipt(Base):
    __tablename__ = "concierge_reply_receipts"
    message_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("concierge_inbox_items.id", ondelete="CASCADE"), index=True)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'uncertain')",
            name="alert_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), unique=True, index=True
    )
    message: Mapped[str] = mapped_column(String(500))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    member: Mapped[FamilyMember] = relationship(lazy="joined")

    @property
    def member_name(self) -> str:
        return self.member.name


class CalendarAlertRule(Base):
    __tablename__ = "calendar_alert_rules"
    __table_args__ = (
        CheckConstraint(
            "appointment_reminder_minutes BETWEEN 0 AND 10080",
            name="appointment_reminder_valid",
        ),
        CheckConstraint(
            "leave_reminder_minutes BETWEEN 0 AND 10080",
            name="leave_reminder_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    appointment_reminder_minutes: Mapped[int] = mapped_column(Integer, default=30)
    leave_reminder_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CalendarAlertMarker(Base):
    __tablename__ = "calendar_alert_markers"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), unique=True)
