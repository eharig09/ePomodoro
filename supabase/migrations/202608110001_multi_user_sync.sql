-- ePomodoro multi-user sync foundation.
-- Run this migration in a Supabase project before enabling cloud sync clients.

create table if not exists public.sync_records (
    user_id uuid not null references auth.users(id) on delete cascade,
    entity_type text not null check (
        entity_type in (
            'local_task',
            'focus_session',
            'habit',
            'habit_checkin',
            'reflection'
        )
    ),
    entity_id text not null check (length(entity_id) between 1 and 300),
    payload jsonb not null default '{}'::jsonb check (jsonb_typeof(payload) = 'object'),
    client_updated_at timestamptz not null,
    device_id text not null check (length(device_id) between 1 and 200),
    deleted_at timestamptz,
    server_updated_at timestamptz not null default now(),
    primary key (user_id, entity_type, entity_id)
);

create index if not exists sync_records_user_server_updated_idx
    on public.sync_records (user_id, server_updated_at, entity_type, entity_id);

alter table public.sync_records enable row level security;
alter table public.sync_records force row level security;

drop policy if exists "Users read only their sync records" on public.sync_records;
create policy "Users read only their sync records"
    on public.sync_records for select
    to authenticated
    using ((select auth.uid()) = user_id);

drop policy if exists "Users insert only their sync records" on public.sync_records;
create policy "Users insert only their sync records"
    on public.sync_records for insert
    to authenticated
    with check ((select auth.uid()) = user_id);

drop policy if exists "Users update only their sync records" on public.sync_records;
create policy "Users update only their sync records"
    on public.sync_records for update
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

drop policy if exists "Users delete only their sync records" on public.sync_records;
create policy "Users delete only their sync records"
    on public.sync_records for delete
    to authenticated
    using ((select auth.uid()) = user_id);

-- Merge a client batch using deterministic last-write-wins semantics. A later
-- client timestamp wins; equal timestamps are broken by device ID so every
-- client converges on the same record even when devices sync concurrently.
create or replace function public.merge_sync_records(p_records jsonb)
returns integer
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
    item jsonb;
    merged_count integer := 0;
    affected integer := 0;
    current_user_id uuid := auth.uid();
begin
    if current_user_id is null then
        raise exception 'Authentication is required';
    end if;
    if jsonb_typeof(p_records) <> 'array' then
        raise exception 'p_records must be a JSON array';
    end if;
    if jsonb_array_length(p_records) > 1000 then
        raise exception 'A sync batch cannot exceed 1000 records';
    end if;

    for item in select value from jsonb_array_elements(p_records)
    loop
        if jsonb_typeof(item) <> 'object'
           or octet_length(coalesce((item->'payload')::text, '{}')) > 100000 then
            raise exception 'A sync record is invalid or too large';
        end if;
        insert into public.sync_records (
            user_id,
            entity_type,
            entity_id,
            payload,
            client_updated_at,
            device_id,
            deleted_at,
            server_updated_at
        ) values (
            current_user_id,
            item->>'entity_type',
            item->>'entity_id',
            coalesce(item->'payload', '{}'::jsonb),
            (item->>'client_updated_at')::timestamptz,
            item->>'device_id',
            nullif(item->>'deleted_at', '')::timestamptz,
            now()
        )
        on conflict (user_id, entity_type, entity_id) do update set
            payload = excluded.payload,
            client_updated_at = excluded.client_updated_at,
            device_id = excluded.device_id,
            deleted_at = excluded.deleted_at,
            server_updated_at = now()
        where
            (excluded.client_updated_at, excluded.device_id) >
            (sync_records.client_updated_at, sync_records.device_id);

        get diagnostics affected = row_count;
        merged_count := merged_count + affected;
    end loop;

    return merged_count;
end;
$$;

revoke all on function public.merge_sync_records(jsonb) from public;
revoke all on function public.merge_sync_records(jsonb) from anon;
grant execute on function public.merge_sync_records(jsonb) to authenticated;

grant select, insert, update, delete on public.sync_records to authenticated;
