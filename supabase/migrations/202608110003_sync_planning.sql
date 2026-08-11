-- Sync daily plans, rituals, weekly objectives, and weekly reviews.
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
            'goal',
            'daily_plan',
            'daily_ritual',
            'weekly_plan',
            'weekly_review'
        )
    );
