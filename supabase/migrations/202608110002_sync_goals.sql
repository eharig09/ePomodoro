-- Preserve desktop goals and their task/habit links in multi-user sync.
alter table public.sync_records
    drop constraint if exists sync_records_entity_type_check;

alter table public.sync_records
    add constraint sync_records_entity_type_check check (
        entity_type in (
            'local_task',
            'focus_session',
            'habit',
            'habit_checkin',
            'reflection',
            'goal'
        )
    );
