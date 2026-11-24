from dataclasses import replace
from datetime import datetime

from calendar_sync.google_calendar.models import CalendarEvent
from calendar_sync.spielerplus.exceptions import SpielerPlusError
from calendar_sync.spielerplus.models import Attendance, SpielerPlusEvent
from calendar_sync.sync.service import (
    SyncService,
    default_description,
    default_title,
    prefixed_title_builder,
)


class FakeSpielerPlus:
    def __init__(self, events):
        self._events = events

    def get_events(self):
        return self._events


class FakeGoogleCalendar:
    def __init__(self, existing=None):
        self.events = dict(existing or {})
        self.created = []
        self.updated = []
        self.deleted = []
        self._next_id = 1

    def list_managed_events(self):
        return dict(self.events)

    def create_event(self, event):
        google_id = f"g{self._next_id}"
        self._next_id += 1
        created = CalendarEvent(
            external_id=event.external_id,
            title=event.title,
            description=event.description,
            start=event.start,
            end=event.end,
            location=event.location,
            google_id=google_id,
        )
        self.events[event.external_id] = created
        self.created.append(created)
        return created

    def update_event(self, event):
        self.events[event.external_id] = event
        self.updated.append(event)
        return event

    def delete_event(self, google_id):
        self.deleted.append(google_id)
        self.events = {k: v for k, v in self.events.items() if v.google_id != google_id}


def _sp_event(
    id="111",
    event_type="training",
    title="Training",
    subtitle="",
    start=None,
    end=None,
    attendance=Attendance.UNKNOWN,
    end_is_estimated=False,
) -> SpielerPlusEvent:
    return SpielerPlusEvent(
        id=id,
        event_type=event_type,
        title=title,
        subtitle=subtitle,
        start=start or datetime(2026, 7, 18, 19, 0),
        end=end or datetime(2026, 7, 18, 21, 0),
        end_is_estimated=end_is_estimated,
        attendance=attendance,
    )


def test_sync_creates_events_missing_from_google_calendar():
    sp = FakeSpielerPlus([_sp_event(id="111"), _sp_event(id="222", event_type="match")])
    gc = FakeGoogleCalendar()

    result = SyncService(sp, gc).sync()

    assert set(result.created) == {"training-111", "match-222"}
    assert result.updated == []
    assert result.deleted == []
    assert len(gc.created) == 2


def test_sync_applies_a_custom_title_builder_to_created_events():
    sp = FakeSpielerPlus([_sp_event(id="111")])
    gc = FakeGoogleCalendar()

    SyncService(sp, gc, title_builder=prefixed_title_builder("U7")).sync()

    assert gc.created[0].title == "[U7] Training"


def test_sync_leaves_matching_events_untouched():
    sp_event = _sp_event(id="111")
    sp = FakeSpielerPlus([sp_event])
    existing = CalendarEvent(
        external_id="training-111",
        title=default_title(sp_event),
        description=default_description(sp_event),
        start=sp_event.start,
        end=sp_event.end,
        google_id="g1",
    )
    gc = FakeGoogleCalendar(existing={"training-111": existing})

    result = SyncService(sp, gc).sync()

    assert result.unchanged == ["training-111"]
    assert result.created == []
    assert result.updated == []
    assert gc.updated == []


def test_sync_updates_events_whose_time_changed():
    sp_event = _sp_event(id="111", start=datetime(2026, 7, 18, 20, 0), end=datetime(2026, 7, 18, 22, 0))
    sp = FakeSpielerPlus([sp_event])
    stale = CalendarEvent(
        external_id="training-111",
        title=default_title(sp_event),
        description=default_description(sp_event),
        start=datetime(2026, 7, 18, 19, 0),
        end=datetime(2026, 7, 18, 21, 0),
        google_id="g1",
    )
    gc = FakeGoogleCalendar(existing={"training-111": stale})

    result = SyncService(sp, gc).sync()

    assert result.updated == ["training-111"]
    assert gc.updated[0].google_id == "g1"
    assert gc.updated[0].start == datetime(2026, 7, 18, 20, 0)


def test_sync_deletes_events_no_longer_in_spielerplus():
    sp = FakeSpielerPlus([])
    stale = CalendarEvent(
        external_id="training-999",
        title="Old training",
        description="",
        start=datetime(2026, 7, 1, 19, 0),
        end=datetime(2026, 7, 1, 21, 0),
        google_id="g1",
    )
    gc = FakeGoogleCalendar(existing={"training-999": stale})

    result = SyncService(sp, gc).sync()

    assert result.deleted == ["training-999"]
    assert gc.deleted == ["g1"]


