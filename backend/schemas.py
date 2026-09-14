from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TaskStatus = Literal["pending", "in_progress", "completed"]
TaskRepeat = Literal["none", "weekly"]
FamilyRole = Literal["parent", "child", "adult"]
ConciergeInboxStatus = Literal["pending", "handled", "dismissed"]
ConciergeTransportationMode = Literal["dropoff_and_pickup", "pickup_only", "none"]


class MemberCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    role: FamilyRole = "adult"
    age: int | None = Field(default=None, ge=0, le=120)


class MemberRead(MemberCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class MemberProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: FamilyRole | None = None
    age: int | None = Field(default=None, ge=0, le=120)


class MemberCreateWithContact(MemberCreate):
    imessage_handle: str | None = Field(default=None, min_length=3, max_length=254)
    alerts_enabled: bool = True


class FamilyDirectoryMemberUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    member_id: Annotated[int, Field(gt=0)]
    role: FamilyRole
    age: int | None = Field(default=None, ge=0, le=120)
    imessage_handle: str | None = Field(default=None, min_length=3, max_length=254)
    alerts_enabled: bool = True


class FamilyDirectoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    members: list[FamilyDirectoryMemberUpdate] = Field(max_length=100)


class TaskCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    assigned_to: Annotated[int, Field(gt=0)] | Annotated[str, Field(min_length=1, max_length=100)] | None = Field(default=None, description="Family member name (case-insensitive) or numeric ID", examples=["Alex"])
    due_at: datetime | None = None
    reminder_minutes_before: int | None = Field(default=None, ge=0, le=10080)
    repeat_interval: TaskRepeat = "none"

    @field_validator("due_at")
    @classmethod
    def require_due_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Include a timezone with the task due time")
        return value

    @model_validator(mode="after")
    def reminder_requires_due_date_and_assignee(self):
        if self.reminder_minutes_before is not None and self.due_at is None:
            raise ValueError("Choose a due date before adding a reminder")
        if self.reminder_minutes_before is not None and self.assigned_to is None:
            raise ValueError("Assign the task to someone before adding a reminder")
        if self.repeat_interval == "weekly" and self.due_at is None:
            raise ValueError("Choose the first date and time for a weekly task")
        return self


class TaskRead(TaskCreate):
    assigned_to: int | None
    assigned_to_name: str | None
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: TaskStatus
    created_at: datetime


class TaskStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TaskStatus


class DepartureSettingsUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    home_address: str = Field(min_length=3, max_length=500)
    arrival_buffer_minutes: int = Field(default=10, ge=0, le=180)
    parking_walk_minutes: int = Field(default=10, ge=0, le=180)


class DepartureSettingsRead(DepartureSettingsUpdate):
    model_config = ConfigDict(from_attributes=True)
    configured: bool = True
    updated_at: datetime | None = None


class DepartureTripUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    round_trip: bool


class DepartureTripRead(DepartureTripUpdate):
    model_config = ConfigDict(from_attributes=True)
    event_id: str
    updated_at: datetime | None = None


class CommuteScheduleUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    member_id: Annotated[int, Field(gt=0)]
    label: str = Field(min_length=1, max_length=100)
    kind: Literal["work", "school"]
    destination_address: str = Field(min_length=3, max_length=500)
    send_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    use_school_calendar: bool = False
    enabled: bool = True

    @field_validator("weekdays")
    @classmethod
    def unique_weekdays(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Choose each weekday only once")
        return sorted(value)

    @model_validator(mode="after")
    def school_calendar_only_for_school_routes(self):
        if self.use_school_calendar and self.kind != "school":
            raise ValueError("The school calendar applies only to school routes")
        return self


class CommuteScheduleRead(CommuteScheduleUpdate):
    id: int
    member_name: str
    updated_at: datetime | None = None


class CommuteClaim(BaseModel):
    run_id: int
    schedule_id: int
    member_name: str
    label: str
    kind: Literal["work", "school"]
    origin_address: str
    destination_address: str
    send_time: str


class CommuteResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    duration_seconds: int | None = Field(default=None, ge=1, le=86400)
    distance_meters: int | None = Field(default=None, ge=1, le=2000000)
    error: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def duration_or_error(self):
        if self.duration_seconds is None and self.error is None:
            raise ValueError("Include a travel time or an error")
        return self


class WeatherSettingsUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    location: str = Field(min_length=2, max_length=200, examples=["Example City 00000"])
    rain_probability_percent: int = Field(default=50, ge=0, le=100)
    jacket_below_fahrenheit: int = Field(default=55, ge=-50, le=100)
    dress_light_above_fahrenheit: int = Field(default=80, ge=40, le=140)


class WeatherSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    configured: bool = True
    suggested_location: str = ""
    location_name: str = ""
    timezone_name: str = ""
    rain_probability_percent: int = 50
    jacket_below_fahrenheit: int = 55
    dress_light_above_fahrenheit: int = 80
    updated_at: datetime | None = None


class MorningBriefingRecipient(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member_id: Annotated[int, Field(gt=0)]
    enabled: bool = True
    include_family_schedule: bool = False
    calendar_keys: list[str] = Field(default_factory=list, max_length=100)


class MorningBriefingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    send_time: str = Field(default="07:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    recipients: list[MorningBriefingRecipient] = Field(default_factory=list, max_length=100)


class CalendarAssignmentUpdateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calendar_key: str = Field(min_length=1, max_length=32)
    member_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=100)


class CalendarAssignmentsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignments: list[CalendarAssignmentUpdateItem] = Field(default_factory=list, max_length=100)


class ConciergePreviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    text: str = Field(min_length=3, max_length=2000)
    driver: str | None = Field(default=None, min_length=1, max_length=100)
    transportation_mode: ConciergeTransportationMode | None = None
    pickup_by: str | None = Field(default=None, min_length=1, max_length=100)
    combine_adjacent_events: bool = False
    requester_name: str | None = Field(default=None, min_length=1, max_length=100)


class ConciergeInboxRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    message_guid: str = Field(min_length=1, max_length=200)
    sender_handle: str = Field(min_length=3, max_length=254)
    text: str = Field(min_length=1, max_length=2000)
    received_at: datetime | None = None

    @field_validator("received_at")
    @classmethod
    def require_received_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Include a timezone with the received time")
        return value


class ConciergeInboxStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ConciergeInboxStatus


class ConciergeFieldEdits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    date: str | None = None
    time: str | None = None
    end_time: str | None = None
    primary_member: str
    notification_members: list[str] = Field(max_length=30)
    repeat_interval: Literal['none', 'weekly'] = 'none'

    @field_validator('date')
    @classmethod
    def valid_date(cls, value):
        if value:
            from datetime import date
            date.fromisoformat(value)
        return value or None

    @field_validator('time', 'end_time')
    @classmethod
    def valid_clock(cls, value):
        if value:
            import re
            if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value): raise ValueError('Use HH:MM time')
        return value or None


class ConciergePlanUpdate(BaseModel):
    keep_in_inbox: bool = False
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    edits: ConciergeFieldEdits | None = None
    text: str = Field(min_length=3, max_length=2000)
    driver: str | None = Field(default=None, min_length=1, max_length=100)
    transportation_mode: ConciergeTransportationMode | None = None
    pickup_by: str | None = Field(default=None, min_length=1, max_length=100)
    combine_adjacent_events: bool = False


class AlertContactUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    imessage_handle: str = Field(min_length=3, max_length=254)
    enabled: bool = True


class AlertContactRead(AlertContactUpdate):
    model_config = ConfigDict(from_attributes=True)
    member_id: int
    member_name: str
    updated_at: datetime | None = None


class AlertContactBulkItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    member_id: Annotated[int, Field(gt=0)]
    imessage_handle: str | None = Field(default=None, min_length=3, max_length=254)
    enabled: bool = True


class AlertContactsBulkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contacts: list[AlertContactBulkItem] = Field(max_length=100)


class AlertCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    member_id: Annotated[int, Field(gt=0)]
    message: str = Field(min_length=1, max_length=500)
    scheduled_for: datetime

    @field_validator("scheduled_for")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Include a timezone with the alert time")
        return value


class AlertRead(AlertCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    member_name: str
    status: Literal["pending", "sending", "sent", "failed", "uncertain"]
    created_at: datetime
    sent_at: datetime | None = None
    attempt_count: int = 0
    last_attempt_at: datetime | None = None


class AlertClaim(BaseModel):
    id: int
    member_name: str
    imessage_handle: str
    message: str
    scheduled_for: datetime


class CalendarAlertRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member_id: Annotated[int, Field(gt=0)]
    enabled: bool = True
    appointment_reminder_minutes: int = Field(default=30, ge=0, le=10080)
    leave_reminder_minutes: int = Field(default=60, ge=0, le=10080)


class CalendarAlertRuleRead(CalendarAlertRuleUpdate):
    member_id: int | None = None
    model_config = ConfigDict(from_attributes=True)
    configured: bool = True
    last_synced_at: datetime | None = None
    updated_at: datetime | None = None


class ConciergeReplyRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    message_guid: str = Field(min_length=1, max_length=200)


class ConciergeWebRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    text: str = Field(min_length=3, max_length=2000)
    member_id: int = Field(gt=0)
    request_id: str = Field(min_length=36, max_length=36)