def test_sync_handles_create_update_and_delete_together():
    kept = _sp_event(id="111")
    new = _sp_event(id="222", event_type="match")
    sp = FakeSpielerPlus([kept, new])

    kept_existing = CalendarEvent(
        external_id="training-111",
        title=default_title(kept),
        description=default_description(kept),
        start=kept.start,
        end=kept.end,
        google_id="g1",
    )
    removed_existing = CalendarEvent(
        external_id="other-333",
        title="Gone",
        description="",
        start=datetime(2026, 7, 1, 0, 0),
        end=datetime(2026, 7, 1, 1, 0),
        google_id="g2",
    )
    gc = FakeGoogleCalendar(existing={"training-111": kept_existing, "other-333": removed_existing})

    result = SyncService(sp, gc).sync()

    assert result.created == ["match-222"]
    assert result.unchanged == ["training-111"]
    assert result.deleted == ["other-333"]
    assert gc.deleted == ["g2"]


def test_sync_result_total_counts_every_bucket():
    from calendar_sync.sync.service import SyncResult

    result = SyncResult(created=["a"], updated=["b", "c"], deleted=[], unchanged=["d"])
    assert result.total == 4


def test_default_title_appends_subtitle_when_present():
    event = _sp_event(title="Punktspiel", subtitle="Heimspiel")
    assert default_title(event) == "Punktspiel – Heimspiel"


def test_default_title_omits_dash_when_no_subtitle():
    event = _sp_event(title="Training", subtitle="")
    assert default_title(event) == "Training"


def test_prefixed_title_builder_prepends_bracketed_prefix():
    event = _sp_event(title="Punktspiel", subtitle="Heimspiel")
    build = prefixed_title_builder("U7")
    assert build(event) == "[U7] Punktspiel – Heimspiel"


def test_prefixed_title_builder_without_prefix_is_a_no_op():
    event = _sp_event(title="Training", subtitle="")
    build = prefixed_title_builder(None)
    assert build(event) == default_title(event)


def test_default_description_flags_estimated_end_time():
    event = _sp_event(end_is_estimated=True)
    description = default_description(event)
    assert "estimated" in description.lower()


def test_default_description_omits_estimate_note_when_end_is_known():
    event = _sp_event(end_is_estimated=False)
    description = default_description(event)
    assert "estimated" not in description.lower()


def test_sync_uses_meeting_time_as_start_when_enabled():
    meetup = datetime(2026, 7, 18, 18, 30)
    ev = SpielerPlusEvent(
        id="1", event_type="training", title="Training", subtitle="",
        start=datetime(2026, 7, 18, 19, 0), end=datetime(2026, 7, 18, 21, 0),
        end_is_estimated=False, attendance=Attendance.UNKNOWN, meetup=meetup,
    )
    gc = FakeGoogleCalendar()
    SyncService(FakeSpielerPlus([ev]), gc, use_meeting_time=True).sync()

    created = gc.created[0]
    assert created.start == meetup
    assert created.end == ev.end
    assert "Meeting time: 18:30" in created.description
    assert "Start: 19:00" in created.description


def test_sync_ignores_meeting_time_by_default():
    ev = SpielerPlusEvent(
        id="1", event_type="training", title="Training", subtitle="",
        start=datetime(2026, 7, 18, 19, 0), end=datetime(2026, 7, 18, 21, 0),
        end_is_estimated=False, attendance=Attendance.UNKNOWN, meetup=datetime(2026, 7, 18, 18, 30),
    )
    gc = FakeGoogleCalendar()
    SyncService(FakeSpielerPlus([ev]), gc).sync()

    assert gc.created[0].start == ev.start
    assert "Meeting time" not in gc.created[0].description


def test_sync_falls_back_to_start_when_no_meeting_time():
    gc = FakeGoogleCalendar()
    SyncService(FakeSpielerPlus([_sp_event()]), gc, use_meeting_time=True).sync()

    assert gc.created[0].start == datetime(2026, 7, 18, 19, 0)
    assert "Meeting time" not in gc.created[0].description


class FakeSpielerPlusWithLocations(FakeSpielerPlus):
    def __init__(self, events, locations=None, fail=False):
        super().__init__(events)
        self.locations = locations or {}
        self.fail = fail
        self.lookups = []

    def get_event_location(self, event):
        self.lookups.append(event.uid)
        if self.fail:
            raise SpielerPlusError("boom")
        return self.locations.get(event.uid)


NOW = datetime(2026, 7, 10, 12, 0)
SOON = datetime(2026, 7, 18, 19, 0)   # 8 days ahead
LATER = datetime(2026, 9, 1, 19, 0)   # far in the future


def _located_service(sp, gc, **kwargs):
    return SyncService(sp, gc, include_location=True, now=lambda: NOW, **kwargs)


def test_location_is_not_looked_up_unless_enabled():
    sp = FakeSpielerPlusWithLocations([_sp_event()], {"training-111": "Platz 1"})
    gc = FakeGoogleCalendar()
    SyncService(sp, gc, now=lambda: NOW).sync()

    assert sp.lookups == []
    assert gc.created[0].location is None


def test_location_is_written_to_new_events():
    sp = FakeSpielerPlusWithLocations([_sp_event(start=SOON, end=SOON.replace(hour=21))], {"training-111": "Platz 1"})
    gc = FakeGoogleCalendar()
    _located_service(sp, gc).sync()

    assert gc.created[0].location == "Platz 1"


def test_changed_location_updates_the_existing_event():
    sp = FakeSpielerPlusWithLocations([_sp_event(start=SOON, end=SOON.replace(hour=21))], {"training-111": "Neuer Platz"})
    gc = FakeGoogleCalendar()
    _located_service(sp, gc).sync()  # create
    gc.events["training-111"] = replace(gc.events["training-111"], location="Alter Platz")

    result = _located_service(sp, gc).sync()

    assert result.updated == ["training-111"]
    assert gc.updated[-1].location == "Neuer Platz"


def test_unchanged_location_is_a_noop():
    sp = FakeSpielerPlusWithLocations([_sp_event(start=SOON, end=SOON.replace(hour=21))], {"training-111": "Platz 1"})
    gc = FakeGoogleCalendar()
    _located_service(sp, gc).sync()
    result = _located_service(sp, gc).sync()

    assert result.unchanged == ["training-111"] and not gc.updated


def test_events_beyond_the_lookahead_window_are_not_looked_up():
    sp = FakeSpielerPlusWithLocations(
        [_sp_event(id="1", start=SOON, end=SOON.replace(hour=21)),
         _sp_event(id="2", start=LATER, end=LATER.replace(hour=21))],
        {"training-1": "A", "training-2": "B"},
    )
    gc = FakeGoogleCalendar()
    _located_service(sp, gc, location_lookahead_days=14).sync()

    assert sp.lookups == ["training-1"]
    assert gc.events["training-2"].location is None


def test_far_future_event_keeps_the_location_google_already_has():
    ev = _sp_event(start=LATER, end=LATER.replace(hour=21))
    gc = FakeGoogleCalendar()
    SyncService(FakeSpielerPlus([ev]), gc, now=lambda: NOW).sync()
    gc.events["training-111"] = replace(gc.events["training-111"], location="Manuell")

    result = _located_service(FakeSpielerPlusWithLocations([ev]), gc).sync()

    assert result.unchanged == ["training-111"]


def test_failed_lookup_keeps_the_current_location_instead_of_clearing_it():
    ev = _sp_event(start=SOON, end=SOON.replace(hour=21))
    gc = FakeGoogleCalendar()
    _located_service(FakeSpielerPlusWithLocations([ev], {"training-111": "Platz 1"}), gc).sync()

    result = _located_service(FakeSpielerPlusWithLocations([ev], fail=True), gc).sync()

    assert result.unchanged == ["training-111"]
    assert gc.events["training-111"].location == "Platz 1"


def test_event_without_an_address_gets_its_location_cleared():
    ev = _sp_event(start=SOON, end=SOON.replace(hour=21))
    gc = FakeGoogleCalendar()
    _located_service(FakeSpielerPlusWithLocations([ev], {"training-111": "Platz 1"}), gc).sync()

    result = _located_service(FakeSpielerPlusWithLocations([ev], {}), gc).sync()

    assert result.updated == ["training-111"]
    assert gc.updated[-1].location is None


def test_disabling_location_leaves_existing_locations_alone():
    ev = _sp_event(start=SOON, end=SOON.replace(hour=21))
    gc = FakeGoogleCalendar()
    _located_service(FakeSpielerPlusWithLocations([ev], {"training-111": "Platz 1"}), gc).sync()

    result = SyncService(FakeSpielerPlus([ev]), gc, now=lambda: NOW).sync()

    assert result.unchanged == ["training-111"]
